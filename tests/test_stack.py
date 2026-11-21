import shutil
import tomllib
import unittest
from pathlib import Path

from scripts.collect_packages import package_matches_tag, validate_registry
from scripts.soname_drift import drift, parse_files_database, parse_needed
from scripts.stack_plan import parse_srcinfo, plan, read_recipes

ROOT = Path(__file__).resolve().parent.parent


def recipe(directory, provides=(), depends=(), makedepends=()):
    lines = [f"pkgbase = {directory}", f"pkgname = {directory}"]
    lines += [f"\tprovides = {name}" for name in provides]
    lines += [f"\tdepends = {name}" for name in depends]
    lines += [f"\tmakedepends = {name}" for name in makedepends]
    return parse_srcinfo(directory, "\n".join(lines))


class PlanTests(unittest.TestCase):
    def test_dependencies_build_first_with_runtime_closure(self) -> None:
        order = plan(
            [
                recipe("app-git", depends=["toolkit-git", "glibc"]),
                recipe("toolkit-git", provides=["toolkit=1"], depends=["utils"], makedepends=["scanner-git"]),
                recipe("utils-git", provides=["utils=1", "libutils.so"]),
                recipe("scanner-git"),
            ]
        )
        names = [directory for directory, _ in order]
        self.assertLess(names.index("utils-git"), names.index("toolkit-git"))
        self.assertLess(names.index("toolkit-git"), names.index("app-git"))
        requirements = dict(order)
        self.assertEqual(requirements["toolkit-git"], ["scanner-git", "utils-git"])
        self.assertEqual(requirements["app-git"], ["toolkit-git", "utils-git"])

    def test_undeclared_package_is_never_installed(self) -> None:
        requirements = dict(
            plan([recipe("compositor-git", depends=["libs-git"]), recipe("libs-git"), recipe("disassembler-git")])
        )
        self.assertEqual(requirements["compositor-git"], ["libs-git"])

    def test_cycle_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cycle"):
            plan([recipe("a-git", depends=["b-git"]), recipe("b-git", depends=["a-git"])])

    def test_two_owners_of_one_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "provided by"):
            plan([recipe("a-git", provides=["thing"]), recipe("b-git", provides=["thing"])])


class DriftTests(unittest.TestCase):
    def test_bumped_library_is_reported_with_its_dependents(self) -> None:
        needed = {
            "hyprgraphics-git": {"libjxl.so.0.12", "libhyprutils.so.13", "libc.so.6"},
            "hyprlock-git": {"libhyprgraphics.so.5", "libc.so.6"},
        }
        shipped = {"libhyprutils.so.13", "libhyprgraphics.so.5"}
        self.assertEqual(
            drift(needed, shipped, {"libjxl.so.0.13", "libc.so.6"}),
            {"libjxl.so.0.12": ["hyprgraphics-git"]},
        )
        needed["hyprgraphics-git"] = {"libjxl.so.0.13", "libhyprutils.so.13", "libc.so.6"}
        self.assertEqual(drift(needed, shipped, {"libjxl.so.0.13", "libc.so.6"}), {})

    def test_private_libraries_shipped_by_the_stack_are_not_drift(self) -> None:
        needed = {"hyprland-qt-support-git": {"libhyprland-quick-style.so"}}
        self.assertEqual(drift(needed, {"libhyprland-quick-style.so"}, set()), {})

    def test_only_the_library_directory_counts_as_available(self) -> None:
        output = "\n".join(
            [
                "extra\0libjxl\0" "0.13.0-1\0usr/lib/libjxl.so.0.13",
                "extra\0nsight-systems\0" "1-1\0usr/lib/nsight-systems/host/libQt6Core.so.6",
                "core\0lib32-glibc\0" "2.44-1\0usr/lib32/libc.so.6",
            ]
        )
        self.assertEqual(parse_files_database(output), {"libjxl.so.0.13"})

    def test_needed_entries_come_from_readelf_output(self) -> None:
        output = (
            " 0x0000000000000001 (NEEDED)             Shared library: [libjxl.so.0.13]\n"
            " 0x000000000000000e (SONAME)             Library soname: [libhyprgraphics.so.5]\n"
        )
        self.assertEqual(parse_needed(output), {"libjxl.so.0.13"})


class StackReleaseTests(unittest.TestCase):
    def test_pkgrel_release_matches_on_pkgrel_only(self) -> None:
        self.assertTrue(package_matches_tag("0.6.0.r3.g3440042-7", "v7", "pkgrel"))
        self.assertFalse(package_matches_tag("0.6.0.r3.g3440042-6", "v7", "pkgrel"))
        self.assertFalse(package_matches_tag("7-1", "v7", "pkgrel"))

    def test_unknown_versioning_is_rejected(self) -> None:
        document = {
            "schema": 1,
            "release": [{"repository": "one", "packages": ["a"], "versioning": "date"}],
        }
        with self.assertRaisesRegex(RuntimeError, "versioning"):
            validate_registry(document)

    def test_registry_lists_exactly_the_stack_pkgbuilds(self) -> None:
        with (ROOT / "packages.toml").open("rb") as handle:
            document = tomllib.load(handle)
        validate_registry(document)
        (release,) = [r for r in document["release"] if r["repository"] == "arch-repo"]
        self.assertEqual(release.get("versioning"), "pkgrel")
        directories = {path.parent.name for path in (ROOT / "pkgbuilds").glob("*/PKGBUILD")}
        self.assertEqual(set(release["packages"]), directories)

    @unittest.skipUnless(shutil.which("makepkg"), "needs makepkg")
    def test_each_directory_is_named_after_its_package(self) -> None:
        for item in read_recipes(ROOT / "pkgbuilds"):
            self.assertIn(item.directory, item.names)


if __name__ == "__main__":
    unittest.main()

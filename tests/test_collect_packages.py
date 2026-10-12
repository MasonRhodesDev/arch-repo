import unittest

from scripts.collect_packages import index_key, release_version, validate_registry


class RegistryTests(unittest.TestCase):
    def test_release_version_strips_pkgrel_and_epoch(self) -> None:
        self.assertEqual(release_version("2.2.0-1"), "2.2.0")
        self.assertEqual(release_version("1:2.2.0-3"), "2.2.0")

    def test_duplicate_package_owner_is_rejected(self) -> None:
        document = {
            "schema": 1,
            "release": [
                {"repository": "one", "packages": ["shared"]},
                {"repository": "two", "packages": ["shared"]},
            ],
        }
        with self.assertRaisesRegex(RuntimeError, "multiple owners"):
            validate_registry(document)

    def test_empty_package_set_is_rejected(self) -> None:
        document = {
            "schema": 1,
            "release": [{"repository": "one", "packages": []}],
        }
        with self.assertRaisesRegex(RuntimeError, "no expected packages"):
            validate_registry(document)


class MultiArchTests(unittest.TestCase):
    """A release now carries one build per architecture.

    Keying on the package name alone made the second build look like a
    duplicate, which broke every publish once hyprstate v2.7.4-2 shipped both
    an x86_64 and an aarch64 package.
    """

    def test_same_package_for_two_architectures_is_not_a_duplicate(self) -> None:
        seen = {}
        for architecture in ("x86_64", "aarch64"):
            key = index_key("hyprstate", architecture)
            self.assertNotIn(key, seen)
            seen[key] = f"hyprstate-2.7.4-2-{architecture}.pkg.tar.zst"
        self.assertEqual(len(seen), 2)

    def test_same_package_and_architecture_twice_is_a_duplicate(self) -> None:
        self.assertEqual(
            index_key("hyprstate", "x86_64"), index_key("hyprstate", "x86_64")
        )

    def test_expected_set_is_satisfied_once_per_name(self) -> None:
        actual = {
            index_key("waybar-workspace-buttons", "x86_64"): "a",
            index_key("waybar-workspace-buttons", "aarch64"): "b",
            index_key("hyprland-workspace-zones", "x86_64"): "c",
            index_key("hyprland-workspace-zones", "aarch64"): "d",
        }
        names = {name for name, _ in actual}
        self.assertEqual(
            names, {"waybar-workspace-buttons", "hyprland-workspace-zones"}
        )

    def test_arch_any_keys_on_any(self) -> None:
        self.assertEqual(index_key("hypr-de", "any"), ("hypr-de", "any"))


if __name__ == "__main__":
    unittest.main()

import unittest

from scripts.collect_packages import release_version, validate_registry


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


if __name__ == "__main__":
    unittest.main()

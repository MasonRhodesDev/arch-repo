#!/usr/bin/env python3
"""Collect and validate the complete package set from latest releases."""

import argparse
import hashlib
import json
import os
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path


def run(arguments: list[str]) -> str:
    process = subprocess.run(arguments, check=False, capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "command failed")
    return process.stdout


def package_metadata(path: Path) -> tuple[str, str]:
    content = run(["bsdtar", "-xOf", str(path), ".PKGINFO"])
    values = {}
    for line in content.splitlines():
        if " = " in line:
            key, value = line.split(" = ", 1)
            values.setdefault(key, value)
    try:
        return values["pkgname"], values["pkgver"]
    except KeyError as error:
        raise RuntimeError(f"{path.name} has incomplete .PKGINFO") from error


def release_version(package_version: str) -> str:
    value = package_version.rsplit("-", 1)[0]
    return value.split(":", 1)[-1]


def validate_registry(document: dict) -> None:
    if document.get("schema") != 1:
        raise RuntimeError("packages.toml must use schema = 1")
    repositories = set()
    packages = set()
    for release in document.get("release", []):
        repository = release.get("repository")
        expected = release.get("packages", [])
        if not repository or repository in repositories:
            raise RuntimeError(f"duplicate or empty repository: {repository!r}")
        repositories.add(repository)
        if not expected:
            raise RuntimeError(f"{repository} has no expected packages")
        for package in expected:
            if package in packages:
                raise RuntimeError(f"package {package} has multiple owners")
            packages.add(package)


def collect(manifest: Path, output: Path) -> dict:
    with manifest.open("rb") as handle:
        document = tomllib.load(handle)
    validate_registry(document)

    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {output}")

    owner = document["owner"]
    collected = []
    for release in document["release"]:
        repository = release["repository"]
        expected_packages = set(release["packages"])
        release_document = json.loads(
            run(["gh", "api", f"repos/{owner}/{repository}/releases/latest"])
        )
        tag = release_document["tag_name"]
        if not tag.startswith("v") or len(tag) == 1:
            raise RuntimeError(f"{repository} latest tag is not v-prefixed: {tag}")
        expected_version = tag[1:]
        package_assets = [
            asset["name"]
            for asset in release_document.get("assets", [])
            if asset["name"].endswith(".pkg.tar.zst")
        ]
        if not package_assets:
            raise RuntimeError(f"{repository} {tag} has no package assets")

        before = set(output.iterdir())
        run(
            [
                "gh",
                "release",
                "download",
                tag,
                "--repo",
                f"{owner}/{repository}",
                "--pattern",
                "*.pkg.tar.zst",
                "--dir",
                str(output),
            ]
        )
        downloaded = sorted(set(output.iterdir()) - before)
        actual_packages = {}
        package_rows = []
        for path in downloaded:
            package, package_version = package_metadata(path)
            if package in actual_packages:
                raise RuntimeError(
                    f"{repository} {tag} contains duplicate package {package}"
                )
            if release_version(package_version) != expected_version:
                raise RuntimeError(
                    f"{path.name} version {package_version} does not match {tag}"
                )
            actual_packages[package] = path.name
            package_rows.append(
                {
                    "name": package,
                    "version": package_version,
                    "file": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )

        if set(actual_packages) != expected_packages:
            missing = sorted(expected_packages - set(actual_packages))
            unexpected = sorted(set(actual_packages) - expected_packages)
            raise RuntimeError(
                f"{repository} {tag} package mismatch; "
                f"missing={missing}, unexpected={unexpected}"
            )
        collected.append(
            {
                "repository": repository,
                "tag": tag,
                "packages": sorted(package_rows, key=lambda row: row["name"]),
            }
        )

    result = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
        f"{os.environ.get('GITHUB_REPOSITORY', 'MasonRhodesDev/arch-repo')}",
        "releases": collected,
    }
    (output.parent / "manifest.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("packages.toml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = collect(args.manifest, args.output)
    package_count = sum(
        len(release["packages"]) for release in result["releases"]
    )
    print(
        f"collected {package_count} packages from "
        f"{len(result['releases'])} releases"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

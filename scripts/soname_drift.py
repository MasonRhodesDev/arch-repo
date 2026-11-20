#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SENTINEL = "libc.so.6"
NEEDED = re.compile(r"\(NEEDED\)\s+Shared library: \[(.+)\]")


def run(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, capture_output=True, text=True)


def parse_needed(readelf_output: str) -> set[str]:
    return set(NEEDED.findall(readelf_output))


def parse_files_database(output: str) -> set[str]:
    available = set()
    for line in output.splitlines():
        fields = line.split("\0")
        if len(fields) == 4 and fields[3] == "usr/lib/" + Path(fields[3]).name:
            available.add(Path(fields[3]).name)
    return available


def drift(
    needed: dict[str, set[str]], shipped: set[str], available: set[str]
) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for package, sonames in needed.items():
        for soname in sonames - shipped - available:
            missing.setdefault(soname, []).append(package)
    return {soname: sorted(packages) for soname, packages in sorted(missing.items())}


def inspect(package: Path) -> tuple[set[str], set[str]]:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        extracted = run(["bsdtar", "-xf", str(package), "-C", scratch])
        if extracted.returncode:
            raise RuntimeError(f"cannot extract {package.name}: {extracted.stderr.strip()}")
        shipped, needed = set(), set()
        for path in root.rglob("*"):
            if path.is_symlink() or path.is_file():
                shipped.add(path.name)
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as handle:
                if handle.read(4) != b"\x7fELF":
                    continue
            needed |= parse_needed(run(["readelf", "-dW", str(path)]).stdout)
        return shipped, needed


def package_name(package: Path) -> str:
    return package.name.rsplit("-", 3)[0]


def available_sonames(sonames: set[str]) -> set[str]:
    result = run(["pacman", "-F", "--machinereadable", SENTINEL, *sorted(sonames)])
    available = parse_files_database(result.stdout)
    if SENTINEL not in available:
        raise RuntimeError(
            f"pacman files database did not resolve {SENTINEL}; run pacman -Fy first. "
            + result.stderr.strip()
        )
    return available


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packages", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        shipped, needed = set(), {}
        for package in args.packages:
            files, sonames = inspect(package)
            shipped |= files
            needed[package_name(package)] = sonames
        external = set().union(*needed.values()) - shipped
        missing = drift(needed, shipped, available_sonames(external))
    except (RuntimeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"checked {len(needed)} packages, {len(external)} external sonames")
    for soname, packages in missing.items():
        print(f"missing {soname}: {' '.join(packages)}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

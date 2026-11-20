#!/usr/bin/env python3

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Recipe:
    directory: str
    names: frozenset[str]
    runtime: frozenset[str]
    build: frozenset[str]


def bare(dependency: str) -> str:
    return re.split(r"[<>=]", dependency, maxsplit=1)[0]


def parse_srcinfo(directory: str, text: str) -> Recipe:
    names, runtime, build = set(), set(), set()
    for line in text.splitlines():
        if " = " not in line:
            continue
        key, value = (part.strip() for part in line.split(" = ", 1))
        if key in ("pkgname", "provides"):
            names.add(bare(value))
        elif key == "depends":
            runtime.add(bare(value))
        elif key == "makedepends":
            build.add(bare(value))
    return Recipe(directory, frozenset(names), frozenset(runtime), frozenset(build))


def plan(recipes: list[Recipe]) -> list[tuple[str, list[str]]]:
    owner = {}
    for recipe in recipes:
        for name in recipe.names:
            if name in owner and owner[name] != recipe.directory:
                raise ValueError(f"{name} is provided by {owner[name]} and {recipe.directory}")
            owner[name] = recipe.directory
    by_directory = {recipe.directory: recipe for recipe in recipes}

    def stack(names: frozenset[str], directory: str) -> set[str]:
        return {owner[name] for name in names if name in owner} - {directory}

    runtime_closure: dict[str, set[str]] = {}

    def runtime_of(directory: str, trail: tuple[str, ...]) -> set[str]:
        if directory in trail:
            raise ValueError("dependency cycle: " + " -> ".join(trail + (directory,)))
        if directory not in runtime_closure:
            closure = set()
            for dependency in stack(by_directory[directory].runtime, directory):
                closure |= {dependency} | runtime_of(dependency, trail + (directory,))
            runtime_closure[directory] = closure
        return runtime_closure[directory]

    requirements = {}
    for recipe in recipes:
        direct = stack(recipe.runtime | recipe.build, recipe.directory)
        closure = set(direct)
        for dependency in direct:
            closure |= runtime_of(dependency, (recipe.directory,))
        if recipe.directory in closure:
            raise ValueError(f"dependency cycle through {recipe.directory}")
        requirements[recipe.directory] = closure

    ordered, done = [], set()
    while len(ordered) < len(recipes):
        ready = sorted(
            directory
            for directory, closure in requirements.items()
            if directory not in done and closure <= done
        )
        if not ready:
            raise ValueError("dependency cycle among " + ", ".join(sorted(set(requirements) - done)))
        for directory in ready:
            ordered.append((directory, sorted(requirements[directory])))
            done.add(directory)
    return ordered


def read_recipes(root: Path) -> list[Recipe]:
    recipes = []
    for pkgbuild in sorted(root.glob("*/PKGBUILD")):
        text = subprocess.run(
            ["makepkg", "--printsrcinfo"],
            cwd=pkgbuild.parent,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        recipes.append(parse_srcinfo(pkgbuild.parent.name, text))
    return recipes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    for directory, requirements in plan(read_recipes(args.root)):
        print(" ".join([directory, *requirements]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

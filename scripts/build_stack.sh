#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 3 ] || ! [[ $2 =~ ^[1-9][0-9]*$ ]]; then
  echo "usage: $0 <builder-user> <pkgrel> <output-dir>" >&2
  exit 2
fi
builder=$1
pkgrel=$2
root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$3"
out=$(cd "$3" && pwd)
work=$(mktemp -d)
cp -r "$root/pkgbuilds/." "$work/"
chown -R "$builder": "$out" "$work"

plan=$(su "$builder" -c "python '$root/scripts/stack_plan.py' '$work'")
stack=$(cut -d' ' -f1 <<<"$plan")
echo "$plan"

while read -r -u 3 directory requirements; do
  echo "::group::$directory"
  installed=$(pacman -Qq $stack 2>/dev/null || true)
  if [ -n "$installed" ]; then
    pacman -Rdd --noconfirm $installed
  fi
  files=()
  for requirement in $requirements; do
    files+=("$out/$requirement"/*.pkg.tar.zst)
  done
  if [ ${#files[@]} -gt 0 ]; then
    pacman -U --noconfirm "${files[@]}"
  fi
  mkdir -p "$out/$directory"
  chown "$builder": "$out/$directory"
  su "$builder" -c "cd '$work/$directory' && makepkg -od --noconfirm"
  sed -i "s/^pkgrel=.*/pkgrel=$pkgrel/" "$work/$directory/PKGBUILD"
  su "$builder" -c "cd '$work/$directory' && PKGDEST='$out/$directory' PKGEXT=.pkg.tar.zst makepkg -se --noconfirm"
  ls "$out/$directory"/*.pkg.tar.zst
  echo "::endgroup::"
done 3<<<"$plan"

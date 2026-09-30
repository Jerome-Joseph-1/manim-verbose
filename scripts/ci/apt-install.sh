#!/usr/bin/env bash
# Installs the Ubuntu packages a CI job needs, named by group:
#
#     scripts/ci/apt-install.sh pango ffmpeg vulkan tex
#
# Each group is a list in scripts/ci/apt/<group>.txt saying why each package is there. Nothing
# a package only recommends is installed, so the lists have to be complete on their own; that
# is what CI checks, a developer's machine usually having more.
#
# Set APT_ARCHIVES to a directory to download the .debs into and install from, so a job can
# keep them with actions/cache. TeX Live is most of a gigabyte of downloads.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
packages=()
for group in "$@"; do
    list="$here/apt/$group.txt"
    if [[ ! -f "$list" ]]; then
        echo "No package group '$group'; the groups are the files in $here/apt" >&2
        exit 2
    fi
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"
        line="${line//[[:space:]]/}"
        if [[ -n "$line" ]]; then
            packages+=("$line")
        fi
    done < "$list"
done
if (( ${#packages[@]} == 0 )); then
    echo "usage: $0 GROUP..." >&2
    exit 2
fi

sudo=()
if [[ "$(id -u)" -ne 0 ]]; then
    sudo=(sudo)
fi

# man-db re-indexes after every install, which after TeX Live takes minutes
echo "man-db man-db/auto-update boolean false" | "${sudo[@]}" debconf-set-selections
"${sudo[@]}" rm -f /var/lib/man-db/auto-update

options=(-y -q --no-install-recommends -o Dpkg::Options::=--force-unsafe-io)
if [[ -n "${APT_ARCHIVES:-}" ]]; then
    mkdir -p "$APT_ARCHIVES/partial"
    # A directory of the user's is no place apt's own unprivileged user can write to
    options+=(-o "Dir::Cache::Archives=$APT_ARCHIVES" -o APT::Sandbox::User=root)
fi

echo "Installing: ${packages[*]}"
"${sudo[@]}" apt-get update -q
"${sudo[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install "${options[@]}" "${packages[@]}"

if [[ -n "${APT_ARCHIVES:-}" ]]; then
    # Drop superseded versions, so a cache saved from here does not grow forever, and give
    # the lot back to the user the cache action runs as
    "${sudo[@]}" apt-get -q -o "Dir::Cache::Archives=$APT_ARCHIVES" autoclean
    "${sudo[@]}" rm -rf "$APT_ARCHIVES/lock" "$APT_ARCHIVES/partial"
    "${sudo[@]}" chown -R "$(id -u):$(id -g)" "$APT_ARCHIVES"
    du -sh "$APT_ARCHIVES"
fi

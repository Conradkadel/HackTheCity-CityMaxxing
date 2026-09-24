#!/usr/bin/env bash
set -euo pipefail

repository="kudzus/project7-prototype"
release="database-v1"
output_dir="exports"
archive="headway-carris-all-carris.dump"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is required: https://cli.github.com/" >&2
  exit 2
fi

mkdir -p "$output_dir"
gh release download "$release" \
  --repo "$repository" \
  --pattern "$archive" \
  --pattern "$archive.sha256" \
  --dir "$output_dir" \
  --clobber

(
  cd "$output_dir"
  shasum -a 256 -c "$archive.sha256"
)

echo "Downloaded and verified $output_dir/$archive"

#!/usr/bin/env bash
set -euo pipefail

mode="${1:-all-carris}"
output="${2:-exports/headway-carris-${mode}.dump}"
target_database="headway_carris_export"

case "$mode" in
  all-carris|configured-lines|challenge-areas) ;;
  *)
    echo "Usage: $0 [all-carris|configured-lines|challenge-areas] [output.dump]" >&2
    exit 2
    ;;
esac

mkdir -p "$(dirname "$output")"
temporary="${output}.partial"
cleanup() {
  rm -f "$temporary"
  docker compose exec -T db dropdb -U headway --if-exists --force "$target_database" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose up -d --build --wait db api
docker compose run --rm api python export_database.py \
  --target-database "$target_database" --mode "$mode" --replace
docker compose exec -T db pg_dump -U headway -d "$target_database" \
  --format=custom --compress=9 --no-owner --no-acl > "$temporary"
mv "$temporary" "$output"
checksum="$(shasum -a 256 "$output" | awk '{print $1}')"
printf '%s  %s\n' "$checksum" "$(basename "$output")" > "${output}.sha256"
docker compose exec -T db dropdb -U headway --if-exists --force "$target_database"
trap - EXIT

echo "Created $output"
du -h "$output"
cat "${output}.sha256"

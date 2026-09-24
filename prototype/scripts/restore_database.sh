#!/usr/bin/env bash
set -euo pipefail

archive="${1:-}"
confirmation="${2:-}"

if [[ -z "$archive" || "$confirmation" != "--replace" ]]; then
  echo "Usage: $0 path/to/database.dump --replace" >&2
  echo "This replaces the local Compose database named headway." >&2
  exit 2
fi
if [[ ! -f "$archive" ]]; then
  echo "Archive not found: $archive" >&2
  exit 2
fi

docker compose stop api >/dev/null 2>&1 || true
docker compose up -d --wait db
docker compose exec -T db dropdb -U headway --if-exists --force headway
docker compose exec -T db createdb -U headway -O headway headway
docker compose exec -T db pg_restore -U headway -d headway \
  --exit-on-error --no-owner --no-acl < "$archive"
docker compose up -d --build --wait api

echo "Database restored. Open http://127.0.0.1:5173 after running npm run dev."

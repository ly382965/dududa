#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DB_PATH="${DB_PATH:-data/icourse.sqlite3}"
REQUEST_DELAY="${REQUEST_DELAY:-1.0}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

cd "$ROOT"
exec "$PYTHON" "$ROOT/run_icourse_mcp.py" --db-path "$DB_PATH" --request-delay "$REQUEST_DELAY"

#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV_PATH="${VENV_PATH:-.venv}"

cd "$ROOT"
"$PYTHON" -m venv "$VENV_PATH"
"$VENV_PATH/bin/python" -m pip install --upgrade pip
"$VENV_PATH/bin/python" -m pip install -r requirements.txt
"$VENV_PATH/bin/python" -m pip install -e .

echo "iCourse MCP environment is ready:"
echo "  $ROOT/$VENV_PATH/bin/python -m icourse_mcp.server"

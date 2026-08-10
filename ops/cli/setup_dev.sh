#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' \
    '未找到 uv。请先按 docs/development/local-environment.md 安装 uv。' >&2
  exit 1
fi

PYTHON_VERSION="${DUDUDA_PYTHON_VERSION:-3.12.13}"

uv python install "$PYTHON_VERSION"
uv sync --locked --python "$PYTHON_VERSION"
uv run --locked python -c \
  'import bs4, httpx, icourse_mcp, jsonschema, mcp, PIL, dududa; print("imports: ok")'

printf '%s\n' \
  '本地开发环境已就绪。' \
  '激活命令：source .venv/bin/activate' \
  '测试命令：PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m unittest discover -s tests -v'

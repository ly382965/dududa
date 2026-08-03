#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' \
    '未找到 uv。请先按 docs/development/local-environment.md 安装 uv。' >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  uv venv --seed --python /usr/bin/python3 .venv
fi

uv pip install --python .venv/bin/python \
  -r plugins/astrbot_plugin_dududa_core/requirements.txt \
  -e packages/dududa-agent \
  -e services/icourse-mcp
uv pip check --python .venv/bin/python

printf '%s\n' \
  '本地开发环境已就绪。' \
  '激活命令：source .venv/bin/activate' \
  '测试命令：PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v'

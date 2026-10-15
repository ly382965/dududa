#!/usr/bin/env bash
set -euo pipefail

plugin_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
worker_env="${1:-/AstrBot/data/plugin_data/astrbot_plugin_dududa_notify/worker-venv}"
uv venv --python 3.12 --allow-existing "$worker_env"
uv pip install --python "$worker_env/bin/python" -r "$plugin_dir/worker-requirements.txt"
"$worker_env/bin/python" -c 'import seminar_radar.auth, seminar_radar.client, seminar_radar.reports, pypdf, docx, reportlab, markdown_it, lxml, pptx, fontTools'

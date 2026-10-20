#!/usr/bin/env bash
# Build the notify feature's campus worker venv (SeminarRadar, pypdf, reportlab, lxml, ...).
# Usage: ops/cli/install_notify_worker.sh <venv_dir>
# Production: <runtime state_dir>/features/notify/worker-venv (the default `worker_python`).
# Legacy .ppt/.doc course files additionally need host packages: catdoc libreoffice-impress-nogui.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <venv_dir>" >&2
  exit 2
fi
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
requirements="$repo/packages/dududa-runtime/src/dududa_v3/features/notify/worker-requirements.txt"
venv="$1"

uv venv --python 3.12 --allow-existing "$venv"
uv pip install --python "$venv/bin/python" -r "$requirements"
"$venv/bin/python" -c 'import seminar_radar.auth, seminar_radar.client, seminar_radar.reports, pypdf, docx, reportlab, markdown_it, lxml, pptx, fontTools, httpx'
echo "notify worker ready: $venv/bin/python"

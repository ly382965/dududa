#!/usr/bin/env bash
# Copy the AstrBot notify plugin state (dedupe history, homework/course/weekly SQLite, fonts,
# portal diagnostics) out of the AstrBot container into the Host notify state dir, unchanged.
# The worker venv is not copied: build it with ops/cli/install_notify_worker.sh.
# Usage: ops/cli/migrate_notify_state.sh <target_dir>
# Production target: <runtime state_dir>/features/notify. Stop AstrBot first so the SQLite
# files are not copied mid-write.
set -euo pipefail

container="${DUDUDA_ASTRBOT_CONTAINER:-dududa-astrbot-1}"
source_dir="/AstrBot/data/plugin_data/astrbot_plugin_dududa_notify"

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <target_dir>" >&2
  exit 2
fi
target="$1"
mkdir -p "$target"
if [[ -n "$(ls -A "$target" | grep -v '^worker-venv$' || true)" ]]; then
  echo "refusing to overwrite: $target is not empty" >&2
  exit 1
fi

# `docker cp` works on stopped containers (AstrBot must be stopped first); `docker exec` would not.
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
docker cp "$container:$source_dir/." "$staging/"
rm -rf "$staging/worker-venv"
copied=0
for entry in "$staging"/* "$staging"/.[!.]*; do
  [[ -e "$entry" ]] || continue
  mv "$entry" "$target/"
  copied=$((copied + 1))
done
chmod 700 "$target"
for entry in "$target"/homework-* "$target"/courses-* "$target"/weekly-* "$target"/portal-diagnostics; do
  if [[ -d "$entry" ]]; then chmod 700 "$entry"; fi
done
echo "copied $copied entries into $target (worker-venv excluded)"

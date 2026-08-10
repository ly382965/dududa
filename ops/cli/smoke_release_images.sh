#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${DUDUDA_REPOSITORY_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT_DIR"

revision="$(git rev-parse --verify HEAD)"
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "invalid_candidate_revision" >&2
  exit 2
fi

suffix="${revision:0:12}-$$"
astrbot_tag="dududa-s19-astrbot:${suffix}"
web_tag="dududa-s19-web:${suffix}"
web_container="dududa-s19-web-${suffix}"
temporary_root="$(mktemp -d -t dududa-s19-images.XXXXXX)"
token_file="$temporary_root/onebot-token"

cleanup() {
  docker rm -f "$web_container" >/dev/null 2>&1 || true
  rm -rf -- "$temporary_root"
}
trap cleanup EXIT INT TERM

umask 077
printf '%s\n' 's19-disposable-token-not-a-runtime-secret' >"$token_file"

docker build \
  --file deploy/docker/astrbot/Dockerfile \
  --tag "$astrbot_tag" \
  . >&2
docker build \
  --file deploy/docker/web/Dockerfile \
  --tag "$web_tag" \
  . >&2

astrbot_image_id="$(docker image inspect --format '{{.Id}}' "$astrbot_tag")"
web_image_id="$(docker image inspect --format '{{.Id}}' "$web_tag")"
image_id_pattern='^sha256:[0-9a-f]{64}$'
if [[ ! "$astrbot_image_id" =~ $image_id_pattern || ! "$web_image_id" =~ $image_id_pattern ]]; then
  echo "invalid_built_image_id" >&2
  exit 2
fi

docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,size=128m \
  --volume "$ROOT_DIR:/workspace:ro" \
  --volume "$ROOT_DIR/configs:/opt/dududa/config:ro" \
  --workdir /tmp \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --env PYTHONPATH=/workspace/apps/astrbot-plugins:/workspace \
  --env ASTRBOT_ROOT=/tmp/astrbot \
  --entrypoint /bin/sh \
  "$astrbot_tag" \
  -ec '
    python -m pip check
    python -c '\''import importlib.metadata as m; assert m.version("dududa-agent") == "0.1.0a1"; assert m.version("mcp") == "1.29.0"'\''
    /opt/dududa/unified-mcp-worker/.venv/bin/python -c '\''import importlib.metadata as m; assert m.version("mcp") == "2.0.0"'\''
    python -c '\''import asyncio; from pathlib import Path; from astrbot_plugin_dududa_core.adapters.mcp_runtime import build_icourse_client; client, mode, reason = build_icourse_client({}, registry_directory=Path("/opt/dududa/config/mcp/servers"), worker_python=Path("/opt/dududa/unified-mcp-worker/.venv/bin/python")); assert (mode, reason) == ("unified", "unified_ready"); asyncio.run(client.close())'\''
    ICOURSE_MCP_DB_PATH=/tmp/icourse.sqlite3 python /opt/dududa/icourse-mcp/scripts/check_mcp.py
    cd /workspace
    python -m unittest -v tests.test_dududa_core_plugin_split tests.contracts.test_production_composition tests.unit.mcp.test_icourse_facade
  ' >&2

docker run --detach \
  --name "$web_container" \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,size=64m \
  --volume "$token_file:/run/secrets/onebot_access_token:ro" \
  "$web_tag" >/dev/null

web_ready=false
for _ in $(seq 1 40); do
  if docker exec "$web_container" node -e '
    fetch("http://127.0.0.1:8000/api/health", {headers: {host: "127.0.0.1:8000"}})
      .then(async response => {
        const value = await response.json()
        if (!response.ok || typeof value !== "object" || value === null) process.exit(1)
      })
      .catch(() => process.exit(1))
  ' >/dev/null 2>&1; then
    web_ready=true
    break
  fi
  sleep 0.25
done
if [[ "$web_ready" != true ]]; then
  echo "web_image_health_failed" >&2
  exit 1
fi

printf '{"astrbot_image_id":"%s","status":"passed","web_image_id":"%s"}\n' \
  "$astrbot_image_id" "$web_image_id"

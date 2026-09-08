#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PYTHON="${PYTHON:-python3}"

ENV_FILE=".env"
if [[ ! -f "$ENV_FILE" ]]; then
  ENV_FILE="deploy/env/.env.example"
fi

env_value() {
  local key="$1"
  local file="$2"
  awk -F= -v key="$key" '$1 == key { print substr($0, index($0, "=") + 1); exit }' "$file" 2>/dev/null | tr -d "\"'"
}

data_root() {
  local root
  root="${STACK_DATA_ROOT:-$(env_value STACK_DATA_ROOT "$ENV_FILE")}"
  root="${root:-./data}"
  if [[ "$root" = /* ]]; then
    printf '%s\n' "$root"
  else
    printf '%s\n' "$ROOT_DIR/${root#./}"
  fi
}

web_data_root() {
  local root
  root="${DUDUDA_WEB_DATA_ROOT:-$(env_value DUDUDA_WEB_DATA_ROOT "$ENV_FILE")}"
  root="${root:-./runtime/web}"
  if [[ "$root" = /* ]]; then
    printf '%s\n' "$root"
  else
    printf '%s\n' "$ROOT_DIR/${root#./}"
  fi
}

api_key_store_root() {
  local root candidate resolved repository_root
  root="${DUDUDA_API_KEY_STORE_ROOT:-$(env_value DUDUDA_API_KEY_STORE_ROOT "$ENV_FILE")}"
  root="${root:-../dududa-state/api-keys}"
  if [[ "$root" = /* ]]; then
    candidate="$root"
  else
    candidate="$ROOT_DIR/${root#./}"
  fi
  resolved="$(realpath -m -- "$candidate")"
  repository_root="$(realpath -m -- "$ROOT_DIR")"
  if [[ "$resolved" == "/" || "$resolved" == "$repository_root" || "$resolved" == "$repository_root/"* ]]; then
    printf 'DUDUDA_API_KEY_STORE_ROOT must resolve outside the repository: %s\n' "$resolved" >&2
    return 1
  fi
  printf '%s\n' "$resolved"
}

astrbot_plugin_root() {
  local root
  root="${DUDUDA_ASTRBOT_PLUGIN_ROOT:-$(env_value DUDUDA_ASTRBOT_PLUGIN_ROOT "$ENV_FILE")}"
  root="${root:-./runtime/astrbot-plugins}"
  if [[ "$root" = /* ]]; then
    printf '%s\n' "$root"
  else
    printf '%s\n' "$ROOT_DIR/${root#./}"
  fi
}

ensure_agent_policy_root() {
  local configured candidate repository_root
  configured="${DUDUDA_AGENT_POLICY_ROOT:-$(env_value DUDUDA_AGENT_POLICY_ROOT "$ENV_FILE")}"
  configured="${configured:-../dududa-state/agent}"
  if [[ "$configured" = /* ]]; then
    candidate="$(realpath -m -- "$configured")"
  else
    candidate="$(realpath -m -- "$ROOT_DIR/$configured")"
  fi
  repository_root="$(realpath -m -- "$ROOT_DIR")"
  if [[ "$candidate" == "/" || "$candidate" == "$repository_root" || "$candidate" == "$repository_root/"* ]]; then
    printf 'DUDUDA_AGENT_POLICY_ROOT must resolve outside the repository\n' >&2
    return 1
  fi
  mkdir -p "$candidate"
  chmod 700 "$candidate"
  _uid="$(stat -c '%u' "$candidate" 2>/dev/null || echo 1000)"
  if [[ "$_uid" != "1000" ]] && [[ -z "${MSYSTEM:-}" ]]; then
    printf 'Agent policy directory must be owned by UID 1000: %s\n' "$candidate" >&2
    return 1
  fi
}

ensure_web_secrets() {
  local root token_file plugin_key_file api_key_root api_key_file api_key_root_uid api_key_file_uid
  root="$(web_data_root)"
  mkdir -p "$root/secrets"
  chmod 700 "$root" "$root/secrets" 2>/dev/null || true
  token_file="$root/secrets/onebot_access_token"
  if [[ ! -f "$token_file" ]]; then
    if command -v openssl >/dev/null 2>&1; then
      openssl rand -hex 32 >"$token_file"
    else
      od -An -N32 -tx1 /dev/urandom | tr -d ' \n' >"$token_file"
    fi
  fi
  chmod 600 "$token_file"
  plugin_key_file="$root/secrets/astrbot_plugin_api_key"
  if [[ ! -e "$plugin_key_file" ]]; then
    : >"$plugin_key_file"
  fi
  chmod 600 "$plugin_key_file"
  api_key_root="$(api_key_store_root)"
  mkdir -p "$api_key_root"
  chmod 700 "$api_key_root" 2>/dev/null || true
  api_key_file="$api_key_root/api-keys.json"
  if [[ ! -e "$api_key_file" ]]; then
    printf '%s\n' '{"schemaVersion":1,"revision":1,"pools":{}}' >"$api_key_file"
  fi
  chmod 600 "$api_key_file"
  api_key_root_uid="$(stat -c '%u' "$api_key_root")"
  api_key_file_uid="$(stat -c '%u' "$api_key_file")"
  if [[ "$api_key_root_uid" != "1000" || "$api_key_file_uid" != "1000" ]] && [[ -z "${MSYSTEM:-}" ]]; then
    printf 'API Key store must be owned by UID 1000 for the Web container: %s\n' "$api_key_root" >&2
    return 1
  fi
  ensure_agent_policy_root
}

project_name() {
  local name
  name="${COMPOSE_PROJECT_NAME:-$(env_value COMPOSE_PROJECT_NAME "$ENV_FILE")}"
  printf '%s\n' "${name:-dududa}"
}

DOCKER_READY=0
declare -a DOCKER COMPOSE

setup_docker() {
  if [[ "$DOCKER_READY" == "1" ]]; then
    return
  fi
  if docker info >/dev/null 2>&1; then
    DOCKER=(docker)
  else
    DOCKER=(sudo docker)
  fi
  COMPOSE=(
    "${DOCKER[@]}" compose
    --project-directory "$ROOT_DIR"
    --env-file "$ENV_FILE"
    -f "$ROOT_DIR/deploy/compose/compose.yml"
    -p "$(project_name)"
  )
  DOCKER_READY=1
}

ops_cli() {
  "$PYTHON" ops/cli/dududa_ops.py "$@"
}

ensure_edge_network() {
  local network
  setup_docker
  network="${EDGE_NETWORK:-$(env_value EDGE_NETWORK "$ENV_FILE")}"
  network="${network:-mmdustc-edge}"
  if ! "${DOCKER[@]}" network inspect "$network" >/dev/null 2>&1; then
    "${DOCKER[@]}" network create "$network" >/dev/null
  fi
}

usage() {
  printf '%s\n' \
    'Usage: ./manage.sh <command> [service]' \
    '' \
    'Commands:' \
    '  bootstrap   Create private runtime and versioned operations directories' \
    '  start       Start containers without build, seed, or migration' \
    '  health      Run read-only release health checks' \
    '  backup      Create and verify a release-bound backup' \
    '  restore     Verify and plan restore; use --apply only for an empty target' \
    '  rollback    Roll back through an explicit operations driver plan' \
    '  init        Create private runtime directories and merge safe templates' \
    '  plugins     Install owned and locked plugins into the 2.0 runtime' \
    '  plugin-access  Provision the Web plugin-scope AstrBot API key' \
    '  api-key-store-path  Validate and print the external API Key store root' \
    '  sync        Merge the icourse MCP template into runtime config' \
    '  seed        Install the Dududa persona and MCP config into AstrBot' \
    '  up          Build and start the complete AstrBot + NapCat + Web stack' \
    '  web-up      Build and start only the Dududa QQ workspace' \
    '  web-connect Add the workspace reverse WS to this stack and restart NapCat' \
    '  web-connect-llbot  Add the workspace reverse WS to LLBot host configs' \
    '  down        Stop and remove containers and private network' \
    '  restart     Restart all services, or one service' \
    '  logs        Follow logs for all services, or one service' \
    '  ps          Show service status' \
    '  pull        Pull locked base images' \
    '  upgrade     Rebuild and recreate services without deleting data' \
    '  config      Render and validate the Compose configuration'
}

cmd="${1:-}"
case "$cmd" in
  bootstrap)
    ops_cli bootstrap --data-root "$(data_root)"
    ;;
  init)
    if [[ ! -f .env ]]; then
      umask 077
      cp deploy/env/.env.example .env
    fi
    chmod 600 .env
    runtime_root="$(data_root)"
    ops_cli bootstrap --data-root "$runtime_root" >/dev/null
    ensure_web_secrets
    "$PYTHON" ops/cli/sync_runtime.py --data-root "$runtime_root"
    ;;
  plugins)
    plugin_root="$(astrbot_plugin_root)"
    mkdir -p "$plugin_root"
    "$PYTHON" ops/cli/install_plugins.py --plugins-root "$plugin_root"
    ;;
  plugin-access)
    setup_docker
    ensure_web_secrets
    plugin_key_file="$(web_data_root)/secrets/astrbot_plugin_api_key"
    if [[ -s "$plugin_key_file" && "${2:-}" != "--force" ]]; then
      printf '%s\n' 'AstrBot plugin access is already configured.'
      exit 0
    fi
    plugin_key_tmp="$(mktemp "$(web_data_root)/secrets/.astrbot_plugin_api_key.XXXXXX")"
    trap 'rm -f "$plugin_key_tmp"' EXIT
    "${COMPOSE[@]}" exec -T astrbot python \
      /opt/dududa/scripts/provision_astrbot_plugin_key.py >"$plugin_key_tmp"
    if [[ ! -s "$plugin_key_tmp" ]]; then
      printf '%s\n' 'AstrBot returned an empty plugin API key.' >&2
      exit 1
    fi
    chmod 600 "$plugin_key_tmp"
    cp "$plugin_key_tmp" "$plugin_key_file"
    rm -f "$plugin_key_tmp"
    chmod 600 "$plugin_key_file"
    trap - EXIT
    printf '%s\n' 'AstrBot plugin access configured.'
    ;;
  api-key-store-path)
    api_key_store_root
    ;;
  sync)
    "$PYTHON" ops/cli/sync_runtime.py --data-root "$(data_root)" --force-config
    ;;
  seed)
    setup_docker
    "${COMPOSE[@]}" exec -T astrbot python /opt/dududa/scripts/seed_astrbot.py \
      --database /AstrBot/data/data_v4.db \
      --astrbot-config /AstrBot/data/cmd_config.json \
      --persona /opt/dududa/config/personas/dududa.json \
      --wait-seconds 90
    ;;
  up)
    "$0" init
    "$0" plugins
    ensure_edge_network
    "${COMPOSE[@]}" up -d --build
    "$0" plugin-access
    "$0" seed
    "${COMPOSE[@]}" restart astrbot
    ;;
  start)
    ensure_web_secrets
    ensure_edge_network
    "${COMPOSE[@]}" up -d
    ;;
  health)
    shift
    ops_cli health --data-root "$(data_root)" "$@"
    ;;
  backup)
    shift
    ops_cli backup --data-root "$(data_root)" "$@"
    ;;
  restore)
    shift
    ops_cli restore --data-root "$(data_root)" "$@"
    ;;
  rollback)
    shift
    ops_cli rollback --data-root "$(data_root)" "$@"
    ;;
  web-up)
    ensure_web_secrets
    ensure_edge_network
    "${COMPOSE[@]}" up -d --build web
    ;;
  web-connect)
    "$0" init
    runtime_root="$(data_root)"
    "$PYTHON" ops/cli/configure_napcat_web.py \
      --config-dir "$runtime_root/napcat/config" \
      --token-file "$(web_data_root)/secrets/onebot_access_token" \
      --apply
    "${COMPOSE[@]}" restart napcat
    ;;
  web-connect-llbot)
    "$0" init
    "$PYTHON" ops/cli/configure_llbot_web.py \
      --config-dir "${LLBOT_DATA_DIR:-$HOME/LLBot/bin/llbot/data}" \
      --token-file "$(web_data_root)/secrets/onebot_access_token" \
      --endpoint "${DUDUDA_WEB_ONEBOT_WS_URL:-ws://127.0.0.1:5173/onebot/v11/ws}" \
      --apply
    ;;
  down)
    setup_docker
    "${COMPOSE[@]}" down
    ;;
  restart)
    shift
    setup_docker
    "${COMPOSE[@]}" restart "$@"
    ;;
  logs)
    shift
    setup_docker
    "${COMPOSE[@]}" logs -f --tail=200 "$@"
    ;;
  ps)
    setup_docker
    "${COMPOSE[@]}" ps
    ;;
  pull)
    setup_docker
    "${COMPOSE[@]}" pull --ignore-buildable
    ;;
  upgrade)
    shift
    if [[ "$#" -gt 0 ]]; then
      ops_cli upgrade --data-root "$(data_root)" "$@"
    else
      "$0" plugins
      "$0" sync
      ensure_web_secrets
      ensure_edge_network
      "${COMPOSE[@]}" pull --ignore-buildable
      "${COMPOSE[@]}" up -d --build
      "$0" plugin-access
      "$0" seed
    fi
    ;;
  config)
    setup_docker
    "${COMPOSE[@]}" config
    ;;
  *)
    usage
    exit 2
    ;;
esac

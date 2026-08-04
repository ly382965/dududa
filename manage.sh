#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env"
if [[ ! -f "$ENV_FILE" ]]; then
  ENV_FILE=".env.example"
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

ensure_web_secrets() {
  local root token_file
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
}

project_name() {
  local name
  name="${COMPOSE_PROJECT_NAME:-$(env_value COMPOSE_PROJECT_NAME "$ENV_FILE")}"
  printf '%s\n' "${name:-dududa}"
}

if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
else
  DOCKER=(sudo docker)
fi
COMPOSE=("${DOCKER[@]}" compose --env-file "$ENV_FILE" -f compose.yml -p "$(project_name)")

ensure_edge_network() {
  local network
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
    '  init        Create private runtime directories and merge safe templates' \
    '  plugins     Install locked third-party plugins into runtime data' \
    '  sync        Merge the icourse MCP template into runtime config' \
    '  seed        Install the Dududa persona and MCP config into AstrBot' \
    '  up          Build and start the complete AstrBot + NapCat + Web stack' \
    '  web-up      Build and start only the Dududa QQ workspace' \
    '  web-connect Add the workspace reverse WS to this stack and restart NapCat' \
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
  init)
    if [[ ! -f .env ]]; then
      umask 077
      cp .env.example .env
    fi
    chmod 600 .env
    runtime_root="$(data_root)"
    mkdir -p "$runtime_root/astrbot/plugins" "$runtime_root/napcat/config" "$runtime_root/napcat/ntqq"
    chmod 700 "$runtime_root" "$runtime_root/astrbot" "$runtime_root/napcat" 2>/dev/null || true
    ensure_web_secrets
    python3 scripts/sync_runtime.py --data-root "$runtime_root"
    ;;
  plugins)
    runtime_root="$(data_root)"
    mkdir -p "$runtime_root/astrbot/plugins"
    python3 scripts/install_plugins.py --data-root "$runtime_root"
    ;;
  sync)
    python3 scripts/sync_runtime.py --data-root "$(data_root)" --force-config
    ;;
  seed)
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
    "$0" seed
    "${COMPOSE[@]}" restart astrbot
    ;;
  web-up)
    ensure_web_secrets
    ensure_edge_network
    "${COMPOSE[@]}" up -d --build web
    ;;
  web-connect)
    "$0" init
    runtime_root="$(data_root)"
    python3 scripts/configure_napcat_web.py \
      --config-dir "$runtime_root/napcat/config" \
      --token-file "$(web_data_root)/secrets/onebot_access_token" \
      --apply
    "${COMPOSE[@]}" restart napcat
    ;;
  down)
    "${COMPOSE[@]}" down
    ;;
  restart)
    shift
    "${COMPOSE[@]}" restart "$@"
    ;;
  logs)
    shift
    "${COMPOSE[@]}" logs -f --tail=200 "$@"
    ;;
  ps)
    "${COMPOSE[@]}" ps
    ;;
  pull)
    "${COMPOSE[@]}" pull --ignore-buildable
    ;;
  upgrade)
    "$0" plugins
    "$0" sync
    ensure_edge_network
    "${COMPOSE[@]}" pull --ignore-buildable
    "${COMPOSE[@]}" up -d --build
    "$0" seed
    ;;
  config)
    "${COMPOSE[@]}" config
    ;;
  *)
    usage
    exit 2
    ;;
esac

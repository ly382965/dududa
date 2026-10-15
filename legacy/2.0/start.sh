#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
action="${1:-up}"
case "$action" in
  up|down|status|logs|build|credentials) ;;
  *) printf 'Usage: bash start.sh [up|down|status|logs|build|credentials]\n'; exit 2 ;;
esac
if ! command -v docker >/dev/null 2>&1; then
  printf 'Please install Docker: https://docs.docker.com/get-started/get-docker/\n' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  printf 'Docker is not ready. Start Docker Desktop / Docker Engine, and check your Docker permissions.\n' >&2
  exit 1
fi
docker compose version >/dev/null
env_file="${DUDUDA_QUICKSTART_ENV:-quickstart.env}"
if [[ ! -f "$env_file" ]]; then
  umask 077
  cp deploy/quickstart/quickstart.env.example "$env_file"
fi
compose=(docker compose --project-directory "$PWD" --env-file "$env_file" -f deploy/quickstart/compose.yml)
case "$action" in
  down) "${compose[@]}" down; exit ;;
  status) "${compose[@]}" ps; exit ;;
  logs) "${compose[@]}" logs --tail=100 -f "${@:2}"; exit ;;
esac
"${compose[@]}" config --quiet
images=(dududa/astrbot:submission-2b52593 dududa/web:submission-2b52593 dududa/napcat:submission-4.18.19)
missing=0
for ref in "${images[@]}"; do
  docker image inspect "$ref" >/dev/null 2>&1 || missing=1
done
if [[ "$missing" == 1 && -f images/dududa-images-amd64.tar.gz ]]; then
  printf 'Loading bundled Docker images (first launch only)...\n'
  docker load --input images/dududa-images-amd64.tar.gz
  missing=0
  for ref in "${images[@]}"; do
    docker image inspect "$ref" >/dev/null 2>&1 || missing=1
  done
fi
if [[ "$action" == build || "$missing" == 1 ]]; then
  printf 'Building Docker images...\n'
  "${compose[@]}" build init web napcat
fi
if [[ "$action" == credentials ]]; then
  "${compose[@]}" run --rm -T --no-deps init credentials
  exit
fi
printf 'Preparing settings, plugins and private data volumes...\n'
"${compose[@]}" run --rm -T --no-deps init prepare
"${compose[@]}" up -d --wait --wait-timeout 240 astrbot mcp-console
"${compose[@]}" run --rm -T --no-deps init finish
"${compose[@]}" restart astrbot
"${compose[@]}" up -d --wait --wait-timeout 180 astrbot web napcat
umask 077
"${compose[@]}" run --rm -T --no-deps init credentials > initial-login.txt
chmod 600 initial-login.txt
"${compose[@]}" ps
printf '\nReady. Open initial-login.txt for URLs and initial login credentials.\n'
printf 'Model and QQ setup: START_HERE.md\nStop (keeps data): bash start.sh down\n'

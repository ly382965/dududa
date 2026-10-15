#!/usr/bin/env bash
set -euo pipefail

# Run explicitly in the bot container; no system-package installs during polling.
apt-get update -qq
apt-get install -y --no-install-recommends catdoc libreoffice-impress-nogui

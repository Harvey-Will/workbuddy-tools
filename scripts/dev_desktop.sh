#!/usr/bin/env bash
# Start desktop dev on macOS: sidecar prerequisites + tauri dev.
# Counterpart of scripts/dev_desktop.ps1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if [ ! -x "$ROOT/.venv/bin/python" ]; then
    python3 -m venv .venv
  fi
  PY="$ROOT/.venv/bin/python"
fi
"$PY" -m pip install -q -r requirements.txt

# UI deps
if [ ! -d "ui/node_modules" ]; then
  (cd ui && npm install)
fi

# Tauri CLI
if [ ! -d "node_modules/@tauri-apps/cli" ]; then
  npm install --no-save @tauri-apps/cli@2
fi

# Dev builds embed the sidecar from src-tauri/binaries; make one if absent.
# shellcheck source=scripts/_macos_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_macos_common.sh"
TRIPLE="$(host_triple 2>/dev/null || true)"
if [ -z "$TRIPLE" ] || [ ! -f "src-tauri/binaries/sidecar-$TRIPLE" ]; then
  bash scripts/build_sidecar.sh
fi

exec npx tauri dev
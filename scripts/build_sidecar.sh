#!/usr/bin/env bash
# Build the Python API sidecar for the macOS desktop shell.
# Counterpart of scripts/build_sidecar.ps1 - produces src-tauri/binaries/sidecar-<triple>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/_macos_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_macos_common.sh"

TRIPLE="$(host_triple)" || {
  echo "ERROR: rustc not found. Install Rust (https://rustup.rs) or add it to PATH." >&2
  exit 1
}
if [ -z "$TRIPLE" ]; then
  echo "ERROR: could not determine host triple from rustc -vV" >&2
  exit 1
fi
echo "target triple: $TRIPLE"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
  else
    PY="$(command -v python3)"
  fi
fi
echo "python: $PY"
"$PY" -m pip install -q -r requirements.txt pyinstaller

# PyInstaller caches under ~/Library/Application Support by default, which can be
# read-only (sandboxed/CI builds). PYINSTALLER_CONFIG_DIR is the documented knob.
export PYINSTALLER_CONFIG_DIR="$ROOT/build/pyinstaller-config"
mkdir -p "$PYINSTALLER_CONFIG_DIR"
# Also point HOME at a writable dir when the default cache is not writable.
if ! mkdir -p "$HOME/Library/Application Support/pyinstaller" 2>/dev/null; then
  export HOME="$ROOT/build/pyinstaller-home"
  mkdir -p "$HOME"
fi
BIN_DIR="$ROOT/src-tauri/binaries"
mkdir -p "$BIN_DIR"

rm -rf "$ROOT/build/sidecar-mac" "$ROOT/dist/sidecar-mac"

"$PY" -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name sidecar \
  --paths "$ROOT" \
  --hidden-import backend.app \
  --hidden-import core.accounts \
  --hidden-import core.editions \
  --hidden-import core.migrate \
  --hidden-import core.tokens \
  --hidden-import core.models \
  --hidden-import core.sessions \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.loops.asyncio \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  --collect-submodules backend \
  --collect-submodules core \
  --distpath "$ROOT/dist/sidecar-mac" \
  --workpath "$ROOT/build/sidecar-mac" \
  "$ROOT/scripts/sidecar_entry.py"

BUILT="$ROOT/dist/sidecar-mac/sidecar"
if [ ! -f "$BUILT" ]; then
  echo "ERROR: sidecar build missing: $BUILT" >&2
  exit 1
fi

# Tauri externalBin naming: <name>-<target-triple> (no extension on macOS).
TARGET="$BIN_DIR/sidecar-$TRIPLE"
cp "$BUILT" "$TARGET"
chmod +x "$TARGET"
echo "sidecar -> $TARGET"
ls -lh "$TARGET" | awk '{print $5, $9}'

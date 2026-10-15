#!/usr/bin/env bash
# Shared helpers for the macOS build scripts.
# Sourced, not executed: defines resolve_rustc / host_triple.
#
# rustup installs its shims under ~/.cargo/bin, which is often absent from PATH
# in non-interactive shells (CI, GUI-launched builds), so probe the usual spots.

resolve_rustc() {
  if [ -n "${RUSTC:-}" ] && [ -x "$RUSTC" ]; then
    printf "%s" "$RUSTC"; return 0
  fi
  local c
  c="$(command -v rustc 2>/dev/null || true)"
  [ -n "$c" ] && { printf "%s" "$c"; return 0; }
  for c in "$HOME/.cargo/bin/rustc" "$HOME/.rustup/toolchains"/*/bin/rustc; do
    [ -x "$c" ] && { printf "%s" "$c"; return 0; }
  done
  return 1
}

host_triple() {
  local rustc; rustc="$(resolve_rustc)" || return 1
  "$rustc" -vV | sed -n 's/^host: //p'
}

#!/usr/bin/env node
// Platform dispatcher: build the Python sidecar on the current platform
const { spawnSync } = require("node:child_process");

const isWin = process.platform === "win32";
const cmd = isWin ? "powershell" : "bash";
const args = isWin
  ? ["-ExecutionPolicy", "Bypass", "-File", "scripts/build_sidecar.ps1"]
  : ["scripts/build_sidecar.sh"];

const r = spawnSync(cmd, args, { stdio: "inherit" });
process.exit(r.status === null ? 1 : r.status);

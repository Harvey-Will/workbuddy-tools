#!/usr/bin/env node
// Platform dispatcher: start the desktop dev app on the current platform
const { spawnSync } = require("node:child_process");

const isWin = process.platform === "win32";
const cmd = isWin ? "powershell" : "bash";
const args = isWin
  ? ["-ExecutionPolicy", "Bypass", "-File", "scripts/dev_desktop.ps1"]
  : ["scripts/dev_desktop.sh"];

const r = spawnSync(cmd, args, { stdio: "inherit" });
process.exit(r.status === null ? 1 : r.status);

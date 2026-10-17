#!/usr/bin/env node
// Platform dispatcher: package the portable build on the current platform
const { spawnSync } = require("node:child_process");

const isWin = process.platform === "win32";
const cmd = isWin ? "powershell" : "bash";
const args = isWin
  ? ["-ExecutionPolicy", "Bypass", "-File", "scripts/build_portable.ps1"]
  : ["scripts/build_portable.sh"];

const r = spawnSync(cmd, args, { stdio: "inherit" });
process.exit(r.status === null ? 1 : r.status);

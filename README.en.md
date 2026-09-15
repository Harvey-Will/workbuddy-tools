# WorkBuddy Tools

English · [简体中文](README.md)

[![Release](https://img.shields.io/github/v/release/Harvey-Will/workbuddy-tools?style=flat&label=Release)](https://github.com/Harvey-Will/workbuddy-tools/releases)
[![Downloads](https://img.shields.io/github/downloads/Harvey-Will/workbuddy-tools/total?style=flat)](https://github.com/Harvey-Will/workbuddy-tools/releases)
[![Stars](https://img.shields.io/github/stars/Harvey-Will/workbuddy-tools?style=flat)](https://github.com/Harvey-Will/workbuddy-tools/stargazers)
[![Issues](https://img.shields.io/github/issues/Harvey-Will/workbuddy-tools?style=flat)](https://github.com/Harvey-Will/workbuddy-tools/issues)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat)](LICENSE)

## Seamlessly continue your WorkBuddy work across accounts

WorkBuddy Tools is a **local-first** account and data manager for **WorkBuddy / WorkBuddyAI**.

If you use multiple accounts, or switch between the domestic and international editions, WorkBuddy Tools helps you manage accounts, switch identity, migrate data, and review Token usage in one desktop app — so work continues smoothly from one account to the next.

Account, session, memory, and configuration data are handled on your machine. There is no project-operated cloud, and your WorkBuddy data is not uploaded to third-party servers.

**Features**: multi-account management · quick switch · data migration · sessions & memory · Skills / MCP · Token usage · local-first

**Platform**: Windows

---

## Features

### Account management

Automatically detect local WorkBuddy and WorkBuddyAI data and present editions and accounts in one place.

- View name, sessions, Memory, MCP, and last activity
- See which account is currently signed in
- Switch to another local account in one click
- Add personal labels for multi-account clarity

No more hunting for config files or editing local data by hand.

### Data migration

Move only the data you need between accounts or editions.

Supported data:

- Chat sessions
- Session content and attachments
- User memory
- Historical tasks
- Skills
- MCP configuration
- Plugins and connector data
- Token usage records

Preview first, then choose what to migrate. Existing target data is preserved where possible, and a local backup is created before migration.

Same-edition session-related migration is not available in this version. Memory, MCP, Skills, and other supported types can still be migrated independently.

### Token usage

Summarize Token usage from local session data.

- Ranges: today / 24h / 7d / 30d / 90d
- Input / Output tokens, Cache Read
- Per-model totals and share

Understand model usage without opening every session.

### Local-first

Core operations stay on your machine.

- No WorkBuddy Tools account required
- No project cloud service
- Scanning, migration, and Token stats run locally
- Automatic backup before migration
- Migration and switch are blocked while the client is running to avoid conflicts

Your data remains under your control.

---

## Download

Use the Windows portable build.

Download the latest from [Releases](https://github.com/Harvey-Will/workbuddy-tools/releases):

```text
WorkBuddyTools-portable-win64-*.zip
```

Extract and run `workbuddy-tools.exe`. No Python, Node.js, or Rust install required.

---

## Quick start

1. Launch WorkBuddy Tools
2. Choose WorkBuddy or WorkBuddyAI
3. Review local accounts
4. Switch account, or open Migration and pick source / target
5. Preview and select data to migrate
6. Check Token usage

Fully quit **WorkBuddy / WorkBuddyAI** before migration or account switch.

---

## Security & privacy

WorkBuddy Tools is local-first.

Default WorkBuddy data locations:

- `~/.workbuddy`
- `~/.workbuddy-ai`

The app reads or updates these local files only when needed, and stores its own backups under the corresponding data directory. There is no cloud store for your accounts, sessions, or memory.

Keep your own regular backups of important work data.

---

## FAQ

**Will my account or sessions be uploaded?**

No. Scanning, migration, and Token stats are based on local data.

**Can I migrate data between two WorkBuddy accounts?**

Yes. Memory, Skills, MCP, and other supported types can be migrated selectively. Same-edition session-related migration is not supported in this version.

**Why does WorkBuddy still show the old account after switching?**

Fully quit WorkBuddy, including tray/background processes, then restart the client.

**Is Token usage the official bill?**

No. It summarizes local session `usage` fields and may differ from official billing.

---

## Development

### Requirements

- Python 3.10+
- Node.js 18+
- Rust / Cargo (desktop build)

### Local development

```bash
npm install
cd ui && npm install && cd ..
npm run dev:desktop
```

### Build

```powershell
powershell -File scripts/build_sidecar.ps1
npm run build:portable
```

### Tests

```powershell
.venv\Scripts\python -m unittest discover -s tests
```

### Stack

Tauri 2 · TypeScript / Vite · Python · FastAPI · SQLite

---

## Contributing

Issues, feature requests, and pull requests are welcome.

If WorkBuddy Tools helps you, a ⭐ Star is appreciated.

## License

MIT License

## Disclaimer

WorkBuddy Tools is an independent community tool and is not officially affiliated with WorkBuddy or Tencent.

The app may read and modify local WorkBuddy data when you request those operations. Keep additional backups of important data.

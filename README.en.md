# WorkBuddy Tools

[简体中文](README.md) · English

Local **WorkBuddy account & data manager**: inspect accounts on domestic WorkBuddy and international WorkBuddyAI, switch identity, selectively migrate sessions/memory/skills/MCP, and visualize Token usage — **all on-device**.

See the [Chinese README](README.md) for the full guide (features, security, install, FAQ, build).

## Quick start (portable)

1. Download `WorkBuddyTools-portable-win64.zip` from Releases  
2. Unzip and run `workbuddy-tools.exe`  
3. No Python install required  

## Dev

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # or Windows Scripts\python
python scripts/dev.py
# http://127.0.0.1:18765
```

## License

MIT

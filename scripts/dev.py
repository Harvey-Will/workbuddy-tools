#!/usr/bin/env python3
"""Start WorkBuddy Tools local server."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main() -> None:
    os.environ.setdefault("WBT_HOST", "127.0.0.1")
    os.environ.setdefault("WBT_PORT", "18765")
    host = os.environ["WBT_HOST"]
    port = int(os.environ["WBT_PORT"])
    print(f"WorkBuddy Tools → http://{host}:{port}")
    print("数据只在本机处理。迁移前请退出 WorkBuddy / WorkBuddyAI。")
    import uvicorn
    from backend.app import app

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

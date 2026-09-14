#!/usr/bin/env python3
"""Sidecar entry: FastAPI on loopback only for the desktop shell."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepare_path() -> None:
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def main() -> None:
    _prepare_path()
    # Desktop must stay on loopback; ignore WBT_HOST to avoid LAN exposure.
    host = "127.0.0.1"
    port = int(os.environ.get("WBT_PORT") or "18765")
    os.environ["WBT_HOST"] = host
    os.environ["WBT_PORT"] = str(port)
    import uvicorn

    from backend.app import app

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()

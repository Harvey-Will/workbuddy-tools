#!/usr/bin/env python3
"""Sidecar entry: start FastAPI on 127.0.0.1:18765 for the desktop shell."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepare_path() -> None:
    if getattr(sys, "frozen", False):
        # PyInstaller onefile: bundled modules are importable; keep cwd friendly
        return
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def main() -> None:
    _prepare_path()
    os.environ.setdefault("WBT_HOST", "127.0.0.1")
    os.environ.setdefault("WBT_PORT", "18765")
    import uvicorn

    from backend.app import app

    uvicorn.run(
        app,
        host=os.environ["WBT_HOST"],
        port=int(os.environ["WBT_PORT"]),
        log_level="warning",
    )


if __name__ == "__main__":
    main()

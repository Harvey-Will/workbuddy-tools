#!/usr/bin/env python3
"""Local HTTP API for WorkBuddy Tools (loopback)."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

if not getattr(sys, "frozen", False):
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
else:
    ROOT = Path(getattr(sys, "_MEIPASS", Path.cwd()))

from core import accounts as accounts_mod
from core import migrate as migrate_mod
from core import tokens as tokens_mod
from core.editions import (
    client_looks_running,
    detect_editions,
    find_client_executables,
    list_edition_info,
    make_paths,
    normalize_edition,
)
from core.safety import (
    AccountNotFound,
    ClientRunningError,
    InvalidUID,
    MigrationBlocked,
    SafetyError,
    SchemaIncompatible,
    UnsafePath,
    WriteConflict,
)

APP_VERSION = "0.1.1"
app = FastAPI(title="WorkBuddy Tools", version=APP_VERSION)

# Optional loopback auth token (set by desktop shell). Empty = open (dev/CLI).
API_TOKEN = os.environ.get("WBT_TOKEN", "").strip()
_migrate_lock = threading.Lock()


def _check_token(x_wbt_token: Optional[str]) -> None:
    if not API_TOKEN:
        return
    if not x_wbt_token or not secrets.compare_digest(x_wbt_token, API_TOKEN):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "invalid or missing API token"},
        )


def _norm(edition: str) -> str:
    try:
        return normalize_edition(edition)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "bad_edition", "message": str(e)})


class SwitchBody(BaseModel):
    edition: str
    target_uid: str


class AddProfileBody(BaseModel):
    edition: str
    uid: str
    label: str = ""


class RenameAccountBody(BaseModel):
    edition: str
    uid: str
    label: str = ""


class OpenClientBody(BaseModel):
    edition: str


class MigrateRunBody(BaseModel):
    from_edition: str
    to_edition: str
    source_uid: str
    target_uid: Optional[str] = None
    items: Dict[str, bool] = Field(default_factory=dict)
    mode: str = "copy"


@app.middleware("http")
async def require_token(request, call_next):
    if request.url.path.startswith("/api/"):
        token = request.headers.get("x-wbt-token")
        try:
            _check_token(token)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content=e.detail)
    return await call_next(request)


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "version": APP_VERSION, "editions": detect_editions(), "auth": bool(API_TOKEN)}


@app.get("/api/editions")
def api_editions() -> Dict[str, Any]:
    items = list_edition_info()
    enriched = []
    for e in items:
        d = e.to_dict()
        d["client_running"] = client_looks_running(e.key) if e.exists else False
        # Do not leak full local binary paths in list API
        d["client_binaries"] = [Path(p).name for p in (find_client_executables(e.key) if e.exists else [])]
        enriched.append(d)
    return {"editions": enriched}


@app.get("/api/accounts")
def api_accounts(edition: str = Query(...)) -> Dict[str, Any]:
    ed = _norm(edition)
    paths = make_paths(ed)
    if not paths.root.exists():
        raise HTTPException(status_code=404, detail={"code": "edition_missing", "message": "data directory not found"})
    accounts = [a.to_dict() for a in accounts_mod.list_accounts(ed)]
    profiles = accounts_mod.load_profiles(ed)
    snap = accounts_mod.read_account_snapshot(paths)
    return {
        "edition": ed,
        "current_uid": snap.get("uid") or accounts_mod.get_current_uid(paths),
        "accounts": accounts,
        "profiles": profiles,
        "client_running": client_looks_running(ed),
    }


@app.get("/api/accounts/current")
def api_current(edition: str = Query(...)) -> Dict[str, Any]:
    ed = _norm(edition)
    paths = make_paths(ed)
    snap = accounts_mod.read_account_snapshot(paths)
    return {
        "edition": ed,
        "uid": snap.get("uid") or accounts_mod.get_current_uid(paths),
        "nickname": snap.get("nickname", ""),
        "client_running": client_looks_running(ed),
    }


def _map_safety(e: SafetyError) -> HTTPException:
    status = 400
    if isinstance(e, ClientRunningError):
        status = 409
    elif isinstance(e, AccountNotFound):
        status = 404
    elif isinstance(e, WriteConflict):
        status = 409
    elif isinstance(e, SchemaIncompatible):
        status = 409
    elif isinstance(e, MigrationBlocked):
        status = 409
    elif isinstance(e, UnsafePath):
        status = 400
    elif isinstance(e, InvalidUID):
        status = 400
    return HTTPException(status_code=status, detail={"code": e.code, "message": e.message})


@app.post("/api/accounts/switch")
def api_switch(body: SwitchBody) -> Dict[str, Any]:
    ed = _norm(body.edition)
    try:
        return accounts_mod.switch_account(ed, body.target_uid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "edition_missing", "message": "edition not found"})
    except SafetyError as e:
        raise _map_safety(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "uid_required", "message": str(e)})


@app.post("/api/accounts/add")
def api_add_profile(body: AddProfileBody) -> Dict[str, Any]:
    ed = _norm(body.edition)
    try:
        item = accounts_mod.add_profile(ed, body.uid, body.label[:80])
    except SafetyError as e:
        raise _map_safety(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "uid_required", "message": str(e)})
    return {"ok": True, "profile": item, "note": "已保存，请在客户端登录后刷新"}


@app.post("/api/accounts/rename")
def api_rename(body: RenameAccountBody) -> Dict[str, Any]:
    ed = _norm(body.edition)
    try:
        return accounts_mod.set_account_label(ed, body.uid, body.label[:80])
    except SafetyError as e:
        raise _map_safety(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(e)})


@app.post("/api/accounts/open-client")
def api_open_client(body: OpenClientBody) -> Dict[str, Any]:
    ed = _norm(body.edition)
    bins = find_client_executables(ed)
    if not bins:
        raise HTTPException(
            status_code=404,
            detail={"code": "client_not_found", "message": "未找到客户端，请手动打开 WorkBuddy / WorkBuddyAI"},
        )
    exe = bins[0]
    try:
        subprocess.Popen([exe], cwd=str(Path(exe).parent), start_new_session=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "launch_failed", "message": str(e)})
    return {"ok": True, "exe": Path(exe).name, "candidates": [Path(p).name for p in bins]}


@app.get("/api/workspaces")
def api_workspaces(edition: str = Query(...)) -> Dict[str, Any]:
    ed = _norm(edition)
    # Return cwd as-is (needed by user); paths stay local to this machine.
    return {"edition": ed, "workspaces": migrate_mod.list_workspaces(ed)}


@app.get("/api/migrate/plan")
def api_migrate_plan(
    from_edition: str = Query(...),
    to_edition: str = Query(...),
    source_uid: str = Query(...),
    target_uid: Optional[str] = Query(None),
) -> Dict[str, Any]:
    fe, te = _norm(from_edition), _norm(to_edition)
    try:
        return migrate_mod.plan_migrate(fe, te, source_uid, target_uid)
    except SafetyError as e:
        raise _map_safety(e)


@app.post("/api/migrate/run")
def api_migrate_run(body: MigrateRunBody) -> Dict[str, Any]:
    fe, te = _norm(body.from_edition), _norm(body.to_edition)
    if body.mode not in ("copy",):
        raise HTTPException(status_code=400, detail={"code": "bad_mode", "message": "v0.1 仅支持 copy"})
    payload = {
        "from_edition": fe,
        "to_edition": te,
        "source_uid": body.source_uid,
        "target_uid": body.target_uid,
        "items": body.items,
    }
    if not _migrate_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={"code": "busy", "message": "已有迁移在进行中，请稍后再试"},
        )
    try:
        return migrate_mod.run_migrate(payload)
    except SafetyError as e:
        raise _map_safety(e)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "migrate_failed", "message": str(e)})
    finally:
        _migrate_lock.release()


@app.get("/api/tokens/summary")
def api_tokens(
    edition: str = Query(...),
    range: str = Query("7d", alias="range"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> Dict[str, Any]:
    ed = _norm(edition)
    if range not in ("today", "24h", "7d", "30d", "90d", "custom"):
        raise HTTPException(status_code=400, detail={"code": "bad_range", "message": "invalid range"})
    return tokens_mod.summarize_tokens(ed, range, date_from, date_to)


@app.get("/")
def index():
    # Prefer packaged ui/dist (desktop); fall back to legacy frontend/
    for cand in (ROOT / "ui" / "dist" / "index.html", ROOT / "frontend" / "index.html"):
        if cand.is_file():
            return FileResponse(cand)
    raise HTTPException(status_code=404, detail={"code": "no_ui", "message": "UI not packaged"})


def main() -> None:
    import uvicorn

    host = "127.0.0.1"
    port = int(os.environ.get("WBT_PORT") or "18765")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

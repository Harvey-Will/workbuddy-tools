#!/usr/bin/env python3
"""Local HTTP API for WorkBuddy Tools (loopback)."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime
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
from core import update as update_mod
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
    BackupCorrupted,
    BackupNotFound,
    ClientRunningError,
    InvalidUID,
    MigrationBlocked,
    SafetyError,
    SchemaIncompatible,
    UnsafePath,
    WriteConflict,
)

APP_VERSION = "0.1.4"
__version__ = APP_VERSION
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


class RestoreBody(BaseModel):
    edition: str
    backup_id: str


class CreateBackupBody(BaseModel):
    edition: str
    target_uid: Optional[str] = None
    label: str = "manual"


class OpenUrlBody(BaseModel):
    url: str


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
    elif isinstance(e, BackupNotFound):
        status = 404
    elif isinstance(e, BackupCorrupted):
        status = 409
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
    if not _migrate_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={"code": "busy", "message": "已有任务正在进行中，请稍后再试"},
        )
    try:
        ed = _norm(body.edition)
        return accounts_mod.switch_account(ed, body.target_uid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "edition_missing", "message": "edition not found"})
    except SafetyError as e:
        raise _map_safety(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "uid_required", "message": str(e)})
    finally:
        _migrate_lock.release()


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


_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _run_job_worker(job_id: str, payload: Dict[str, Any]) -> None:
    def progress_cb(stage: str, percent: int, msg: str) -> None:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["stage"] = stage
                _jobs[job_id]["progress"] = percent
                _jobs[job_id]["message"] = msg
                _jobs[job_id]["updated_at"] = datetime.now().isoformat()

    try:
        with _jobs_lock:
            _jobs[job_id]["status"] = "running"
        result = migrate_mod.run_migrate(payload, progress_callback=progress_cb)
        with _jobs_lock:
            _jobs[job_id]["status"] = "completed" if result.get("ok") else "failed"
            _jobs[job_id]["progress"] = 100
            _jobs[job_id]["result"] = result
            _jobs[job_id]["updated_at"] = datetime.now().isoformat()
    except SafetyError as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = {"code": e.code, "message": e.message}
            _jobs[job_id]["updated_at"] = datetime.now().isoformat()
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = {"code": "migrate_failed", "message": str(e)}
            _jobs[job_id]["updated_at"] = datetime.now().isoformat()
    finally:
        _migrate_lock.release()


@app.post("/api/migrate/jobs")
def api_migrate_create_job(body: MigrateRunBody) -> Dict[str, Any]:
    if not _migrate_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={"code": "busy", "message": "已有任务正在进行中，请稍后再试"},
        )
    fe, te = _norm(body.from_edition), _norm(body.to_edition)
    if body.mode not in ("copy",):
        _migrate_lock.release()
        raise HTTPException(status_code=400, detail={"code": "bad_mode", "message": "v0.1 仅支持 copy"})
    payload = {
        "from_edition": fe,
        "to_edition": te,
        "source_uid": body.source_uid,
        "target_uid": body.target_uid,
        "items": body.items,
    }
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    rand_id = secrets.token_hex(4)
    job_id = f"job_{stamp}_{rand_id}"
    job_info = {
        "job_id": job_id,
        "status": "pending",
        "stage": "queued",
        "progress": 0,
        "message": "已排队，等待启动...",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "payload": payload,
        "result": None,
        "error": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job_info
    try:
        thread = threading.Thread(target=_run_job_worker, args=(job_id, payload), daemon=True)
        thread.start()
    except Exception:
        _migrate_lock.release()
        raise
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/migrate/jobs/{job_id}")
def api_migrate_get_job(job_id: str) -> Dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "作业不存在"})
    return job


@app.get("/api/migrate/jobs")
def api_migrate_list_jobs() -> Dict[str, Any]:
    with _jobs_lock:
        items = list(_jobs.values())
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"jobs": items[:20]}


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


@app.get("/api/backups")
def api_backups(edition: str = Query(...)) -> Dict[str, Any]:
    ed = _norm(edition)
    paths = make_paths(ed)
    return {"edition": ed, "backups": migrate_mod.list_backups(paths)}


@app.post("/api/backups/create")
def api_backups_create(body: CreateBackupBody) -> Dict[str, Any]:
    if not _migrate_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={"code": "busy", "message": "已有任务正在进行中，请稍后再试"},
        )
    try:
        ed = _norm(body.edition)
        paths = make_paths(ed)
        target_uid = (body.target_uid or "").strip()
        if not target_uid:
            snap = accounts_mod.read_account_snapshot(paths)
            target_uid = snap.get("uid") or accounts_mod.get_current_uid(paths) or "default"
        label = (body.label or "manual").strip()
        bk_path_str = migrate_mod.create_backup(paths, target_uid=target_uid, label=label)
        bk_path = Path(bk_path_str)
        return {
            "ok": True,
            "backup_id": bk_path.name,
            "path": bk_path_str,
            "edition": ed,
        }
    except SafetyError as e:
        raise _map_safety(e)
    finally:
        _migrate_lock.release()


@app.post("/api/backups/restore")
def api_backups_restore(body: RestoreBody) -> Dict[str, Any]:
    if not _migrate_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={"code": "busy", "message": "已有任务正在进行中，请稍后再试"},
        )
    try:
        ed = _norm(body.edition)
        paths = make_paths(ed)
        return migrate_mod.restore_backup(paths, body.backup_id)
    except SafetyError as e:
        raise _map_safety(e)
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


@app.get("/api/system/version")
def api_system_version() -> Dict[str, Any]:
    return {
        "version": APP_VERSION,
        "repo_url": "https://github.com/Harvey-Will/workbuddy-tools",
    }


@app.get("/api/system/check-update")
def api_check_update() -> Dict[str, Any]:
    return update_mod.check_github_update(APP_VERSION)


@app.post("/api/system/open-url")
def api_open_url(body: OpenUrlBody) -> Dict[str, Any]:
    url = body.url.strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_url", "message": "Only HTTP/HTTPS URLs allowed"},
        )
    import webbrowser

    webbrowser.open(url)
    return {"ok": True}


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

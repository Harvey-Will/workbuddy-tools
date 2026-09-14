from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
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

app = FastAPI(title="WorkBuddy Tools", version="1.0.0")

FRONTEND = ROOT / "frontend"


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


def _norm(edition: str) -> str:
    try:
        return normalize_edition(edition)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "bad_edition", "message": str(e)})


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "editions": detect_editions()}


@app.get("/api/editions")
def api_editions() -> Dict[str, Any]:
    items = list_edition_info()
    enriched = []
    for e in items:
        d = e.to_dict()
        d["client_running"] = client_looks_running(e.key) if e.exists else False
        d["client_binaries"] = find_client_executables(e.key) if e.exists else []
        enriched.append(d)
    return {"editions": enriched}


@app.get("/api/accounts")
def api_accounts(edition: str = Query(...)) -> Dict[str, Any]:
    ed = _norm(edition)
    root = make_paths(ed).root
    if not root.exists():
        raise HTTPException(status_code=404, detail={"code": "edition_missing", "message": str(root)})
    accounts = [a.to_dict() for a in accounts_mod.list_accounts(ed)]
    profiles = accounts_mod.load_profiles(ed)
    snap = accounts_mod.read_account_snapshot(make_paths(ed))
    return {
        "edition": ed,
        "current_uid": snap.get("uid") or accounts_mod.get_current_uid(make_paths(ed)),
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


@app.post("/api/accounts/switch")
def api_switch(body: SwitchBody) -> Dict[str, Any]:
    ed = _norm(body.edition)
    if not body.target_uid:
        raise HTTPException(status_code=400, detail={"code": "uid_required", "message": "target_uid required"})
    try:
        return accounts_mod.switch_account(ed, body.target_uid)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail={"code": "edition_missing", "message": str(e)})


@app.post("/api/accounts/add")
def api_add_profile(body: AddProfileBody) -> Dict[str, Any]:
    ed = _norm(body.edition)
    try:
        item = accounts_mod.add_profile(ed, body.uid, body.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "uid_required", "message": str(e)})
    return {"ok": True, "profile": item, "note": "已保存，请在客户端登录后刷新"}


@app.post("/api/accounts/rename")
def api_rename(body: RenameAccountBody) -> Dict[str, Any]:
    ed = _norm(body.edition)
    try:
        return accounts_mod.set_account_label(ed, body.uid, body.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(e)})


@app.post("/api/accounts/open-client")
def api_open_client(body: OpenClientBody) -> Dict[str, Any]:
    ed = _norm(body.edition)
    bins = find_client_executables(ed)
    if not bins:
        raise HTTPException(
            status_code=404,
            detail={"code": "client_not_found", "message": "未找到客户端可执行文件，请手动打开 WorkBuddy / WorkBuddyAI"},
        )
    exe = bins[0]
    try:
        subprocess.Popen([exe], cwd=str(Path(exe).parent), start_new_session=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "launch_failed", "message": str(e)})
    return {"ok": True, "exe": exe, "candidates": bins}


@app.get("/api/workspaces")
def api_workspaces(edition: str = Query(...)) -> Dict[str, Any]:
    ed = _norm(edition)
    return {"edition": ed, "workspaces": migrate_mod.list_workspaces(ed)}


@app.get("/api/migrate/plan")
def api_migrate_plan(
    from_edition: str = Query(...),
    to_edition: str = Query(...),
    source_uid: str = Query(...),
    target_uid: Optional[str] = Query(None),
) -> Dict[str, Any]:
    fe, te = _norm(from_edition), _norm(to_edition)
    return migrate_mod.plan_migrate(fe, te, source_uid, target_uid)


@app.post("/api/migrate/run")
def api_migrate_run(body: MigrateRunBody) -> Dict[str, Any]:
    fe, te = _norm(body.from_edition), _norm(body.to_edition)
    if body.mode not in ("copy",):
        raise HTTPException(status_code=400, detail={"code": "bad_mode", "message": "v1 仅支持 copy"})
    payload = {
        "from_edition": fe,
        "to_edition": te,
        "source_uid": body.source_uid,
        "target_uid": body.target_uid,
        "items": body.items,
    }
    try:
        return migrate_mod.run_migrate(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "migrate_failed", "message": str(e)})


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
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


def main() -> None:
    import uvicorn

    host = os.environ.get("WBT_HOST", "127.0.0.1")
    port = int(os.environ.get("WBT_PORT", "18765"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

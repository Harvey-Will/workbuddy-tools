from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .editions import AppPaths, client_looks_running, make_paths, normalize_edition
from .models import AccountInfo
from .safety import (
    ClientRunningError,
    InvalidUID,
    WriteConflict,
    atomic_write_json,
    atomic_write_text,
    ensure_within,
    validate_uid,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


def read_account_snapshot(paths: AppPaths) -> Dict[str, str]:
    snapshot = paths.account_snapshot_path
    empty = {"uid": "", "nickname": ""}
    if not snapshot.exists():
        return empty
    try:
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        primary = data.get("primary") or {}
        uid = primary.get("uid") or ""
        nick = primary.get("nickname") or ""
        return {
            "uid": uid.strip() if isinstance(uid, str) else "",
            "nickname": nick.strip() if isinstance(nick, str) else "",
        }
    except Exception:
        return empty


def get_current_uid(paths: AppPaths) -> str:
    snap = read_account_snapshot(paths)
    if snap.get("uid"):
        return snap["uid"]
    return db_top_uid(paths)


def db_top_uid(paths: AppPaths) -> str:
    if not paths.db_path.exists():
        return ""
    try:
        conn = _connect(paths.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, COUNT(*) as cnt FROM sessions "
            "WHERE user_id IS NOT NULL GROUP BY user_id ORDER BY cnt DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row and row[0] else ""
    except Exception:
        return ""


def session_counts(paths: AppPaths) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not paths.db_path.exists():
        return counts
    try:
        conn = _connect(paths.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, COUNT(*) FROM sessions WHERE user_id IS NOT NULL GROUP BY user_id"
        )
        for uid, n in cur.fetchall():
            counts[uid] = n
        conn.close()
    except sqlite3.Error:
        pass
    return counts


def memory_sizes(paths: AppPaths) -> Dict[str, int]:
    sizes: Dict[str, int] = {}
    if paths.memory_dir.exists():
        for f in paths.memory_dir.glob("*_memory.md"):
            uid = f.stem.replace("_memory", "")
            try:
                sizes[uid] = f.stat().st_size
            except OSError:
                pass
    return sizes


def connector_stats(paths: AppPaths) -> Dict[str, Dict[str, int]]:
    info: Dict[str, Dict[str, int]] = {}
    if not paths.connectors_dir.exists():
        return info
    for d in paths.connectors_dir.iterdir():
        if not d.is_dir() or d.name in ("default", "skills") or d.name.startswith("."):
            continue
        if "-" not in d.name:
            continue
        mcp_servers = 0
        states = 0
        mcp = d / "mcp.json"
        if mcp.exists():
            try:
                data = json.loads(mcp.read_text(encoding="utf-8"))
                servers = data.get("mcpServers") or {}
                mcp_servers = len(servers) if isinstance(servers, dict) else 0
            except Exception:
                pass
        st = d / "connector-states.json"
        if st.exists():
            try:
                data = json.loads(st.read_text(encoding="utf-8"))
                states = len(data) if isinstance(data, dict) else 0
            except Exception:
                pass
        info[d.name] = {"mcp_servers": mcp_servers, "connector_states": states}
    return info


def task_counts(paths: AppPaths) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not paths.tasks_dir.exists():
        return counts
    # tasks are by session, not uid — attribute to current/any via sessions map later
    return counts


def discover_uids(paths: AppPaths) -> List[str]:
    uids = set()
    uids.update(session_counts(paths).keys())
    uids.update(memory_sizes(paths).keys())
    for name in connector_stats(paths).keys():
        uids.add(name)
    snap = read_account_snapshot(paths)
    if snap.get("uid"):
        uids.add(snap["uid"])
    if paths.storage_dir.exists():
        for d in paths.storage_dir.iterdir():
            if not d.is_dir() or not d.name.startswith("user-"):
                continue
            uid = d.name[len("user-") :]
            if uid.endswith("-personal"):
                uid = uid[: -len("-personal")]
            if uid and "-" in uid:
                uids.add(uid)
    return sorted(uids)


def nicknames_cache_path(paths: AppPaths) -> Path:
    return paths.tools_meta_dir / "nicknames.json"


def load_nickname_cache(paths: AppPaths) -> Dict[str, str]:
    p = nicknames_cache_path(paths)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if k and v}
    except Exception:
        pass
    return {}


def save_nickname_cache(paths: AppPaths, mapping: Dict[str, str]) -> None:
    paths.tools_meta_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(nicknames_cache_path(paths), mapping)


def remember_nickname(paths: AppPaths, uid: str, nickname: str) -> None:
    uid = (uid or "").strip()
    nickname = (nickname or "").strip()
    if not uid or not nickname:
        return
    cache = load_nickname_cache(paths)
    if cache.get(uid) == nickname:
        return
    cache[uid] = nickname
    save_nickname_cache(paths, cache)


def _profile_label_map(paths: AppPaths) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in load_profiles(paths=paths):
        uid = str(item.get("uid") or "").strip()
        label = str(item.get("label") or "").strip()
        if uid and label:
            out[uid] = label
    return out


def uid_short(uid: str) -> str:
    uid = (uid or "").strip()
    if not uid:
        return "????"
    parts = uid.split("-")
    return (parts[0] if parts else uid)[:8].lower()


def fallback_display_name(paths: AppPaths, uid: str) -> str:
    """Distinguishable auto name when no official nickname exists.

    Format: `{版本短名} · {uid8}` e.g. `国内版 · a1b2c3d4`
    Never empty, never '未命名'.
    """
    short = uid_short(uid)
    if not short or short == "????":
        return f"{paths.short} · 未知"
    return f"{paths.short} · {short}"


def last_activity_map(paths: AppPaths) -> Dict[str, int]:
    """uid -> max last_activity_at/updated_at (epoch ms)."""
    out: Dict[str, int] = {}
    if not paths.db_path.exists():
        return out
    try:
        conn = _connect(paths.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, MAX(COALESCE(last_activity_at, updated_at, created_at)) "
            "FROM sessions WHERE user_id IS NOT NULL GROUP BY user_id"
        )
        for uid, ts in cur.fetchall():
            if uid and ts:
                try:
                    out[uid] = int(ts)
                except (TypeError, ValueError):
                    pass
        conn.close()
    except sqlite3.Error:
        pass
    return out


def resolve_display_name(
    paths: AppPaths,
    uid: str,
    *,
    current_uid: str = "",
    snap_nickname: str = "",
) -> Tuple[str, str]:
    """Return (display_name, source). Never empty.

    source: snapshot | cache | profile | fallback
    Priority:
    1. live snapshot nickname (current login) — learned into cache
    2. user-edited profile label (higher than cache so rename wins)
    3. persisted nickname cache
    4. snapshot nickname for this uid
    5. distinguishable fallback `{edition} · {uid8}`
    """
    uid = (uid or "").strip()
    if not uid:
        return f"{paths.short} · 未知", "fallback"

    if current_uid and uid == current_uid:
        live = (snap_nickname or "").strip()
        if live:
            remember_nickname(paths, uid, live)
            return live, "snapshot"

    label = _profile_label_map(paths).get(uid, "").strip()
    if label:
        # profile is explicit user intent; also mirror into cache for switch restore
        remember_nickname(paths, uid, label)
        return label, "profile"

    cached = load_nickname_cache(paths).get(uid, "").strip()
    if cached:
        return cached, "cache"

    snap = read_account_snapshot(paths)
    if snap.get("uid") == uid and snap.get("nickname"):
        nick = snap["nickname"].strip()
        if nick:
            remember_nickname(paths, uid, nick)
            return nick, "snapshot"

    return fallback_display_name(paths, uid), "fallback"


def resolve_nickname(paths: AppPaths, uid: str, *, current_uid: str = "", snap_nickname: str = "") -> str:
    name, _ = resolve_display_name(
        paths, uid, current_uid=current_uid, snap_nickname=snap_nickname
    )
    return name


def seed_nicknames_from_snapshot(paths: AppPaths) -> None:
    """Persist current snapshot nickname so future switches keep the name."""
    snap = read_account_snapshot(paths)
    uid = (snap.get("uid") or "").strip()
    nick = (snap.get("nickname") or "").strip()
    if uid and nick:
        remember_nickname(paths, uid, nick)


def set_account_label(edition: str, uid: str, label: str) -> Dict[str, Any]:
    """User-editable display label. Empty label clears profile override."""
    paths = make_paths(edition)
    uid = validate_uid(uid)
    label = (label or "").strip()
    items = load_profiles(edition)
    found = False
    for item in items:
        if item.get("uid") == uid:
            found = True
            if label:
                item["label"] = label
                item["updatedAt"] = datetime.now().isoformat()
            else:
                item.pop("label", None)
            break
    if not found and label:
        items.append(
            {
                "uid": uid,
                "label": label,
                "edition": paths.edition,
                "createdAt": datetime.now().isoformat(),
                "updatedAt": datetime.now().isoformat(),
            }
        )
    paths.tools_meta_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(profiles_path(paths), items)

    if label:
        remember_nickname(paths, uid, label)
    else:
        cache = load_nickname_cache(paths)
        if uid in cache:
            cache.pop(uid, None)
            save_nickname_cache(paths, cache)

    name, source = resolve_display_name(paths, uid)
    return {"ok": True, "uid": uid, "display_name": name, "name_source": source}


def list_accounts(edition: str) -> List[AccountInfo]:
    paths = make_paths(edition)
    seed_nicknames_from_snapshot(paths)
    current = get_current_uid(paths)
    snap = read_account_snapshot(paths)
    sc = session_counts(paths)
    ms = memory_sizes(paths)
    cs = connector_stats(paths)
    last_act = last_activity_map(paths)
    session_to_uid: Dict[str, str] = {}
    if paths.db_path.exists():
        try:
            conn = _connect(paths.db_path)
            cur = conn.cursor()
            cur.execute("SELECT id, user_id FROM sessions")
            for sid, uid in cur.fetchall():
                session_to_uid[sid] = uid
            conn.close()
        except sqlite3.Error:
            pass
    tasks_by_uid: Dict[str, int] = {}
    if paths.tasks_dir.exists():
        for p in paths.tasks_dir.iterdir():
            if p.is_dir():
                uid = session_to_uid.get(p.name, "")
                if uid:
                    tasks_by_uid[uid] = tasks_by_uid.get(uid, 0) + 1

    out: List[AccountInfo] = []
    for uid in discover_uids(paths):
        info = cs.get(uid, {})
        display, source = resolve_display_name(
            paths,
            uid,
            current_uid=current,
            snap_nickname=snap.get("nickname", ""),
        )
        out.append(
            AccountInfo(
                uid=uid,
                nickname=display,
                edition=paths.edition,
                sessions=sc.get(uid, 0),
                memory_bytes=ms.get(uid, 0),
                mcp_servers=info.get("mcp_servers", 0),
                connector_states=info.get("connector_states", 0),
                is_current=uid == current,
                tasks=tasks_by_uid.get(uid, 0),
                display_name=display,
                name_source=source,
                last_activity_at=last_act.get(uid),
                role="current" if uid == current else "other",
            )
        )
    return out


def switch_account(edition: str, target_uid: str) -> Dict[str, Any]:
    """Switch current login identity by rewriting account-snapshot.json."""
    paths = make_paths(edition)
    if not paths.root.exists():
        raise FileNotFoundError(f"edition data root missing: {paths.root}")
    target_uid = validate_uid(target_uid)
    if client_looks_running(paths.edition):
        raise ClientRunningError("客户端正在运行，请完全退出 WorkBuddy 后再切换账号")
    known = {a.uid for a in list_accounts(edition)}
    if target_uid not in known:
        # still allow switch to unknown uid (user may add new)
        pass
    snapshot = paths.account_snapshot_path
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    ensure_within(paths.root, snapshot)
    backup_path = None
    if snapshot.exists():
        paths.backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = str(paths.backup_root / f"account-snapshot.{stamp}.json")
        shutil.copy2(str(snapshot), backup_path)

    data: Dict[str, Any] = {}
    if snapshot.exists():
        try:
            data = json.loads(snapshot.read_text(encoding="utf-8"))
        except Exception:
            raise WriteConflict("account-snapshot.json 无法解析，已中止切换以保护原文件")
        if not isinstance(data, dict):
            raise WriteConflict("account-snapshot.json 结构异常，已中止切换以保护原文件")
    primary = data.get("primary") or {}
    if not isinstance(primary, dict):
        raise WriteConflict("account-snapshot.json primary 结构异常，已中止切换")
    old_uid = primary.get("uid") or ""
    # remember outgoing current nickname, then resolve target display name
    if old_uid and primary.get("nickname"):
        remember_nickname(paths, old_uid, str(primary.get("nickname") or "").strip())
    nickname = resolve_nickname(paths, target_uid)
    # never persist auto-fallback names into client snapshot
    snapshot_nick = ""
    cache = load_nickname_cache(paths)
    cached = cache.get(target_uid, "").strip()
    if cached and " · " not in cached:
        snapshot_nick = cached
    elif nickname and " · " not in nickname and not nickname.startswith("账号 "):
        snapshot_nick = nickname
        remember_nickname(paths, target_uid, nickname)

    primary.update(
        {
            "uid": target_uid,
            "nickname": snapshot_nick,
            "savedAt": int(datetime.now().timestamp() * 1000),
        }
    )
    data["primary"] = primary
    atomic_write_json(snapshot, data)
    return {
        "ok": True,
        "edition": paths.edition,
        "old_uid": old_uid,
        "new_uid": target_uid,
        "nickname": nickname,
        "backup_path": backup_path,
        "need_restart": True,
        "message": f"已切换到「{nickname}」，请完全退出并重启对应 WorkBuddy 客户端",
    }


def profiles_path(paths: AppPaths) -> Path:
    return paths.tools_meta_dir / "profiles.json"


def load_profiles(edition: str = "", paths: Optional[AppPaths] = None) -> List[Dict[str, Any]]:
    if paths is None:
        if not edition:
            return []
        paths = make_paths(edition)
    p = profiles_path(paths)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def add_profile(edition: str, uid: str, label: str = "") -> Dict[str, Any]:
    paths = make_paths(edition)
    paths.tools_meta_dir.mkdir(parents=True, exist_ok=True)
    items = load_profiles(edition)
    uid = validate_uid(uid)
    for item in items:
        if item.get("uid") == uid:
            item["label"] = label or item.get("label") or ""
            item["updatedAt"] = datetime.now().isoformat()
            atomic_write_json(profiles_path(paths), items)
            return item
    item = {
        "uid": uid,
        "label": label or uid[:8],
        "edition": paths.edition,
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
    }
    items.append(item)
    atomic_write_json(profiles_path(paths), items)
    return item

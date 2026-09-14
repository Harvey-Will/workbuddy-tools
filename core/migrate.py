from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .accounts import get_current_uid
from .editions import AppPaths, client_looks_running, make_paths
from .models import DEFAULT_MIGRATE_ITEMS, MigrateItemResult


def _deep_merge(source: dict, target: dict) -> dict:
    for k, v in source.items():
        if k not in target:
            target[k] = v
        elif isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge(v, target[k])
    return target


def _copy_if_missing(src: Path, dst: Path) -> bool:
    if dst.exists() or not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))
    return True


def _checkpoint(conn: sqlite3.Connection) -> None:
    try:
        conn.cursor().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass


def create_backup(paths: AppPaths, target_uid: str, label: str = "migrate") -> str:
    paths.backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    tag = f"{stamp}_{label}_{target_uid[:8]}"
    backup_path = paths.backup_root / tag
    backup_path.mkdir(parents=True, exist_ok=True)
    if paths.db_path.exists():
        shutil.copy2(str(paths.db_path), str(backup_path / "workbuddy.db"))
        for suffix in ("-wal", "-shm"):
            side = Path(str(paths.db_path) + suffix)
            if side.exists():
                shutil.copy2(str(side), str(backup_path / side.name))
    mem = paths.memory_file(target_uid)
    if mem.exists():
        shutil.copy2(str(mem), str(backup_path / mem.name))
    conn_dir = paths.connectors_user_dir(target_uid)
    if conn_dir.exists():
        dst = backup_path / target_uid
        if dst.exists():
            shutil.rmtree(str(dst))
        shutil.copytree(str(conn_dir), str(dst))
    meta = {
        "timestamp": stamp,
        "target_uid": target_uid,
        "edition": paths.edition,
        "created_at": datetime.now().isoformat(),
    }
    (backup_path / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return str(backup_path)


def session_ids_for_uid(paths: AppPaths, uid: str) -> List[str]:
    if not paths.db_path.exists() or not uid:
        return []
    try:
        conn = sqlite3.connect(str(paths.db_path))
        cur = conn.cursor()
        cur.execute("SELECT id FROM sessions WHERE user_id = ?", (uid,))
        rows = [r[0] for r in cur.fetchall() if r and r[0]]
        conn.close()
        return rows
    except sqlite3.Error:
        return []


def migrate_sessions(source: AppPaths, target: AppPaths, source_uid: str, target_uid: str) -> Tuple[int, str]:
    same_db = source.db_path.resolve() == target.db_path.resolve()
    if not source.db_path.exists():
        return 0, "源数据库不存在"
    conn = sqlite3.connect(str(source.db_path))
    cur = conn.cursor()
    _checkpoint(conn)
    cur.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (source_uid,))
    count = cur.fetchone()[0]
    if count == 0:
        conn.close()
        return 0, "源账号无 session"

    if same_db:
        cur.execute("UPDATE sessions SET user_id = ? WHERE user_id = ?", (target_uid, source_uid))
        migrated = cur.rowcount
        conn.commit()
        _checkpoint(conn)
        conn.close()
        return migrated, f"同库 UPDATE {migrated} 条"

    cur.execute("SELECT * FROM sessions WHERE user_id = ?", (source_uid,))
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()

    tconn = sqlite3.connect(str(target.db_path))
    tcur = tconn.cursor()
    _checkpoint(tconn)
    tcur.execute("PRAGMA table_info(sessions)")
    tcols = {r[1] for r in tcur.fetchall()}
    insert_cols = [c for c in cols if c in tcols]
    if "id" not in insert_cols or "user_id" not in insert_cols:
        tconn.close()
        return 0, "目标表结构异常"
    col_sql = ", ".join(insert_cols)
    ph = ", ".join("?" for _ in insert_cols)
    idx = {c: cols.index(c) for c in insert_cols}
    migrated = 0
    skipped = 0
    for row in rows:
        vals = []
        for c in insert_cols:
            v = row[idx[c]]
            if c == "user_id":
                v = target_uid
            vals.append(v)
        try:
            tcur.execute(f"INSERT OR IGNORE INTO sessions ({col_sql}) VALUES ({ph})", vals)
            if tcur.rowcount > 0:
                migrated += 1
            else:
                skipped += 1
        except sqlite3.Error:
            skipped += 1
    tconn.commit()
    _checkpoint(tconn)
    tconn.close()
    return migrated, f"跨库复制 {migrated}，跳过 {skipped}"


def migrate_session_content(session_ids: List[str], source: AppPaths, target: AppPaths) -> int:
    if not session_ids:
        return 0
    sid_set = set(session_ids)
    copied = 0
    if source.projects_dir.exists():
        for proj in source.projects_dir.iterdir():
            if not proj.is_dir():
                continue
            for item in proj.iterdir():
                name = item.name
                base = name.split(".")[0]
                if base in sid_set or (item.is_dir() and name in sid_set):
                    if _copy_if_missing(item, target.projects_dir / proj.name / item.name):
                        copied += 1
    for src_root, dst_root in [
        (source.file_history_dir, target.file_history_dir),
        (source.changes_detail_dir, target.changes_detail_dir),
        (source.workspace_sessions_dir, target.workspace_sessions_dir),
    ]:
        if not src_root.exists():
            continue
        for sid in session_ids:
            if _copy_if_missing(src_root / sid, dst_root / sid):
                copied += 1
    for src_root, dst_root, suffix in [
        (source.changes_index_dir, target.changes_index_dir, ".json"),
        (source.artifact_index_dir, target.artifact_index_dir, ".json"),
    ]:
        if not src_root.exists():
            continue
        for sid in session_ids:
            if _copy_if_missing(src_root / f"{sid}{suffix}", dst_root / f"{sid}{suffix}"):
                copied += 1
    if source.blobs_dir.exists():
        # incremental; do not skip when target already has blobs/
        copied += _merge_copy_dir(source.blobs_dir, target.blobs_dir)
    return copied


def _extract_memory_block(text: str) -> str:
    if "## Memory Block" not in text:
        return text.strip()
    after = text.split("## Memory Block", 1)[1]
    for stop in ("\n---\n", "\n<!-- RAW_JSON_START"):
        idx = after.find(stop)
        if idx != -1:
            after = after[:idx]
    return after.strip()


def merge_memory_profile(src_text: str, dst_text: str, source_uid: str, target_uid: str) -> str:
    if not src_text.strip():
        return dst_text
    if not dst_text.strip():
        return src_text
    src_block = _extract_memory_block(src_text)
    dst_block = _extract_memory_block(dst_text)
    if not src_block or src_block in dst_block:
        return dst_text
    if dst_block:
        merged_block = f"{dst_block}\n\n### 迁移自 {source_uid[:12]}...\n\n{src_block}"
    else:
        merged_block = src_block
    updated_at = datetime.now().isoformat()
    body = (
        "# User Memory Profile\n"
        f"> Last updated: {updated_at}\n"
        "> Version: 1\n\n"
        "## Memory Block\n\n"
        f"{merged_block}\n\n"
        "---\n\n"
        "<!-- RAW_JSON_START\n"
        + json.dumps(
            {"uid": target_uid, "memoryBlock": merged_block, "updatedAt": updated_at},
            ensure_ascii=False,
            indent=2,
        )
        + "\nRAW_JSON_END -->\n"
    )
    return body


def migrate_memory(source: AppPaths, target: AppPaths, source_uid: str, target_uid: str) -> Tuple[int, str]:
    src = source.memory_file(source_uid)
    dst = target.memory_file(target_uid)
    if not src.exists():
        return 0, "源无 Memory"
    src_text = src.read_text(encoding="utf-8")
    dst_text = dst.read_text(encoding="utf-8") if dst.exists() else ""
    if not dst_text.strip():
        merged = _rewrite_memory_identity(src_text, source_uid, target_uid)
    else:
        merged = merge_memory_profile(src_text, dst_text, source_uid, target_uid)
    if merged == dst_text and dst_text:
        return 0, "无新增"
    target.memory_dir.mkdir(parents=True, exist_ok=True)
    dst.write_text(merged, encoding="utf-8")
    return len(merged), f"Memory 已写入 {len(merged)} 字符"


def _rewrite_memory_identity(src_text: str, source_uid: str, target_uid: str) -> str:
    """Copy source memory but stamp target uid in RAW_JSON."""
    import re

    def _sub(m):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict) and data.get("uid") == source_uid:
                data["uid"] = target_uid
            return (
                "RAW_JSON_START\n"
                + json.dumps(data, ensure_ascii=False, indent=2)
                + "\nRAW_JSON_END"
            )
        except Exception:
            return m.group(0)

    return re.sub(
        r"RAW_JSON_START\n(\{.*?\})\nRAW_JSON_END",
        _sub,
        src_text,
        flags=re.S,
    )


def migrate_connectors(source: AppPaths, target: AppPaths, source_uid: str, target_uid: str) -> Tuple[int, str]:
    src_dir = source.connectors_user_dir(source_uid)
    dst_dir = target.connectors_user_dir(target_uid)
    if not src_dir.exists():
        return 0, "源无 Connectors"
    dst_dir.mkdir(parents=True, exist_ok=True)
    added = 0
    for fname in ["mcp.json", "connector-states.json"]:
        src_file = src_dir / fname
        dst_file = dst_dir / fname
        if not src_file.exists():
            continue
        try:
            src_data = json.loads(src_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        dst_data = {}
        if dst_file.exists():
            try:
                dst_data = json.loads(dst_file.read_text(encoding="utf-8"))
            except Exception:
                dst_data = {}
        if isinstance(src_data, dict) and isinstance(dst_data, dict):
            before = len(dst_data.get("mcpServers") or {}) if fname == "mcp.json" else len(dst_data)
            _deep_merge(src_data, dst_data)
            after = len(dst_data.get("mcpServers") or {}) if fname == "mcp.json" else len(dst_data)
            dst_file.write_text(json.dumps(dst_data, indent=2, ensure_ascii=False), encoding="utf-8")
            added += max(0, after - before)
        elif not dst_data:
            dst_file.write_text(json.dumps(src_data, indent=2, ensure_ascii=False), encoding="utf-8")
            added += 1
    servers = 0
    mcp = dst_dir / "mcp.json"
    if mcp.exists():
        try:
            servers = len(json.loads(mcp.read_text(encoding="utf-8")).get("mcpServers") or {})
        except Exception:
            pass
    return added, f"目标 mcpServers={servers}"


def migrate_tasks(source: AppPaths, target: AppPaths, session_ids: List[str]) -> int:
    if not source.tasks_dir.exists():
        return 0
    ids = session_ids or [p.name for p in source.tasks_dir.iterdir() if p.is_dir()]
    target.tasks_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for sid in ids:
        if _copy_if_missing(source.tasks_dir / sid, target.tasks_dir / sid):
            copied += 1
    return copied


def _merge_copy_dir(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for item in src.iterdir():
        if _copy_if_missing(item, dst / item.name):
            n += 1
    return n


def migrate_skills(source: AppPaths, target: AppPaths) -> int:
    return _merge_copy_dir(source.skills_dir, target.skills_dir)


def _merge_installed_plugins(src_file: Path, dst_file: Path) -> int:
    if not src_file.exists():
        return 0

    def load(path: Path) -> dict:
        if not path.exists():
            return {"version": 1, "plugins": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                plugins = data.get("plugins")
                if isinstance(plugins, list):
                    mapped = {}
                    for i, p in enumerate(plugins):
                        k = (p.get("id") or p.get("pluginId") or str(i)) if isinstance(p, dict) else str(i)
                        mapped[str(k)] = p
                    data["plugins"] = mapped
                elif not isinstance(plugins, dict):
                    data["plugins"] = {}
                return data
        except Exception:
            pass
        return {"version": 1, "plugins": {}}

    src = load(src_file)
    dst = load(dst_file)
    sp, dp = src.get("plugins") or {}, dst.get("plugins") or {}
    added = 0
    if isinstance(sp, dict) and isinstance(dp, dict):
        for k, v in sp.items():
            if k not in dp:
                dp[k] = v
                added += 1
        dst["plugins"] = dp
    if added:
        dst_file.write_text(json.dumps(dst, indent=2, ensure_ascii=False), encoding="utf-8")
    return added


def migrate_shared_plugins(source: AppPaths, target: AppPaths) -> int:
    if not source.plugins_dir.exists():
        return 0
    target.plugins_dir.mkdir(parents=True, exist_ok=True)
    n = _merge_installed_plugins(source.plugins_dir / "installed_plugins.json", target.plugins_dir / "installed_plugins.json")
    for sub in ("cache", "data", "marketplaces"):
        n += _merge_copy_dir(source.plugins_dir / sub, target.plugins_dir / sub)
    n += _merge_copy_dir(source.connectors_marketplace_dir, target.connectors_marketplace_dir)
    return n


def migrate_session_usage(source: AppPaths, target: AppPaths, session_ids: List[str]) -> int:
    if not source.db_path.exists() or not target.db_path.exists() or not session_ids:
        return 0
    sconn = sqlite3.connect(str(source.db_path))
    scur = sconn.cursor()
    try:
        scur.execute(
            f"SELECT * FROM session_usage WHERE session_id IN ({','.join('?' for _ in session_ids)})",
            session_ids,
        )
    except sqlite3.Error:
        sconn.close()
        return 0
    rows = scur.fetchall()
    cols = [d[0] for d in scur.description]
    sconn.close()
    tconn = sqlite3.connect(str(target.db_path))
    tcur = tconn.cursor()
    copied = 0
    try:
        tcur.execute("PRAGMA table_info(session_usage)")
        tcols = {r[1] for r in tcur.fetchall()}
        insert_cols = [c for c in cols if c in tcols]
        col_sql = ", ".join(insert_cols)
        ph = ", ".join("?" for _ in insert_cols)
        idx = {c: cols.index(c) for c in insert_cols}
        for row in rows:
            vals = [row[idx[c]] for c in insert_cols]
            try:
                tcur.execute(f"INSERT OR IGNORE INTO session_usage ({col_sql}) VALUES ({ph})", vals)
                copied += tcur.rowcount
            except sqlite3.Error:
                pass
        tconn.commit()
    finally:
        tconn.close()
    return copied


def plan_migrate(
    from_edition: str,
    to_edition: str,
    source_uid: str,
    target_uid: Optional[str] = None,
) -> Dict[str, Any]:
    source = make_paths(from_edition)
    target = make_paths(to_edition)
    if not target_uid:
        target_uid = get_current_uid(target)
    scur_ids = session_ids_for_uid(source, source_uid)
    items = []
    def add(key: str, label: str, count: int, note: str = "") -> None:
        items.append({"key": key, "label": label, "count": count, "note": note})

    add("sessions", "聊天 Sessions", len(scur_ids), "DB sessions 表")
    add("session_content", "会话正文/附件", len(scur_ids), "projects jsonl / blobs")
    mem = source.memory_file(source_uid)
    add("user_memory", "用户记忆", 1 if mem.exists() else 0, str(mem))
    tasks = 0
    if source.tasks_dir.exists():
        tasks = sum(1 for sid in scur_ids if (source.tasks_dir / sid).exists())
        if not scur_ids:
            tasks = sum(1 for p in source.tasks_dir.iterdir() if p.is_dir())
    add("tasks", "历史任务", tasks, "tasks/{session}")
    skills = sum(1 for _ in source.skills_dir.iterdir()) if source.skills_dir.exists() else 0
    add("skills", "技能 Skills", skills, "全局共享目录")
    mcp = source.connectors_user_dir(source_uid) / "mcp.json"
    mcp_n = 0
    if mcp.exists():
        try:
            mcp_n = len(json.loads(mcp.read_text(encoding="utf-8")).get("mcpServers") or {})
        except Exception:
            pass
    add("mcp_connectors", "MCP 连接器", mcp_n, "connectors/{uid}")
    add("shared_plugins", "插件/连接器市场", 0, "plugins + connectors-marketplace")
    add("session_usage", "用量记录", len(scur_ids), "session_usage 表")

    return {
        "from_edition": source.edition,
        "to_edition": target.edition,
        "source_uid": source_uid,
        "target_uid": target_uid,
        "client_running": client_looks_running(target.edition),
        "items": items,
        "default_items": dict(DEFAULT_MIGRATE_ITEMS),
    }


def run_migrate(payload: Dict[str, Any]) -> Dict[str, Any]:
    from_edition = payload["from_edition"]
    to_edition = payload["to_edition"]
    source_uid = payload["source_uid"]
    target_uid = payload.get("target_uid") or get_current_uid(make_paths(to_edition))
    items = {**DEFAULT_MIGRATE_ITEMS, **(payload.get("items") or {})}
    source = make_paths(from_edition)
    target = make_paths(to_edition)

    warnings = []
    if client_looks_running(target.edition):
        warnings.append("目标客户端可能正在运行，memory/mcp 可能被覆盖")

    backups = []
    backups.append(create_backup(target, target_uid, "target"))
    if source.edition != target.edition:
        backups.append(create_backup(source, source_uid, "source"))

    results: List[MigrateItemResult] = []
    # Cache before UPDATE may clear source user_id mapping
    session_ids = session_ids_for_uid(source, source_uid)

    if items.get("sessions"):
        n, detail = migrate_sessions(source, target, source_uid, target_uid)
        results.append(MigrateItemResult("sessions", True, detail, n))

    if items.get("session_content"):
        n = migrate_session_content(session_ids, source, target)
        results.append(MigrateItemResult("session_content", True, f"复制 {n} 项", n))

    if items.get("user_memory"):
        n, detail = migrate_memory(source, target, source_uid, target_uid)
        results.append(MigrateItemResult("user_memory", True, detail, n))

    if items.get("mcp_connectors"):
        n, detail = migrate_connectors(source, target, source_uid, target_uid)
        results.append(MigrateItemResult("mcp_connectors", True, detail, n))

    if items.get("tasks"):
        n = migrate_tasks(source, target, session_ids)
        results.append(MigrateItemResult("tasks", True, f"任务目录 {n}", n))

    if items.get("skills"):
        n = migrate_skills(source, target)
        results.append(MigrateItemResult("skills", True, f"新增 {n}", n))

    if items.get("shared_plugins"):
        n = migrate_shared_plugins(source, target)
        results.append(MigrateItemResult("shared_plugins", True, f"新增 {n}", n))

    if items.get("session_usage"):
        n = migrate_session_usage(source, target, session_ids)
        results.append(MigrateItemResult("session_usage", True, f"复制 {n} 行", n))

    return {
        "ok": True,
        "warnings": warnings,
        "backups": backups,
        "results": [r.to_dict() for r in results],
        "target_uid": target_uid,
        "source_uid": source_uid,
        "need_restart": True,
    }


def list_workspaces(edition: str) -> List[Dict[str, Any]]:
    paths = make_paths(edition)
    out = []
    if not paths.db_path.exists():
        return out
    try:
        conn = sqlite3.connect(str(paths.db_path))
        cur = conn.cursor()
        cur.execute("SELECT cwd, COUNT(*) FROM sessions WHERE cwd IS NOT NULL GROUP BY cwd")
        rows = cur.fetchall()
        conn.close()
    except sqlite3.Error:
        return out
    for cwd, n in rows:
        p = Path(cwd)
        mem = p / ".workbuddy" / "memory"
        out.append(
            {
                "cwd": cwd,
                "sessions": n,
                "exists": p.exists(),
                "project_memory": mem.exists(),
                "memory_files": sum(1 for _ in mem.iterdir()) if mem.exists() else 0,
            }
        )
    return out

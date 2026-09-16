from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .accounts import discover_uids, get_current_uid
from .editions import AppPaths, client_looks_running, make_paths, normalize_edition
from .models import DEFAULT_MIGRATE_ITEMS, MigrateItemResult, MigrateStatus
from .safety import (
    AccountNotFound,
    BackupCorrupted,
    BackupNotFound,
    ClientRunningError,
    MigrationBlocked,
    SafetyError,
    SchemaIncompatible,
    UnsafePath,
    WriteConflict,
    atomic_write_json,
    atomic_write_text,
    ensure_within,
    selected_true_items,
    validate_path_component,
    validate_uid,
)

SESSION_SCOPED_ITEMS = {
    "sessions",
    "session_content",
    "tasks",
    "session_usage",
}

KNOWN_ITEMS = tuple(DEFAULT_MIGRATE_ITEMS.keys())


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


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _backup_sqlite_db(src_db: Path, dst_db: Path) -> None:
    """Use sqlite3.Connection.backup() to produce a consistent point-in-time snapshot.

    This ensures transaction consistency across active WAL files without manual copying.
    """
    if not src_db.exists():
        return
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    src_conn = None
    try:
        try:
            src_uri = f"file:{src_db.resolve().as_posix()}?mode=ro"
            src_conn = sqlite3.connect(src_uri, uri=True)
        except Exception:
            src_conn = sqlite3.connect(str(src_db))
        dst_conn = sqlite3.connect(str(dst_db))
        try:
            with dst_conn:
                src_conn.backup(dst_conn, pages=100)
        finally:
            dst_conn.close()
    finally:
        if src_conn is not None:
            src_conn.close()


def create_backup(paths: AppPaths, target_uid: str, label: str = "migrate") -> str:
    """Create point-in-time snapshot with SQLite backup API and manifest."""
    if client_looks_running(paths.edition):
        raise ClientRunningError(
            f"检测到 {paths.edition} 客户端正在运行。为了数据安全，备份和迁移前请完全退出客户端。"
        )
    target_uid = validate_uid(target_uid)
    paths.backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    tag = f"{stamp}_{label}_{target_uid[:8]}_{rand_suffix}"
    backup_path = paths.backup_root / tag
    backup_path.mkdir(parents=True, exist_ok=True)

    file_manifests: List[Dict[str, Any]] = []

    def record_file(fpath: Path, target_role: str) -> None:
        if fpath.is_file():
            rel = str(fpath.relative_to(backup_path)).replace("\\", "/")
            file_manifests.append({
                "rel_path": rel,
                "target_role": target_role,
                "sha256": _file_sha256(fpath),
                "size_bytes": fpath.stat().st_size,
            })

    # 1. SQLite Database via backup() API
    if paths.db_path.exists():
        dst_db = backup_path / "workbuddy.db"
        _backup_sqlite_db(paths.db_path, dst_db)
        record_file(dst_db, "workbuddy.db")
        for suffix in ("-wal", "-shm"):
            side = Path(str(paths.db_path) + suffix)
            if side.exists():
                dst_side = backup_path / side.name
                shutil.copy2(str(side), str(dst_side))
                record_file(dst_side, side.name)

    # 2. User memory profile
    mem = paths.memory_file(target_uid)
    if mem.exists():
        dst_mem = backup_path / mem.name
        shutil.copy2(str(mem), str(dst_mem))
        record_file(dst_mem, f"memory/{mem.name}")

    # 3. User connectors
    conn_dir = paths.connectors_user_dir(target_uid)
    if conn_dir.exists():
        dst_conn = backup_path / target_uid
        if dst_conn.exists():
            shutil.rmtree(str(dst_conn))
        shutil.copytree(str(conn_dir), str(dst_conn))
        for p in dst_conn.rglob("*"):
            if p.is_file():
                record_file(p, f"connectors/{target_uid}/{p.relative_to(dst_conn)}")

    # 4. Write manifest.json
    manifest = {
        "manifest_version": 2,
        "backup_id": tag,
        "timestamp": stamp,
        "created_at": datetime.now().isoformat(),
        "edition": paths.edition,
        "target_uid": target_uid,
        "label": label,
        "files": file_manifests,
    }
    atomic_write_json(backup_path / "manifest.json", manifest)

    # 5. Backward compatibility: meta.json
    meta = {
        "timestamp": stamp,
        "target_uid": target_uid,
        "edition": paths.edition,
        "created_at": manifest["created_at"],
        "backup_id": tag,
    }
    atomic_write_json(backup_path / "meta.json", meta)
    return str(backup_path)


def restore_backup(paths: AppPaths, backup_id_or_tag: str) -> Dict[str, Any]:
    """Restore database and files from a verified backup directory."""
    if client_looks_running(paths.edition):
        raise ClientRunningError(
            f"检测到 {paths.edition} 客户端正在运行。为了数据安全，恢复备份前请完全退出客户端。"
        )

    safe_tag = validate_path_component(backup_id_or_tag, label="backup_id")
    backup_path = paths.backup_root / safe_tag
    ensure_within(paths.backup_root, backup_path)
    if not backup_path.is_dir():
        raise BackupNotFound(f"备份不存在: {backup_id_or_tag}")

    manifest_file = backup_path / "manifest.json"
    manifest: Optional[Dict[str, Any]] = None
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise BackupCorrupted(f"备份 manifest.json 损坏: {e}") from e

    # Integrity verification
    if manifest and "files" in manifest:
        for fentry in manifest["files"]:
            fpath = backup_path / fentry["rel_path"]
            if not fpath.is_file():
                raise BackupCorrupted(f"备份文件缺失: {fentry['rel_path']}")
            actual_sha = _file_sha256(fpath)
            if actual_sha != fentry.get("sha256"):
                raise BackupCorrupted(f"备份文件已被篡改或损坏: {fentry['rel_path']}")

    restored_files: List[str] = []

    # Restore workbuddy.db
    bk_db = backup_path / "workbuddy.db"
    if bk_db.is_file():
        for suffix in ("-wal", "-shm"):
            stale = Path(str(paths.db_path) + suffix)
            if stale.exists():
                stale.unlink(missing_ok=True)
        shutil.copy2(str(bk_db), str(paths.db_path))
        restored_files.append(str(paths.db_path.name))

    meta_file = backup_path / "meta.json"
    target_uid = ""
    if manifest and manifest.get("target_uid"):
        target_uid = manifest["target_uid"]
    elif meta_file.exists():
        try:
            meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
            target_uid = meta_data.get("target_uid", "")
        except Exception:
            pass

    if target_uid:
        dst_mem = paths.memory_file(target_uid)
        for cand in (backup_path / dst_mem.name, backup_path / f"{target_uid}.md", backup_path / f"{target_uid}_memory.md"):
            if cand.is_file():
                dst_mem.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(cand), str(dst_mem))
                restored_files.append(f"memory/{dst_mem.name}")
                break

        bk_conn = backup_path / target_uid
        if bk_conn.is_dir():
            dst_conn = paths.connectors_user_dir(target_uid)
            if dst_conn.exists():
                shutil.rmtree(str(dst_conn))
            shutil.copytree(str(bk_conn), str(dst_conn))
            restored_files.append(f"connectors/{target_uid}")

    return {
        "ok": True,
        "backup_id": safe_tag,
        "restored_files": restored_files,
        "edition": paths.edition,
    }


def list_backups(paths: AppPaths) -> List[Dict[str, Any]]:
    """List all available backups for this edition."""
    if not paths.backup_root.exists():
        return []
    items: List[Dict[str, Any]] = []
    for d in paths.backup_root.iterdir():
        if not d.is_dir():
            continue
        manifest_file = d / "manifest.json"
        meta_file = d / "meta.json"
        entry: Dict[str, Any] = {
            "backup_id": d.name,
            "created_at": "",
            "target_uid": "",
            "edition": paths.edition,
            "file_count": len(list(d.rglob("*"))),
        }
        if manifest_file.is_file():
            try:
                m = json.loads(manifest_file.read_text(encoding="utf-8"))
                entry["created_at"] = m.get("created_at", "")
                entry["target_uid"] = m.get("target_uid", "")
                entry["label"] = m.get("label", "")
                entry["files"] = m.get("files", [])
            except Exception:
                pass
        elif meta_file.is_file():
            try:
                m = json.loads(meta_file.read_text(encoding="utf-8"))
                entry["created_at"] = m.get("created_at", "")
                entry["target_uid"] = m.get("target_uid", "")
            except Exception:
                pass
        items.append(entry)
    items.sort(key=lambda x: x.get("created_at", "") or x.get("backup_id", ""), reverse=True)
    return items


def _table_columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}


def validate_minimum_schema(db_path: Path, items: Set[str]) -> None:
    """Only check tables/columns that this migration will actually touch."""
    if not items:
        return
    need_sessions_cols = bool(items & SESSION_SCOPED_ITEMS)
    if not db_path.exists():
        if need_sessions_cols or "session_usage" in items:
            raise SchemaIncompatible("源数据库不存在")
        return
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        has_sessions = cur.fetchone() is not None
        if need_sessions_cols and not has_sessions:
            raise SchemaIncompatible(
                "检测到当前 WorkBuddy 数据库结构与本工具验证过的结构不兼容（缺少 sessions 表）。"
                "为避免损坏数据，本次迁移已取消。"
            )
        if has_sessions and need_sessions_cols:
            cols = _table_columns(conn, "sessions")
            if not {"id", "user_id"}.issubset(cols):
                raise SchemaIncompatible(
                    "检测到当前 WorkBuddy 数据库结构与本工具验证过的结构不兼容"
                    "（sessions 缺少 id/user_id）。为避免损坏数据，本次迁移已取消。"
                )
        if "session_usage" in items:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='session_usage'"
            )
            if cur.fetchone() is None:
                raise SchemaIncompatible(
                    "检测到当前 WorkBuddy 数据库结构与本工具验证过的结构不兼容"
                    "（缺少 session_usage 表）。为避免损坏数据，本次迁移已取消。"
                )
            cols = _table_columns(conn, "session_usage")
            if "session_id" not in cols:
                raise SchemaIncompatible(
                    "检测到当前 WorkBuddy 数据库结构与本工具验证过的结构不兼容"
                    "（session_usage 缺少 session_id）。为避免损坏数据，本次迁移已取消。"
                )
    finally:
        conn.close()


def _load_connector_json(path: Path, *, role: str, fname: str) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise WriteConflict(f"{role} {fname} 无法解析，已中止以保护原文件: {e}")
    if not isinstance(data, dict):
        raise WriteConflict(f"{role} {fname} 结构异常，已中止以保护原文件")
    return data


def preflight_migration(
    from_edition: str,
    to_edition: str,
    source_uid: str,
    target_uid: str,
    selected_items: Set[str],
) -> Dict[str, Any]:
    """All safety checks. Must run before the first disk write."""
    fe = normalize_edition(from_edition)
    te = normalize_edition(to_edition)
    source_uid = validate_uid(source_uid)
    target_uid = validate_uid(target_uid)

    source = make_paths(fe)
    target = make_paths(te)

    if not source.root.exists():
        raise AccountNotFound("源版本数据目录不存在")
    if not target.root.exists():
        raise AccountNotFound("目标版本数据目录不存在")

    source_uids = set(discover_uids(source))
    target_uids = set(discover_uids(target))
    if source_uid not in source_uids:
        raise AccountNotFound(f"源账号不存在或未被发现: {source_uid}")
    if target_uid not in target_uids:
        raise AccountNotFound(f"目标账号不存在或未被发现: {target_uid}")

    ensure_within(source.root, source.memory_file(source_uid))
    ensure_within(source.root, source.connectors_user_dir(source_uid))
    ensure_within(target.root, target.memory_file(target_uid))
    ensure_within(target.root, target.connectors_user_dir(target_uid))

    if fe == te and source_uid == target_uid:
        raise MigrationBlocked("源账号和目标账号相同，无需执行迁移。")

    if fe == te and (selected_items & SESSION_SCOPED_ITEMS):
        raise MigrationBlocked(
            "当前版本暂不支持同版本账号之间复制会话相关数据。"
            "这样做需要完整 Session ID 重映射，否则可能修改或混淆源账号数据。"
        )

    if client_looks_running(fe):
        raise ClientRunningError("源客户端正在运行，请完全退出 WorkBuddy 后再迁移。")
    if client_looks_running(te):
        raise ClientRunningError("目标客户端正在运行，请完全退出 WorkBuddy 后再迁移。")

    if selected_items:
        validate_minimum_schema(source.db_path, selected_items)
        if te != fe:
            validate_minimum_schema(target.db_path, selected_items & {"sessions", "session_usage"})

    # Read-only parse checks before any write.
    if "shared_plugins" in selected_items:
        src_plugins = source.plugins_dir / "installed_plugins.json"
        dst_plugins = target.plugins_dir / "installed_plugins.json"
        if src_plugins.exists():
            _load_installed_plugins(src_plugins, role="源")
        if dst_plugins.exists():
            _load_installed_plugins(dst_plugins, role="目标")
    if "mcp_connectors" in selected_items:
        for label, root, uid in (
            ("源", source, source_uid),
            ("目标", target, target_uid),
        ):
            conn_dir = root.connectors_user_dir(uid)
            for fname in ("mcp.json", "connector-states.json"):
                _load_connector_json(conn_dir / fname, role=label, fname=fname)

    return {
        "from_edition": fe,
        "to_edition": te,
        "source_uid": source_uid,
        "target_uid": target_uid,
        "selected_items": sorted(selected_items),
        "ok": True,
    }


def session_ids_for_uid(paths: AppPaths, uid: str, *, strict: bool = False) -> List[str]:
    if not paths.db_path.exists() or not uid:
        if strict and uid:
            raise SchemaIncompatible("源数据库不存在，无法读取 session 列表")
        return []
    try:
        conn = sqlite3.connect(str(paths.db_path))
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM sessions WHERE user_id = ?", (uid,))
            rows = [r[0] for r in cur.fetchall() if r and r[0]]
        finally:
            conn.close()
    except sqlite3.Error as e:
        if strict:
            raise SchemaIncompatible(f"读取源 sessions 失败，已中止: {e}") from e
        return []
    if not strict:
        return [str(x) for x in rows]
    validated: List[str] = []
    for sid in rows:
        validated.append(validate_path_component(sid, label="session_id"))
    return validated


def migrate_sessions(source: AppPaths, target: AppPaths, source_uid: str, target_uid: str) -> Tuple[int, str, str]:
    """Returns (count, detail, status)."""
    same_db = source.db_path.resolve() == target.db_path.resolve()
    if not source.db_path.exists():
        return 0, "源数据库不存在", MigrateStatus.SKIPPED
    if same_db:
        # v0.1.1: never reassign session ownership inside one DB.
        return (
            0,
            "同版本库内不支持会话迁移（会修改源账号归属），已跳过",
            MigrateStatus.SKIPPED,
        )
    conn = sqlite3.connect(str(source.db_path))
    try:
        cur = conn.cursor()
        _checkpoint(conn)
        cur.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (source_uid,))
        count = cur.fetchone()[0]
        if count == 0:
            return 0, "源账号无 session", MigrateStatus.SKIPPED
        cur.execute("SELECT * FROM sessions WHERE user_id = ?", (source_uid,))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    except sqlite3.Error as e:
        raise SchemaIncompatible(f"读取源 sessions 失败，已中止: {e}") from e
    finally:
        conn.close()

    tconn = sqlite3.connect(str(target.db_path))
    try:
        tcur = tconn.cursor()
        _checkpoint(tconn)
        tcur.execute("PRAGMA table_info(sessions)")
        tcols = {r[1] for r in tcur.fetchall()}
        insert_cols = [c for c in cols if c in tcols]
        if "id" not in insert_cols or "user_id" not in insert_cols:
            return 0, "目标表结构异常", MigrateStatus.FAILED
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
            tcur.execute(f"INSERT OR IGNORE INTO sessions ({col_sql}) VALUES ({ph})", vals)
            if tcur.rowcount > 0:
                migrated += 1
            else:
                skipped += 1
        tconn.commit()
    except sqlite3.Error as e:
        tconn.rollback()
        raise SchemaIncompatible(f"写入目标 sessions 失败，已中止: {e}") from e
    finally:
        tconn.close()
    return migrated, f"跨库复制 {migrated}，跳过 {skipped}", MigrateStatus.SUCCESS


SHA256_HEX_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


def find_reachable_blobs(source: AppPaths, session_ids: List[str]) -> List[Path]:
    """Find blob files in source.blobs_dir referenced by the given session_ids."""
    if not source.blobs_dir.exists() or not session_ids:
        return []
    sid_set = set(session_ids)
    referenced_hashes: Set[str] = set()

    # 1. Scan projects/* for session jsonl/txt files
    if source.projects_dir.exists():
        for proj in source.projects_dir.iterdir():
            if not proj.is_dir():
                continue
            for item in proj.iterdir():
                base = item.name.split(".")[0]
                if (base in sid_set or item.name in sid_set) and item.is_file():
                    try:
                        content = item.read_text(encoding="utf-8", errors="ignore")
                        for h in SHA256_HEX_RE.findall(content):
                            referenced_hashes.add(h.lower())
                    except Exception:
                        pass

    # 2. Scan tasks/{session_id}/**/*
    if source.tasks_dir.exists():
        for sid in session_ids:
            try:
                safe_sid = validate_path_component(sid, label="session_id")
            except UnsafePath:
                continue
            task_dir = source.tasks_dir / safe_sid
            if task_dir.is_dir():
                for fpath in task_dir.rglob("*"):
                    if fpath.is_file():
                        try:
                            content = fpath.read_text(encoding="utf-8", errors="ignore")
                            for h in SHA256_HEX_RE.findall(content):
                                referenced_hashes.add(h.lower())
                        except Exception:
                            pass

    # 3. Match blobs in source.blobs_dir
    matched: List[Path] = []
    for h in referenced_hashes:
        prefix = h[:2]
        bucket = source.blobs_dir / prefix
        if bucket.is_dir():
            for blob_file in bucket.iterdir():
                if blob_file.is_file() and blob_file.name.lower().startswith(h):
                    matched.append(blob_file)
    return matched


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

    # Selective blob reachability: only copy blobs referenced by migrated sessions
    if source.blobs_dir.exists():
        target.blobs_dir.mkdir(parents=True, exist_ok=True)
        reachable = find_reachable_blobs(source, session_ids)
        for blob_file in reachable:
            rel = blob_file.relative_to(source.blobs_dir)
            dst_blob = target.blobs_dir / rel
            dst_blob.parent.mkdir(parents=True, exist_ok=True)
            if _copy_if_missing(blob_file, dst_blob):
                copied += 1
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
    ensure_within(target.root, dst)
    atomic_write_text(dst, merged)
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
    ensure_within(target.root, dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    added = 0
    for fname in ["mcp.json", "connector-states.json"]:
        src_file = src_dir / fname
        dst_file = dst_dir / fname
        if not src_file.exists():
            continue
        try:
            src_data = json.loads(src_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise WriteConflict(f"源 {fname} 无法解析，已中止以保护原文件: {e}")
        if not isinstance(src_data, dict):
            raise WriteConflict(f"源 {fname} 结构异常，已中止以保护原文件")
        if dst_file.exists():
            try:
                dst_data = json.loads(dst_file.read_text(encoding="utf-8"))
            except Exception:
                # Never overwrite a malformed target file with {}
                raise WriteConflict(f"{dst_file.name} 无法解析，已中止以保护原文件")
            if not isinstance(dst_data, dict):
                raise WriteConflict(f"{dst_file.name} 结构异常，已中止以保护原文件")
        else:
            dst_data = {}
        if isinstance(src_data, dict) and isinstance(dst_data, dict):
            before = len(dst_data.get("mcpServers") or {}) if fname == "mcp.json" else len(dst_data)
            _deep_merge(src_data, dst_data)
            after = len(dst_data.get("mcpServers") or {}) if fname == "mcp.json" else len(dst_data)
            atomic_write_json(dst_file, dst_data)
            added += max(0, after - before)
        elif not dst_data:
            atomic_write_json(dst_file, src_data)
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
    """Copy only task dirs that belong to the selected source sessions.

    Empty session_ids means no source sessions — never fall back to all tasks.
    """
    if not source.tasks_dir.exists() or not session_ids:
        return 0
    ensure_within(target.root, target.tasks_dir)
    target.tasks_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for sid in session_ids:
        safe_sid = validate_path_component(sid, label="session_id")
        ensure_within(source.tasks_dir, source.tasks_dir / safe_sid)
        ensure_within(target.tasks_dir, target.tasks_dir / safe_sid)
        if _copy_if_missing(source.tasks_dir / safe_sid, target.tasks_dir / safe_sid):
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


def _load_installed_plugins(path: Path, *, role: str) -> dict:
    """Parse installed_plugins.json. Malformed files must not be treated as empty."""
    if not path.exists():
        return {"version": 1, "plugins": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise WriteConflict(f"{role} installed_plugins.json 无法解析，已中止以保护原文件: {e}")
    if not isinstance(data, dict):
        raise WriteConflict(f"{role} installed_plugins.json 结构异常，已中止以保护原文件")
    plugins = data.get("plugins")
    if isinstance(plugins, list):
        mapped = {}
        for i, p in enumerate(plugins):
            k = (p.get("id") or p.get("pluginId") or str(i)) if isinstance(p, dict) else str(i)
            mapped[str(k)] = p
        data["plugins"] = mapped
    elif plugins is None:
        data["plugins"] = {}
    elif not isinstance(plugins, dict):
        raise WriteConflict(f"{role} installed_plugins.json plugins 字段类型异常，已中止")
    return data


def _merge_installed_plugins(src_file: Path, dst_file: Path) -> int:
    if not src_file.exists():
        return 0
    src = _load_installed_plugins(src_file, role="源")
    dst = _load_installed_plugins(dst_file, role="目标")
    sp, dp = src.get("plugins") or {}, dst.get("plugins") or {}
    added = 0
    if isinstance(sp, dict) and isinstance(dp, dict):
        for k, v in sp.items():
            if k not in dp:
                dp[k] = v
                added += 1
        dst["plugins"] = dp
    if added:
        atomic_write_json(dst_file, dst)
    return added


def migrate_shared_plugins(
    source: AppPaths,
    target: AppPaths,
    include_cache_and_data: bool = False,
) -> int:
    if not source.plugins_dir.exists():
        return 0
    target.plugins_dir.mkdir(parents=True, exist_ok=True)
    n = _merge_installed_plugins(
        source.plugins_dir / "installed_plugins.json",
        target.plugins_dir / "installed_plugins.json",
    )
    # Conservative defaults: only copy marketplace descriptors by default,
    # skip ephemeral cache and sensitive plugin persistent data.
    sub_dirs = ("marketplaces",)
    if include_cache_and_data:
        sub_dirs = ("cache", "data", "marketplaces")
    for sub in sub_dirs:
        n += _merge_copy_dir(source.plugins_dir / sub, target.plugins_dir / sub)
    n += _merge_copy_dir(source.connectors_marketplace_dir, target.connectors_marketplace_dir)
    return n


def migrate_session_usage(source: AppPaths, target: AppPaths, session_ids: List[str]) -> int:
    if not source.db_path.exists() or not target.db_path.exists() or not session_ids:
        return 0
    sconn = sqlite3.connect(str(source.db_path))
    try:
        scur = sconn.cursor()
        scur.execute(
            f"SELECT * FROM session_usage WHERE session_id IN ({','.join('?' for _ in session_ids)})",
            session_ids,
        )
        rows = scur.fetchall()
        cols = [d[0] for d in scur.description]
    except sqlite3.Error as e:
        raise SchemaIncompatible(f"读取源 session_usage 失败，已中止: {e}") from e
    finally:
        sconn.close()
    tconn = sqlite3.connect(str(target.db_path))
    try:
        tcur = tconn.cursor()
        tcur.execute("PRAGMA table_info(session_usage)")
        tcols = {r[1] for r in tcur.fetchall()}
        insert_cols = [c for c in cols if c in tcols]
        if "session_id" not in insert_cols:
            raise SchemaIncompatible("目标 session_usage 表结构异常，已中止")
        # Drop surrogate PK `id` so cross-DB copies do not collide with target AUTOINCREMENT ids.
        insert_cols = [c for c in insert_cols if c != "id"]
        col_sql = ", ".join(insert_cols)
        ph = ", ".join("?" for _ in insert_cols)
        idx = {c: cols.index(c) for c in insert_cols}
        copied = 0
        for row in rows:
            vals = [row[idx[c]] for c in insert_cols]
            tcur.execute(f"INSERT OR IGNORE INTO session_usage ({col_sql}) VALUES ({ph})", vals)
            copied += tcur.rowcount
        tconn.commit()
    except sqlite3.Error as e:
        tconn.rollback()
        raise SchemaIncompatible(f"写入目标 session_usage 失败，已中止: {e}") from e
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
    source_uid = validate_uid(source_uid)
    if target_uid:
        target_uid = validate_uid(target_uid)

    scur_ids = session_ids_for_uid(source, source_uid)
    items = []

    def add(key: str, label: str, count: int, note: str = "") -> None:
        items.append({"key": key, "label": label, "count": count, "note": note})

    add("sessions", "聊天 Sessions", len(scur_ids), "DB sessions 表")
    add("session_content", "会话正文/附件", len(scur_ids), "projects jsonl / blobs")
    mem = source.memory_file(source_uid)
    add("user_memory", "用户记忆", 1 if mem.exists() else 0, str(mem))
    tasks = 0
    if source.tasks_dir.exists() and scur_ids:
        tasks = sum(1 for sid in scur_ids if (source.tasks_dir / sid).exists())
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

    same_edition = source.edition == target.edition
    same_account = same_edition and bool(target_uid) and source_uid == target_uid
    blocked_keys = sorted(SESSION_SCOPED_ITEMS) if same_edition and not same_account else []
    warnings: List[str] = []
    blocked = False
    block_reason = ""

    default_items = dict(DEFAULT_MIGRATE_ITEMS)
    if same_edition:
        for k in blocked_keys:
            default_items[k] = False
        if blocked_keys:
            warnings.append("同版本账号间暂不支持会话相关迁移，默认已关闭对应选项")

    # Preflight only the preview defaults (what UI would run), not every known key.
    preview_selected = {k for k, v in default_items.items() if v is True}
    if target_uid and preview_selected:
        try:
            preflight_migration(
                from_edition,
                to_edition,
                source_uid,
                target_uid,
                preview_selected,
            )
        except SafetyError as e:
            blocked = True
            block_reason = e.message
    elif target_uid and not preview_selected:
        warnings.append("当前默认未选择任何可迁移项目")
    else:
        warnings.append("尚未选择目标账号，预览仅展示源侧数量")
        if client_looks_running(source.edition) or client_looks_running(target.edition):
            blocked = True
            block_reason = "客户端正在运行，请完全退出后再执行迁移"

    return {
        "from_edition": source.edition,
        "to_edition": target.edition,
        "source_uid": source_uid,
        "target_uid": target_uid,
        "client_running": client_looks_running(source.edition) or client_looks_running(target.edition),
        "items": items,
        "default_items": default_items,
        "blocked": blocked,
        "block_reason": block_reason,
        "blocked_item_keys": blocked_keys,
        "same_edition": same_edition,
        "same_account": same_account,
        "warnings": warnings,
    }


def _status_for_count(n: int, empty_detail: str = "") -> str:
    if n > 0:
        return MigrateStatus.SUCCESS
    return MigrateStatus.SKIPPED


def run_migrate(
    payload: Dict[str, Any],
    progress_callback: Optional[Callable[[str, int, str], None]] = None,
) -> Dict[str, Any]:
    """Execute migration. Fail-closed: only explicitly true items run.

    Preflight runs here again; plan results are never trusted.
    """
    def notify(stage: str, percent: int, msg: str) -> None:
        if progress_callback:
            try:
                progress_callback(stage, percent, msg)
            except Exception:
                pass

    notify("preflight", 5, "正在进行前置检查与安全验证...")
    from_edition = payload["from_edition"]
    to_edition = payload["to_edition"]
    source_uid = payload["source_uid"]
    target_uid = payload.get("target_uid") or get_current_uid(make_paths(to_edition))

    # Fail-closed selection: no DEFAULT merge.
    selected = selected_true_items(payload.get("items"), KNOWN_ITEMS)
    if not selected:
        notify("completed", 100, "未选择任何迁移项目")
        return {
            "ok": True,
            "status": "skipped",
            "warnings": ["未选择任何迁移项目，未执行任何写入"],
            "backups": [],
            "results": [],
            "target_uid": target_uid,
            "source_uid": source_uid,
            "need_restart": False,
        }

    # Write barrier: every unsafe condition must throw before create_backup.
    preflight = preflight_migration(from_edition, to_edition, source_uid, target_uid, selected)

    source = make_paths(preflight["from_edition"])
    target = make_paths(preflight["to_edition"])
    source_uid = preflight["source_uid"]
    target_uid = preflight["target_uid"]

    # Strict session IDs before any backup/write.
    session_ids: List[str] = []
    if selected & SESSION_SCOPED_ITEMS:
        session_ids = session_ids_for_uid(source, source_uid, strict=True)

    notify("backup", 20, "正在创建 SQLite 一致性快照与 Manifest 备份...")
    warnings: List[str] = []
    backups: List[str] = []
    backups.append(create_backup(target, target_uid, "target"))
    if source.edition != target.edition:
        backups.append(create_backup(source, source_uid, "source"))

    results: List[MigrateItemResult] = []

    def add_result(key: str, status: str, detail: str, count: int = 0) -> None:
        results.append(MigrateItemResult(key, status, detail, count))

    if "sessions" in selected:
        notify("sessions", 35, "正在迁移会话数据...")
        try:
            n, detail, status = migrate_sessions(source, target, source_uid, target_uid)
            add_result("sessions", status, detail, n)
        except Exception as e:
            add_result("sessions", MigrateStatus.FAILED, str(e), 0)

    if "session_content" in selected:
        notify("session_content", 50, "正在迁移会话正文与引用附件...")
        try:
            n = migrate_session_content(session_ids, source, target)
            add_result(
                "session_content",
                _status_for_count(n),
                f"复制 {n} 项" if n else "无会话正文可复制",
                n,
            )
        except Exception as e:
            add_result("session_content", MigrateStatus.FAILED, str(e), 0)

    if "user_memory" in selected:
        notify("user_memory", 65, "正在合并用户记忆...")
        try:
            n, detail = migrate_memory(source, target, source_uid, target_uid)
            add_result("user_memory", _status_for_count(n), detail, n)
        except Exception as e:
            add_result("user_memory", MigrateStatus.FAILED, str(e), 0)

    if "mcp_connectors" in selected:
        notify("mcp_connectors", 75, "正在合并 MCP 工具配置...")
        try:
            n, detail = migrate_connectors(source, target, source_uid, target_uid)
            add_result("mcp_connectors", _status_for_count(n), detail, n)
        except Exception as e:
            add_result("mcp_connectors", MigrateStatus.FAILED, str(e), 0)

    if "tasks" in selected:
        notify("tasks", 82, "正在迁移任务上下文...")
        try:
            n = migrate_tasks(source, target, session_ids)
            add_result(
                "tasks",
                _status_for_count(n),
                f"任务目录 {n}" if n else "无关联任务可迁移",
                n,
            )
        except Exception as e:
            add_result("tasks", MigrateStatus.FAILED, str(e), 0)

    if "skills" in selected:
        notify("skills", 88, "正在复制技能定义...")
        try:
            n = migrate_skills(source, target)
            add_result("skills", _status_for_count(n), f"新增 {n}", n)
        except Exception as e:
            add_result("skills", MigrateStatus.FAILED, str(e), 0)

    if "shared_plugins" in selected:
        notify("shared_plugins", 92, "正在同步插件配置...")
        try:
            n = migrate_shared_plugins(source, target)
            add_result("shared_plugins", _status_for_count(n), f"新增 {n}", n)
        except Exception as e:
            add_result("shared_plugins", MigrateStatus.FAILED, str(e), 0)

    if "session_usage" in selected:
        notify("session_usage", 96, "正在迁移 Token 用量记录...")
        try:
            n = migrate_session_usage(source, target, session_ids)
            add_result(
                "session_usage",
                _status_for_count(n),
                f"复制 {n} 行" if n else "无用量记录可复制",
                n,
            )
        except Exception as e:
            add_result("session_usage", MigrateStatus.FAILED, str(e), 0)

    failed = [r for r in results if r.status == MigrateStatus.FAILED]
    notify("completed", 100, "迁移已完成" if not failed else "迁移部分失败")
    return {
        "ok": not failed,
        "status": "failed" if failed else "success",
        "warnings": warnings,
        "backups": backups,
        "results": [r.to_dict() for r in results],
        "target_uid": target_uid,
        "source_uid": source_uid,
        "selected_items": sorted(selected),
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

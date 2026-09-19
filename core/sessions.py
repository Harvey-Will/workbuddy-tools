from __future__ import annotations

import io
import json
import re
import sqlite3
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .accounts import list_accounts, load_profiles
from .editions import AppPaths, client_looks_running, make_paths, normalize_edition
from .migrate import (
    _checkpoint,
    migrate_session_content,
    migrate_session_usage,
    migrate_tasks,
)
from .safety import (
    AccountNotFound,
    ClientRunningError,
    InvalidUID,
    SchemaIncompatible,
    UnsafePath,
    ensure_within,
    validate_path_component,
    validate_uid,
)
from .tokens import _calc_hit_rate, iter_token_events


def _parse_ts_epoch_ms(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        v = int(float(val))
        if v < 10_000_000_000:
            v *= 1000
        return v
    except (TypeError, ValueError):
        return None


def _format_epoch_ms(ms: Optional[int]) -> str:
    if not ms:
        return "未知"
    try:
        return datetime.fromtimestamp(ms / 1000).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知"


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", name.strip())
    name = re.sub(r"\s+", " ", name)
    return (name[:60] or "未命名对话").strip()


def find_session_jsonl(paths: AppPaths, session_id: str) -> Optional[Path]:
    """Locate the jsonl file for a session within paths.projects_dir."""
    if not paths.projects_dir.exists():
        return None
    try:
        safe_sid = validate_path_component(session_id, label="session_id")
    except UnsafePath:
        return None

    # 1. Direct match: projects/*/{session_id}.jsonl
    matches = list(paths.projects_dir.glob(f"*/{safe_sid}.jsonl"))
    if matches:
        return matches[0]

    # 2. Match in subagents or nested dirs
    nested = list(paths.projects_dir.glob(f"**/{safe_sid}.jsonl"))
    if nested:
        return nested[0]

    return None


def count_session_turns_and_messages(jsonl_path: Optional[Path]) -> Tuple[int, int]:
    """Returns (turn_count, message_count). Turn count is user interactions."""
    if not jsonl_path or not jsonl_path.is_file():
        return 0, 0
    turns = 0
    messages = 0
    try:
        with open(jsonl_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                role = obj.get("role") or (obj.get("message") or {}).get("role")
                msg_type = obj.get("type")
                if role == "user" or (msg_type == "message" and role == "user"):
                    turns += 1
                    messages += 1
                elif role == "assistant" or (msg_type == "message" and role == "assistant"):
                    messages += 1
    except OSError:
        pass
    return turns, messages


def get_all_session_token_stats(paths: AppPaths) -> Dict[str, Dict[str, Any]]:
    """Scan token events and aggregate per session_id."""
    stats: Dict[str, Dict[str, Any]] = {}
    if paths.projects_dir.exists():
        for ev in iter_token_events(paths):
            sid = ev.session_id
            if sid not in stats:
                stats[sid] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_tokens": 0,
                    "events": 0,
                    "model": ev.model or "",
                }
            st = stats[sid]
            st["input_tokens"] += ev.input_tokens
            st["output_tokens"] += ev.output_tokens
            st["cache_read_tokens"] += ev.cache_read
            st["total_tokens"] += ev.total_tokens
            st["events"] += 1
            if ev.model and not st["model"]:
                st["model"] = ev.model

    # Check session_usage in sqlite if some sessions lack jsonl token events
    if paths.db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{paths.db_path.resolve().as_posix()}?mode=ro", uri=True)
            try:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_usage'")
                if cur.fetchone() is not None:
                    cur.execute("PRAGMA table_info(session_usage)")
                    cols = {r[1] for r in cur.fetchall()}
                    if "session_id" in cols:
                        if "input_tokens" in cols and "output_tokens" in cols:
                            cur.execute("SELECT session_id, model, input_tokens, output_tokens FROM session_usage")
                            for row in cur.fetchall():
                                sid, m, inp, out = row[0], row[1], int(row[2] or 0), int(row[3] or 0)
                                if sid not in stats or stats[sid]["total_tokens"] == 0:
                                    if sid not in stats:
                                        stats[sid] = {
                                            "input_tokens": 0,
                                            "output_tokens": 0,
                                            "cache_read_tokens": 0,
                                            "total_tokens": 0,
                                            "events": 0,
                                            "model": m or "",
                                        }
                                    stats[sid]["input_tokens"] += inp
                                    stats[sid]["output_tokens"] += out
                                    stats[sid]["total_tokens"] += inp + out
                        elif "used" in cols:
                            cur.execute("SELECT session_id, used FROM session_usage")
                            for row in cur.fetchall():
                                sid, used = row[0], int(row[1] or 0)
                                if sid not in stats:
                                    stats[sid] = {
                                        "input_tokens": 0,
                                        "output_tokens": 0,
                                        "cache_read_tokens": 0,
                                        "total_tokens": used,
                                        "events": 0,
                                        "model": "",
                                    }
                                elif stats[sid]["total_tokens"] < used:
                                    stats[sid]["total_tokens"] = used
            finally:
                conn.close()
        except Exception:
            pass

    for st in stats.values():
        st["cache_hit_rate"] = _calc_hit_rate(st["input_tokens"], st["cache_read_tokens"])

    return stats


def _table_column_names(conn: sqlite3.Connection, table: str) -> List[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


def list_sessions(
    edition: str,
    uid: Optional[str] = None,
    query: Optional[str] = None,
    sort_by: str = "updated_at",
    order: str = "desc",
) -> List[Dict[str, Any]]:
    """List sessions for an edition with token stats, turns, and account labels."""
    ed = normalize_edition(edition)
    paths = make_paths(ed)
    if not paths.db_path.exists():
        return []

    # Map user UIDs to display names
    account_map: Dict[str, str] = {}
    try:
        accs = list_accounts(ed)
        for a in accs:
            account_map[a.uid] = a.display_name or a.nickname or a.uid[:8]
    except Exception:
        pass

    # Aggregated token usage for this edition
    token_stats_all = get_all_session_token_stats(paths)

    conn = sqlite3.connect(f"file:{paths.db_path.resolve().as_posix()}?mode=ro", uri=True)
    sessions_list: List[Dict[str, Any]] = []
    try:
        cur = conn.cursor()
        cols = _table_column_names(conn, "sessions")
        if not cols or "id" not in cols:
            return []

        select_cols = [
            c for c in [
                "id",
                "user_id",
                "title",
                "custom_title",
                "status",
                "created_at",
                "updated_at",
                "last_activity_at",
                "model",
                "cwd",
                "deleted_at",
            ]
            if c in cols
        ]
        sql = f"SELECT {', '.join(select_cols)} FROM sessions"
        clauses = []
        params: List[Any] = []
        if "deleted_at" in cols:
            clauses.append("deleted_at IS NULL")
        if uid:
            clauses.append("user_id = ?")
            params.append(uid)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        cur.execute(sql, params)
        rows = cur.fetchall()
        col_idx = {c: i for i, c in enumerate(select_cols)}

        for r in rows:
            sid = str(r[col_idx["id"]] or "")
            if not sid:
                continue
            user_id = str(r[col_idx["user_id"]] or "") if "user_id" in col_idx else ""
            raw_title = str(r[col_idx["title"]] or "") if "title" in col_idx else ""
            custom_title = str(r[col_idx["custom_title"]] or "") if "custom_title" in col_idx else ""
            display_title = custom_title if custom_title.strip() else (raw_title or "未命名对话")

            created_at = _parse_ts_epoch_ms(r[col_idx["created_at"]]) if "created_at" in col_idx else None
            updated_at = _parse_ts_epoch_ms(r[col_idx["updated_at"]]) if "updated_at" in col_idx else None
            last_activity = (
                _parse_ts_epoch_ms(r[col_idx["last_activity_at"]]) if "last_activity_at" in col_idx else None
            ) or updated_at or created_at

            status = str(r[col_idx["status"]] or "active") if "status" in col_idx else "active"
            cwd = str(r[col_idx["cwd"]] or "") if "cwd" in col_idx else ""
            model = str(r[col_idx["model"]] or "") if "model" in col_idx else ""

            # Token stats
            tstats = token_stats_all.get(sid, {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "total_tokens": 0,
                "events": 0,
                "model": model,
                "cache_hit_rate": 0.0,
            })
            if not model and tstats.get("model"):
                model = tstats["model"]

            # Turns & messages
            jsonl_p = find_session_jsonl(paths, sid)
            turns, msg_count = count_session_turns_and_messages(jsonl_p)

            item = {
                "id": sid,
                "edition": ed,
                "user_id": user_id,
                "account_name": account_map.get(user_id, user_id[:8] if user_id else "默认账号"),
                "title": display_title,
                "raw_title": raw_title,
                "custom_title": custom_title,
                "status": status,
                "cwd": cwd,
                "model": model or "unknown",
                "created_at": created_at,
                "updated_at": updated_at,
                "last_activity_at": last_activity,
                "turns": turns,
                "message_count": msg_count,
                "input_tokens": tstats["input_tokens"],
                "output_tokens": tstats["output_tokens"],
                "cache_read_tokens": tstats["cache_read_tokens"],
                "total_tokens": tstats["total_tokens"],
                "cache_hit_rate": tstats["cache_hit_rate"],
                "has_jsonl": jsonl_p is not None and jsonl_p.is_file(),
            }
            sessions_list.append(item)
    finally:
        conn.close()

    # Filter query if provided
    if query and query.strip():
        q = query.strip().lower()
        sessions_list = [
            s for s in sessions_list
            if q in s["title"].lower()
            or q in s["id"].lower()
            or q in s["cwd"].lower()
            or q in s["account_name"].lower()
        ]

    # Sorting
    reverse = (order.lower() != "asc")
    if sort_by == "created_at":
        sessions_list.sort(key=lambda s: s.get("created_at") or 0, reverse=reverse)
    elif sort_by in ("tokens", "total_tokens"):
        sessions_list.sort(key=lambda s: s.get("total_tokens") or 0, reverse=reverse)
    elif sort_by in ("cache_hit_rate", "hit_rate"):
        sessions_list.sort(key=lambda s: s.get("cache_hit_rate") or 0.0, reverse=reverse)
    elif sort_by == "turns":
        sessions_list.sort(key=lambda s: s.get("turns") or 0, reverse=reverse)
    elif sort_by == "title":
        sessions_list.sort(key=lambda s: s.get("title", ""), reverse=reverse)
    else:  # default updated_at / last_activity_at
        sessions_list.sort(key=lambda s: s.get("last_activity_at") or s.get("updated_at") or 0, reverse=reverse)

    return sessions_list


def copy_sessions(
    from_edition: str,
    to_edition: str,
    session_ids: List[str],
    target_uid: str,
    title_suffix: Optional[str] = None,
    clone_mode: bool = False,
) -> Dict[str, Any]:
    """Copy or clone selected sessions across accounts or editions.

    If clone_mode is True or same account copy, generates new session UUIDs and
    appends title_suffix (default: ' (副本)').
    Rewrites SQLite records, jsonl history with new sessionIds, tasks, and usage.
    """
    fe = normalize_edition(from_edition)
    te = normalize_edition(to_edition)
    target_uid = validate_uid(target_uid)

    if not session_ids:
        raise ValueError("未选择任何待复制的会话")

    source = make_paths(fe)
    target = make_paths(te)

    if not source.db_path.exists():
        raise SchemaIncompatible("源数据库不存在")
    if not target.db_path.exists():
        raise SchemaIncompatible("目标数据库不存在")

    if client_looks_running(fe):
        raise ClientRunningError(f"源客户端 ({fe}) 正在运行，请完全退出客户端后再复制。")
    if client_looks_running(te):
        raise ClientRunningError(f"目标客户端 ({te}) 正在运行，请完全退出客户端后再复制。")

    validated_sids = [validate_path_component(s, label="session_id") for s in session_ids]

    # Map old_sid -> new_sid
    # Always generate new unique UUID for cloned/copied sessions to avoid collisions
    id_map: Dict[str, str] = {sid: str(uuid.uuid4()) for sid in validated_sids}

    suffix = title_suffix if title_suffix is not None else " (副本)"

    # 1. Clone/insert session rows into target DB
    sconn = sqlite3.connect(str(source.db_path))
    try:
        _checkpoint(sconn)
        scur = sconn.cursor()
        ph = ",".join("?" for _ in validated_sids)
        scur.execute(f"SELECT * FROM sessions WHERE id IN ({ph})", validated_sids)
        rows = scur.fetchall()
        cols = [d[0] for d in scur.description]
    finally:
        sconn.close()

    if not rows:
        raise SchemaIncompatible("在源数据库中未找到指定的会话记录")

    tconn = sqlite3.connect(str(target.db_path))
    now_ms = int(time.time() * 1000)
    try:
        _checkpoint(tconn)
        tcur = tconn.cursor()
        tcols = set(_table_column_names(tconn, "sessions"))
        insert_cols = [c for c in cols if c in tcols]
        if "id" not in insert_cols or "user_id" not in insert_cols:
            raise SchemaIncompatible("目标 sessions 表结构不符合要求")

        col_sql = ", ".join(insert_cols)
        val_ph = ", ".join("?" for _ in insert_cols)
        idx = {c: cols.index(c) for c in insert_cols}

        copied_count = 0
        for row in rows:
            old_sid = row[idx["id"]]
            new_sid = id_map.get(old_sid)
            if not new_sid:
                continue

            # Title adjust
            old_title = str(row[idx["title"]] or "") if "title" in idx else ""
            old_uid = str(row[idx["user_id"]] or "") if "user_id" in idx else ""
            is_same_account = (fe == te and old_uid == target_uid)
            if clone_mode or is_same_account:
                new_title = f"{old_title}{suffix}" if old_title else f"对话{suffix}"
            else:
                new_title = old_title

            vals = []
            for c in insert_cols:
                if c == "id":
                    vals.append(new_sid)
                elif c == "user_id":
                    vals.append(target_uid)
                elif c == "title":
                    vals.append(new_title)
                elif c == "custom_title" and (clone_mode or is_same_account):
                    old_custom = row[idx["custom_title"]]
                    vals.append(f"{old_custom}{suffix}" if old_custom else None)
                elif c == "updated_at":
                    vals.append(now_ms)
                elif c == "last_activity_at":
                    vals.append(now_ms)
                elif c == "deleted_at":
                    vals.append(None)
                else:
                    vals.append(row[idx[c]])

            tcur.execute(f"INSERT INTO sessions ({col_sql}) VALUES ({val_ph})", vals)
            copied_count += tcur.rowcount
        tconn.commit()
    except sqlite3.Error as e:
        tconn.rollback()
        raise SchemaIncompatible(f"写入目标 sessions 表失败: {e}") from e
    finally:
        tconn.close()

    # 2. Content cloning & rewrite (projects jsonl, workspace sessions, blobs, file-history)
    copied_content = migrate_session_content(validated_sids, source, target, session_id_map=id_map)

    # 3. Tasks cloning
    copied_tasks = migrate_tasks(source, target, validated_sids, session_id_map=id_map)

    # 4. Usage records cloning
    copied_usage = migrate_session_usage(source, target, validated_sids, session_id_map=id_map)

    return {
        "ok": True,
        "copied": copied_count,
        "from_edition": fe,
        "to_edition": te,
        "target_uid": target_uid,
        "session_id_map": id_map,
        "details": {
            "sessions": copied_count,
            "content_files": copied_content,
            "tasks": copied_tasks,
            "usage": copied_usage,
        },
    }


def _extract_text_blocks(content: Any) -> str:
    """Extract plain text from string or structured content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                t = b.get("text") or b.get("content")
                if t:
                    parts.append(str(t))
                elif b.get("type") == "image_blob_ref":
                    parts.append("[附图]")
        return "\n".join(parts)
    if isinstance(content, dict):
        if "text" in content:
            return str(content["text"])
        if "content" in content:
            return _extract_text_blocks(content["content"])
    return str(content or "")


def _clean_user_prompt(text: str) -> str:
    """Remove injected system reminders and unwraps query tags."""
    # Remove <system-reminder> blocks
    clean = re.sub(r"<system-reminder[\s\S]*?</system-reminder>", "", text, flags=re.IGNORECASE)
    clean = re.sub(r"^<user_query>([\s\S]*?)</user_query>$", r"\1", clean.strip(), flags=re.IGNORECASE)
    return clean.strip()


def export_session_markdown(
    edition: str,
    session_id: str,
    mode: str = "clean",
) -> Tuple[str, str]:
    """Export a single session to Markdown.

    Returns (filename, markdown_string).
    mode: 'clean' (纯文本: User & Assistant replies only, stripped tool calls)
          'full' (带 Tool Call: detailed technical view with reasoning & tool executions)
    """
    ed = normalize_edition(edition)
    paths = make_paths(ed)
    safe_sid = validate_path_component(session_id, label="session_id")

    title = "未命名对话"
    cwd = ""
    model = "unknown"
    created_at_ms: Optional[int] = None
    updated_at_ms: Optional[int] = None

    if paths.db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{paths.db_path.resolve().as_posix()}?mode=ro", uri=True)
            try:
                cur = conn.cursor()
                cols = _table_column_names(conn, "sessions")
                select_cols = [c for c in ["id", "title", "custom_title", "cwd", "model", "created_at", "updated_at"] if c in cols]
                cur.execute(f"SELECT {', '.join(select_cols)} FROM sessions WHERE id = ?", (safe_sid,))
                row = cur.fetchone()
                if row:
                    col_idx = {c: i for i, c in enumerate(select_cols)}
                    c_title = row[col_idx["custom_title"]] if "custom_title" in col_idx else None
                    r_title = row[col_idx["title"]] if "title" in col_idx else None
                    title = c_title or r_title or "未命名对话"
                    cwd = row[col_idx["cwd"]] if "cwd" in col_idx else ""
                    model = row[col_idx["model"]] if "model" in col_idx else "unknown"
                    created_at_ms = _parse_ts_epoch_ms(row[col_idx["created_at"]]) if "created_at" in col_idx else None
                    updated_at_ms = _parse_ts_epoch_ms(row[col_idx["updated_at"]]) if "updated_at" in col_idx else None
            finally:
                conn.close()
        except Exception:
            pass

    # Read jsonl
    jsonl_p = find_session_jsonl(paths, safe_sid)
    lines_data: List[Dict[str, Any]] = []
    if jsonl_p and jsonl_p.is_file():
        try:
            with open(jsonl_p, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            lines_data.append(obj)
                    except Exception:
                        continue
        except OSError:
            pass

    # Token stats for header
    token_stats_all = get_all_session_token_stats(paths)
    st = token_stats_all.get(safe_sid, {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "total_tokens": 0,
        "cache_hit_rate": 0.0,
    })

    # Prepare markdown buffer
    md: List[str] = []
    md.append(f"# {title}\n")
    md.append(f"- **会话 ID**: `{safe_sid}`")
    md.append(f"- **所属版本**: {paths.label}")
    md.append(f"- **创建时间**: {_format_epoch_ms(created_at_ms)}")
    md.append(f"- **更新时间**: {_format_epoch_ms(updated_at_ms)}")
    if cwd:
        md.append(f"- **工作目录**: `{cwd}`")
    if model and model != "unknown":
        md.append(f"- **模型**: `{model}`")
    md.append(
        f"- **Token 统计**: 总消耗 **{st['total_tokens']:,}** "
        f"(输入: {st['input_tokens']:,} | 缓存读取: {st['cache_read_tokens']:,} | 输出: {st['output_tokens']:,})"
    )
    hit_pct = round(st["cache_hit_rate"] * 100, 1)
    md.append(f"- **Prompt 缓存命中率**: **{hit_pct}%**")
    mode_label = "纯文本（已精简工具调用与思考）" if mode == "clean" else "完整模式（含 Tool Call & 思考过程）"
    md.append(f"- **导出模式**: {mode_label}")
    md.append("\n---\n")

    if not lines_data:
        md.append("*（该会话暂无历史消息记录）*\n")
        filename = f"{_sanitize_filename(title)}_{safe_sid[:8]}.md"
        return filename, "\n".join(md)

    # Process messages
    # In full mode, index function_call_results by callId
    results_by_call_id: Dict[str, Dict[str, Any]] = {}
    if mode == "full":
        for item in lines_data:
            if item.get("type") == "function_call_result":
                cid = item.get("callId")
                if cid:
                    results_by_call_id[cid] = item

    rendered_result_ids: Set[str] = set()

    for item in lines_data:
        msg_type = item.get("type")
        role = item.get("role") or (item.get("message") or {}).get("role")

        if role == "user" or (msg_type == "message" and role == "user"):
            raw_user = _extract_text_blocks(item.get("content"))
            user_text = _clean_user_prompt(raw_user) if mode == "clean" else raw_user.strip()
            if user_text:
                md.append("### 👤 用户\n")
                md.append(f"{user_text}\n")
                md.append("---\n")

        elif role == "assistant" or (msg_type == "message" and role == "assistant"):
            asst_text = _extract_text_blocks(item.get("content")).strip()
            if asst_text:
                md.append("### 🤖 助手\n")
                md.append(f"{asst_text}\n")
                md.append("---\n")

        elif mode == "full":
            if msg_type == "reasoning":
                raw_c = item.get("rawContent") or item.get("content")
                pd_r = (item.get("providerData") or {}).get("reasoning")
                r_text = _extract_text_blocks(raw_c) if raw_c else (str(pd_r or ""))
                if r_text.strip():
                    md.append("<details>")
                    md.append("<summary>💭 思考过程 (Reasoning)</summary>\n")
                    md.append(r_text.strip())
                    md.append("\n</details>\n")

            elif msg_type == "function_call":
                tool_name = item.get("name") or "Tool"
                cid = item.get("callId") or ""
                args = item.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.dumps(json.loads(args), ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                elif isinstance(args, (dict, list)):
                    args = json.dumps(args, ensure_ascii=False, indent=2)

                res_item = results_by_call_id.get(cid) if cid else None
                if res_item:
                    rendered_result_ids.add(res_item.get("id") or cid)
                    out = res_item.get("output")
                    out_text = ""
                    if isinstance(out, dict):
                        out_text = str(out.get("text") or out.get("output") or json.dumps(out, ensure_ascii=False))
                    else:
                        out_text = str(out or "")
                    status = res_item.get("status") or "completed"
                else:
                    out_text = "(无执行输出)"
                    status = "invoked"

                md.append("<details>")
                md.append(f"<summary>🛠️ 工具调用: <code>{tool_name}</code> ({status})</summary>\n")
                md.append("**调用参数:**")
                md.append("```json")
                md.append(str(args or "{}"))
                md.append("```\n")
                md.append("**执行结果:**")
                md.append("```")
                md.append(out_text.strip())
                md.append("```")
                md.append("\n</details>\n")

            elif msg_type == "function_call_result":
                rid = item.get("id") or item.get("callId") or ""
                if rid not in rendered_result_ids:
                    tool_name = item.get("name") or "Tool"
                    out = item.get("output")
                    out_text = out.get("text") if isinstance(out, dict) else str(out or "")
                    md.append("<details>")
                    md.append(f"<summary>⚙️ 工具输出: <code>{tool_name}</code></summary>\n")
                    md.append("```")
                    md.append(str(out_text or "").strip())
                    md.append("```")
                    md.append("\n</details>\n")

    filename = f"{_sanitize_filename(title)}_{safe_sid[:8]}.md"
    return filename, "\n".join(md)


def export_sessions_batch(
    edition: str,
    session_ids: List[str],
    mode: str = "clean",
) -> List[Dict[str, str]]:
    """Export multiple sessions. Returns list of {session_id, filename, content}."""
    results: List[Dict[str, str]] = []
    for sid in session_ids:
        try:
            fname, content = export_session_markdown(edition, sid, mode=mode)
            results.append({
                "session_id": sid,
                "filename": fname,
                "content": content,
            })
        except Exception as e:
            results.append({
                "session_id": sid,
                "filename": f"error_{sid[:8]}.md",
                "content": f"# 导出失败\n\n会话 `{sid}` 导出遇到错误: {e}\n",
            })
    return results


def create_export_zip(items: List[Dict[str, str]]) -> bytes:
    """Package markdown files into an in-memory zip archive."""
    buf = io.BytesIO()
    used_names: Set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for it in items:
            name = it["filename"]
            base = name[:-3] if name.endswith(".md") else name
            counter = 1
            while name in used_names:
                name = f"{base}_{counter}.md"
                counter += 1
            used_names.add(name)
            zf.writestr(name, it["content"].encode("utf-8"))
    buf.seek(0)
    return buf.getvalue()

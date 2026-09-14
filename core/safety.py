from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Set

UID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SafetyError(Exception):
    """Raised when an operation must fail closed before any disk write."""

    code = "safety_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class InvalidUID(SafetyError):
    code = "invalid_uid"


class UnsafePath(SafetyError):
    code = "unsafe_path"


class AccountNotFound(SafetyError):
    code = "account_not_found"


class ClientRunningError(SafetyError):
    code = "client_running"


class MigrationBlocked(SafetyError):
    code = "migration_blocked"


class SchemaIncompatible(SafetyError):
    code = "schema_incompatible"


class WriteConflict(SafetyError):
    code = "write_conflict"


def validate_uid(raw: Any) -> str:
    uid = "" if raw is None else str(raw).strip()
    if not uid:
        raise InvalidUID("UID 不能为空")
    if len(uid) > 128:
        raise InvalidUID("UID 过长")
    if any(ord(c) < 32 for c in uid):
        raise InvalidUID("UID 含非法控制字符")
    if not UID_RE.fullmatch(uid):
        raise InvalidUID("UID 格式非法")
    if uid in {".", ".."} or ".." in uid:
        raise InvalidUID("UID 含非法路径片段")
    return uid


def ensure_within(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafePath(f"路径越界: {candidate}") from exc
    return candidate_resolved


def safe_join(root: Path, *parts: str) -> Path:
    root_resolved = root.resolve()
    path = root_resolved
    for part in parts:
        if part in ("", ".", "..") or "/" in part or "\\" in part or ".." in part:
            raise UnsafePath(f"非法路径片段: {part}")
        path = path / part
    ensure_within(root_resolved, path)
    return path


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with open(tmp, "w", encoding=encoding, newline="") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    import json

    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False))


def selected_true_items(payload_items: Any, known: Iterable[str]) -> Set[str]:
    """Fail-closed: only keys explicitly set to True in the payload are selected."""
    if not isinstance(payload_items, dict):
        return set()
    known_set = set(known)
    return {k for k, v in payload_items.items() if k in known_set and v is True}

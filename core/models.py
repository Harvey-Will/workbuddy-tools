from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class EditionInfo:
    key: str
    label: str
    short: str
    root: str
    exists: bool
    is_current_default: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AccountInfo:
    uid: str
    nickname: str
    edition: str
    sessions: int
    memory_bytes: int
    mcp_servers: int
    connector_states: int
    is_current: bool
    tasks: int = 0
    display_name: str = ""
    name_source: str = "fallback"  # snapshot | cache | profile | fallback
    last_activity_at: Optional[int] = None  # epoch ms
    role: str = "other"  # current | other

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TokenEvent:
    ts_ms: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_read: int
    total_tokens: int
    session_id: str
    edition: str


class MigrateStatus:
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class MigrateItemResult:
    key: str
    status: str
    detail: str
    count: int = 0
    ok: bool = True  # legacy field; status is authoritative

    def __post_init__(self) -> None:
        self.ok = self.status != MigrateStatus.FAILED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULT_MIGRATE_ITEMS = {
    "sessions": True,
    "session_content": True,
    "user_memory": True,
    "tasks": True,
    "skills": True,
    "mcp_connectors": True,
    "shared_plugins": True,
    "session_usage": True,
}

MODEL_PALETTE = [
    "#4F46E5",
    "#06B6D4",
    "#10B981",
    "#F59E0B",
    "#EF4444",
    "#8B5CF6",
    "#EC4899",
    "#14B8A6",
    "#F97316",
    "#3B82F6",
    "#84CC16",
    "#A855F7",
]


def color_for_model(model: str) -> str:
    if not model:
        model = "unknown"
    h = 0
    for ch in model:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return MODEL_PALETTE[h % len(MODEL_PALETTE)]

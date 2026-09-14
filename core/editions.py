from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

from .models import EditionInfo

EDITION_DEFS = {
    "domestic": {
        "key": "domestic",
        "label": "国内版 WorkBuddy",
        "short": "国内版",
        "dir_name": ".workbuddy",
        "process_names": ("WorkBuddy",),
    },
    "international": {
        "key": "international",
        "label": "国际版 WorkBuddyAI",
        "short": "国际版",
        "dir_name": ".workbuddy-ai",
        "process_names": ("WorkBuddyAI",),
    },
}

EDITION_ORDER = ("domestic", "international")

ALIASES = {
    "cn": "domestic",
    "china": "domestic",
    "国内": "domestic",
    "国内版": "domestic",
    "workbuddy": "domestic",
    "intl": "international",
    "global": "international",
    "international": "international",
    "ai": "international",
    "workbuddyai": "international",
    "国际": "international",
    "国际版": "international",
}


def normalize_edition(edition: str) -> str:
    key = (edition or "").strip().lower()
    key = ALIASES.get(key, key)
    if key not in EDITION_DEFS:
        raise ValueError(f"unknown edition: {edition}")
    return key


def data_home() -> Path:
    """Override for tests/sandbox so tools never touch the real user home."""
    override = os.environ.get("WBT_DATA_HOME", "").strip()
    if override:
        return Path(override)
    return Path.home()


def edition_root(edition: str) -> Path:
    return data_home() / EDITION_DEFS[normalize_edition(edition)]["dir_name"]


@dataclass(frozen=True)
class AppPaths:
    edition: str
    root: Path

    @property
    def label(self) -> str:
        return EDITION_DEFS[self.edition]["label"]

    @property
    def short(self) -> str:
        return EDITION_DEFS[self.edition]["short"]

    @property
    def db_path(self) -> Path:
        return self.root / "workbuddy.db"

    @property
    def memory_dir(self) -> Path:
        return self.root / "memory"

    @property
    def connectors_dir(self) -> Path:
        return self.root / "connectors"

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def storage_dir(self) -> Path:
        return self.root / "storage"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def plugins_dir(self) -> Path:
        return self.root / "plugins"

    @property
    def connectors_marketplace_dir(self) -> Path:
        return self.root / "connectors-marketplace"

    @property
    def tools_meta_dir(self) -> Path:
        return self.root / ".workbuddy-tools"

    @property
    def backup_root(self) -> Path:
        return self.tools_meta_dir / "backups"

    @property
    def account_snapshot_path(self) -> Path:
        return self.storage_dir / "skeleton" / "account-snapshot.json"

    @property
    def file_history_dir(self) -> Path:
        return self.root / "file-history"

    @property
    def changes_detail_dir(self) -> Path:
        return self.root / "changes-detail"

    @property
    def changes_index_dir(self) -> Path:
        return self.root / "changes-index"

    @property
    def artifact_index_dir(self) -> Path:
        return self.root / "artifact-index"

    @property
    def blobs_dir(self) -> Path:
        return self.root / "blobs"

    @property
    def workspace_sessions_dir(self) -> Path:
        return self.root / "workspace" / "sessions"

    def memory_file(self, uid: str) -> Path:
        return self.memory_dir / f"{uid}_memory.md"

    def connectors_user_dir(self, uid: str) -> Path:
        return self.connectors_dir / uid


def make_paths(edition: str) -> AppPaths:
    key = normalize_edition(edition)
    return AppPaths(edition=key, root=edition_root(key))


def detect_editions() -> List[str]:
    return [e for e in EDITION_ORDER if edition_root(e).exists() and edition_root(e).is_dir()]


def list_edition_info() -> List[EditionInfo]:
    available = detect_editions()
    preferred = available[0] if available else ""
    out: List[EditionInfo] = []
    for edition in EDITION_ORDER:
        root = edition_root(edition)
        out.append(
            EditionInfo(
                key=edition,
                label=EDITION_DEFS[edition]["label"],
                short=EDITION_DEFS[edition]["short"],
                root=str(root),
                exists=edition in available,
                is_current_default=edition == preferred,
            )
        )
    return out


def client_looks_running(edition: str) -> bool:
    key = normalize_edition(edition)
    names = EDITION_DEFS[key]["process_names"]
    if platform.system() == "Windows":
        for name in names:
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"IMAGENAME eq {name}.exe", "/NH"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
                if name.lower() in out.lower():
                    return True
            except Exception:
                continue
        return False

    pgrep = shutil.which("pgrep")
    if not pgrep:
        return False
    for name in names:
        try:
            r = subprocess.run([pgrep, "-f", name], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return True
        except Exception:
            continue
    return False


def find_client_executables(edition: str) -> List[str]:
    key = normalize_edition(edition)
    if platform.system() == "Windows":
        names = [n + ".exe" for n in EDITION_DEFS[key]["process_names"]]
    else:
        names = list(EDITION_DEFS[key]["process_names"])

    candidates: List[Path] = []
    if platform.system() == "Windows":
        bases = [
            Path("E:/WorkBuddyAI"),
            Path("E:/WorkBuddy"),
            Path("D:/WorkBuddyAI"),
            Path("D:/WorkBuddy"),
            Path.home() / "AppData/Local/Programs/WorkBuddyAI",
            Path.home() / "AppData/Local/Programs/WorkBuddy",
        ]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            bases.append(Path(local) / "Programs/WorkBuddyAI")
            bases.append(Path(local) / "Programs/WorkBuddy")
        for base in bases:
            for n in names:
                candidates.append(base / n)
        for drive in [Path("E:/"), Path("D:/"), Path("C:/")]:
            if not drive.exists():
                continue
            try:
                for child in drive.iterdir():
                    if not child.is_dir():
                        continue
                    lname = child.name.lower()
                    hit = (key == "international" and "workbuddyai" in lname) or (
                        key == "domestic" and "workbuddy" in lname and "workbuddyai" not in lname
                    )
                    if hit:
                        for n in names:
                            candidates.append(child / n)
            except Exception:
                pass
    else:
        for n in names:
            candidates.extend(
                [
                    Path("/usr/bin") / n,
                    Path("/usr/local/bin") / n,
                    Path.home() / ".local/bin" / n,
                ]
            )

    found: List[str] = []
    seen: Set[str] = set()
    for p in candidates:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        try:
            if p.exists() and p.is_file():
                found.append(s)
        except OSError:
            continue
    return found

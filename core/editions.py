from __future__ import annotations

import os
import platform
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from .models import EditionInfo

EDITION_DEFS = {
    "domestic": {
        "key": "domestic",
        "label": "国内版 WorkBuddy",
        "short": "国内版",
        "dir_name": ".workbuddy",
        "process_names": ("WorkBuddy",),
        # macOS .app bundle layout (Electron: bundle id under Contents/MacOS).
        "macos_bundle": "WorkBuddy",
        "macos_executable": "Electron",
    },
    "international": {
        "key": "international",
        "label": "国际版 WorkBuddyAI",
        "short": "国际版",
        "dir_name": ".workbuddy-ai",
        "process_names": ("WorkBuddyAI",),
        "macos_bundle": "WorkBuddyAI",
        "macos_executable": "Electron",
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


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a database for reading without ever needing to write.

    A plain sqlite3.connect() opens read-write, and SQLite then wants to create
    a journal/WAL file next to the database. On macOS that directory is often
    not writable by us (TCC-protected home, or a client that owns it), so even
    a pure read fails with "unable to open database file" and the whole
    migration aborts. Windows does not have this problem, which is why it went
    unnoticed.

    Order of attempts:
      mode=ro      - read-only; still wants a journal, so it fails on a
                     directory we cannot write to
      immutable=1  - assumes the file never changes; skips all locking and
                     journal machinery, so it works on a read-only directory
      plain        - last resort for filesystems that reject both URIs
    """
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))

    posix = db_path.resolve().as_posix()
    last_err: Optional[Exception] = None
    for uri in (f"file:{posix}?mode=ro", f"file:{posix}?mode=ro&immutable=1"):
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(uri, uri=True)
            # Force a real read so a broken URI fails here, not later.
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return conn
        except sqlite3.Error as e:
            last_err = e
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.Error as e:
        # Surface the most informative error we saw, not this last attempt.
        raise last_err if last_err is not None else e


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
        if _pgrep_matches(pgrep, ["-x", name]):
            return True
        for line in _pgrep_lines(pgrep, name):
            if _looks_like_client_process(line, name):
                return True
    return False


def _pgrep_lines(pgrep: str, pattern: str) -> List[str]:
    """Return full command lines matching a pattern.

    pgrep without -l prints only PIDs on macOS, and the PID alone can never be
    classified, so -l is required. Output is "PID <space> command line".
    """
    try:
        r = subprocess.run([pgrep, "-lf", pattern], capture_output=True, text=True)
        if r.returncode != 0:
            return []
    except Exception:
        return []
    out: List[str] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip the leading "PID " field; the rest is the command line.
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            out.append(parts[1])
    return out


def _pgrep_matches(pgrep: str, args: list) -> bool:
    try:
        r = subprocess.run([pgrep, *args], capture_output=True, text=True)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


# Sub-commands that keep a bundle's binary alive without the user running the
# app: Electron helper processes, the crashpad handler, sandbox workers, and
# the CLI's warm-pool worker. Matched as whole argv tokens / path segments so a
# username or directory that merely contains the word cannot mislead us.
_NOT_A_RUNNING_CLIENT_ARGS = (
    "--prewarm",
    "--type=",
    "--stdio",
    "--no-rate-limit",
)

_NOT_A_RUNNING_CLIENT_PATH_SEGMENTS = (
    "/frameworks/",
    "/helpers/",
    "/resources/app.asar.unpacked/",
    "/vendor/sandbox/",
    "/cli/bin/",
)

# Our own app must never be mistaken for the client it manages.
_SELF_MARKERS = ("workbuddy-tools", "workbuddy tools.app", "workbuddy_tools")


def _looks_like_client_process(cmdline: str, name: str) -> bool:
    """Decide whether one pgrep -f match is the client's main UI process.

    pgrep -f matches any argv containing the name, which on macOS wrongly
    includes: this tool's own window, Electron GPU/renderer helpers, the
    crashpad handler, sandbox workers, and WorkBuddy's prewarmed CLI pool.
    None of those mean the user is actively running the client, so blocking
    backup/migration on them is wrong.

    A real client process looks like:
        /Applications/WorkBuddy.app/Contents/MacOS/Electron
    i.e. the bundle's main executable with no sub-command appended.
    """
    low = cmdline.lower()
    if any(marker in low for marker in _SELF_MARKERS):
        return False
    if any(arg in low for arg in _NOT_A_RUNNING_CLIENT_ARGS):
        return False
    if any(seg in low for seg in _NOT_A_RUNNING_CLIENT_PATH_SEGMENTS):
        return False
    if ".app/contents/macos/" not in low:
        return False
    if name.lower() not in low:
        return False
    # The main UI process is launched without extra argv; anything with a
    # trailing sub-command is a child worker, not the app itself.
    return _is_bare_bundle_executable(cmdline)


def _is_bare_bundle_executable(cmdline: str) -> bool:
    """True when argv is only one path pointing at some .app/Contents/MacOS/X."""
    argv = cmdline.split()
    if len(argv) != 1:
        return False
    exe = argv[0].lower()
    marker = ".app/contents/macos/"
    idx = exe.find(marker)
    if idx < 0:
        return False
    # Nothing after the executable name: ".../Contents/MacOS/Electron"
    tail = exe[idx + len(marker):]
    return bool(tail) and "/" not in tail


def _macos_app_candidates(edition: str) -> List[Path]:
    """macOS clients ship as .app bundles whose real executable is not the
    app name (Electron apps use Electron/WorkBuddy as the Mach-O entry)."""
    key = normalize_edition(edition)
    bundle = EDITION_DEFS[key].get("macos_bundle", "")
    exe = EDITION_DEFS[key].get("macos_executable", "")
    if not bundle or not exe:
        return []

    names = list(EDITION_DEFS[key]["process_names"])
    out: List[Path] = []
    app_dirs = [
        Path("/Applications"),
        Path("/Applications/Utilities"),
        Path.home() / "Applications",
    ]
    # Lower-priority fallbacks: on macOS these are firmlinks that resolve to the
    # same volume, so they only matter when the primary locations are missing.
    if platform.system() == "Darwin":
        app_dirs.extend([Path("/System/Applications"), Path("/System/Volumes/Data/Applications")])
    # Some builds ship per-user under ~/Library/Application Support/<Name>/.
    for n in names:
        app_dirs.append(Path.home() / "Library/Application Support" / n)
    for base in app_dirs:
        for n in [bundle, *names]:
            out.append(base / f"{n}.app/Contents/MacOS/{exe}")
            out.append(base / f"{n}.app/Contents/MacOS/{n}")
    return out


def find_client_executables(edition: str) -> List[str]:
    key = normalize_edition(edition)
    if platform.system() == "Windows":
        names = [n + ".exe" for n in EDITION_DEFS[key]["process_names"]]
    else:
        names = list(EDITION_DEFS[key]["process_names"])

    candidates: List[Path] = []
    if platform.system() == "Darwin":
        candidates.extend(_macos_app_candidates(key))
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
    resolved: Set[str] = set()
    for p in candidates:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        try:
            # Resolve so symlinked bundle locations (/Applications vs
            # /System/Volumes/Data/Applications on macOS) collapse to one entry.
            real = str(p.resolve())
            if real in resolved:
                continue
            resolved.add(real)
            if p.exists() and p.is_file():
                found.append(s)
        except OSError:
            continue
    return found

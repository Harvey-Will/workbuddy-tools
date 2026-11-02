from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path

from .editions import normalize_edition


# These are the authentication IDs used by the current desktop clients.
_AUTH_FILENAMES = {
    "domestic": "workbuddy-desktop.info",
    "international": "workbuddy-desktop-ai.info",
}


@dataclass(frozen=True)
class AuthAccountState:
    """Sanitized view of the client's active authentication state.

    Deliberately contains no access token, refresh token, or raw session JSON.
    status:
      - ok: an active, usable session exists
      - missing: no session file exists (legacy clients may use snapshot only)
      - unauthenticated: the client has explicitly logged out
      - invalid: a session file exists but cannot be trusted/parsing failed
    """

    status: str
    uid: str = ""
    nickname: str = ""
    account_type: str = ""


def auth_store_root() -> Path:
    """Return the CodeBuddyExtension shared-data root without creating it."""
    override = os.environ.get("WBT_AUTH_HOME", "").strip()
    if override:
        return Path(override)
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "CodeBuddyExtension"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "CodeBuddyExtension"
    return Path.home() / ".local" / "share" / "CodeBuddyExtension"


def auth_session_path(edition: str) -> Path:
    key = normalize_edition(edition)
    return auth_store_root() / "Data" / "Public" / "auth" / _AUTH_FILENAMES[key]


def logout_marker_path(edition: str) -> Path:
    return auth_session_path(edition).parent / "workbuddy" / "file" / "auth" / "secure" / "logout" / "marker"


def _has_usable_credential(value: object) -> bool:
    """Recognize plaintext and $wbEncrypted credential envelopes safely."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value.get("$wbEncrypted")) and "envelope" in value
    return False


def read_auth_account(edition: str) -> AuthAccountState:
    """Read only the active account metadata from the real client session.

    The client restores its authenticated session from this store, not solely
    from account-snapshot.json. Never return the raw JSON: it contains secrets.
    """
    path = auth_session_path(edition)
    if logout_marker_path(edition).exists():
        return AuthAccountState(status="unauthenticated")
    if not path.exists():
        return AuthAccountState(status="missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return AuthAccountState(status="invalid")
        account = data.get("account")
        auth = data.get("auth")
        if not isinstance(account, dict) or not isinstance(auth, dict):
            return AuthAccountState(status="invalid")
        uid = account.get("uid")
        nickname = account.get("nickname")
        account_type = account.get("type")
        token = auth.get("accessToken")
        if not isinstance(uid, str) or not uid.strip():
            return AuthAccountState(status="invalid")
        if not isinstance(account_type, str) or not account_type.strip():
            return AuthAccountState(status="invalid")
        if not _has_usable_credential(token):
            return AuthAccountState(status="unauthenticated")
        return AuthAccountState(
            status="ok",
            uid=uid.strip(),
            nickname=nickname.strip() if isinstance(nickname, str) else "",
            account_type=account_type.strip(),
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return AuthAccountState(status="invalid")

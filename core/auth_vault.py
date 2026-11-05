from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .auth_store import (
    auth_session_path,
    logout_marker_path,
    parse_auth_session_bytes,
    read_auth_account,
)
from .editions import AppPaths
from .safety import ReauthenticationRequired, SafetyError, VaultUnavailable, WriteConflict, validate_uid

VAULT_VERSION = 1
MAX_SESSION_BYTES = 2 * 1024 * 1024
MAX_VAULT_FILE_BYTES = 5 * 1024 * 1024
_ENTROPY = b"WorkBuddyTools.auth-vault.v1"
_DPAPI_DESCRIPTION = "WorkBuddy Tools account session"


@dataclass(frozen=True)
class VaultRecord:
    uid: str
    nickname: str
    account_type: str
    captured_at: str
    source_sha256: str


def _vault_dir(paths: AppPaths) -> Path:
    return paths.tools_meta_dir / "auth-vault" / paths.edition


def _vault_path(paths: AppPaths, uid: str) -> Path:
    uid = validate_uid(uid)
    return _vault_dir(paths) / f"{uid}.wbtvault"


def _forgotten_path(paths: AppPaths, uid: str) -> Path:
    uid = validate_uid(uid)
    return _vault_dir(paths) / "forgotten" / f"{uid}.json"


def _is_forgotten(paths: AppPaths, uid: str) -> bool:
    return _forgotten_path(paths, uid).is_file()


def _clear_forgotten(paths: AppPaths, uid: str) -> None:
    try:
        _forgotten_path(paths, uid).unlink()
    except (FileNotFoundError, OSError):
        pass


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _dpapi_protect(data: bytes) -> bytes:
    if platform.system() != "Windows":
        raise VaultUnavailable("账号密钥库仅支持 Windows DPAPI，当前平台无法安全加密会话")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def make_blob(value: bytes):
        buffer = ctypes.create_string_buffer(value)
        return DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        input_blob, input_buffer = make_blob(data)
        entropy_blob, entropy_buffer = make_blob(_ENTROPY)
        output_blob = DataBlob()
        ok = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            _DPAPI_DESCRIPTION,
            ctypes.byref(entropy_blob),
            None,
            None,
            0x1,
            ctypes.byref(output_blob),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
            del input_buffer, entropy_buffer
    except OSError as exc:
        raise VaultUnavailable(f"无法使用 Windows DPAPI 加密账号会话（错误码 {exc.errno}）") from exc


def _dpapi_unprotect(data: bytes) -> bytes:
    if platform.system() != "Windows":
        raise VaultUnavailable("账号密钥库仅支持 Windows DPAPI，当前平台无法安全解密会话")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def make_blob(value: bytes):
        buffer = ctypes.create_string_buffer(value)
        return DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        input_blob, input_buffer = make_blob(data)
        entropy_blob, entropy_buffer = make_blob(_ENTROPY)
        output_blob = DataBlob()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            0x1,
            ctypes.byref(output_blob),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
            del input_buffer, entropy_buffer
    except OSError as exc:
        raise VaultUnavailable(f"无法使用 Windows DPAPI 解密账号会话（错误码 {exc.errno}）") from exc


# Kept as module functions so tests can replace the OS protector without DPAPI.
def protect_bytes(data: bytes) -> bytes:
    return _dpapi_protect(data)


def unprotect_bytes(data: bytes) -> bytes:
    return _dpapi_unprotect(data)


def _refresh_expiry_ms(raw: bytes) -> Optional[int]:
    try:
        data = json.loads(raw.decode("utf-8"))
        auth = data.get("auth") or {}
        value = auth.get("refreshExpiresAt") or auth.get("expiresAt")
        if value is None or isinstance(value, bool):
            return None
        timestamp = int(float(value))
        return timestamp * 1000 if timestamp < 10_000_000_000 else timestamp
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError, AttributeError):
        return None


def _read_envelope(path: Path) -> Optional[dict]:
    try:
        if path.stat().st_size > MAX_VAULT_FILE_BYTES:
            raise WriteConflict("账号密钥库文件大小异常")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WriteConflict("账号密钥库文件无法解析") from exc
    if not isinstance(data, dict) or data.get("version") != VAULT_VERSION:
        raise WriteConflict("账号密钥库版本不受支持")
    return data


def _write_vault_blob(
    paths: AppPaths,
    raw: bytes,
    state,
    source: str,
) -> VaultRecord:
    digest = hashlib.sha256(raw).hexdigest()
    target = _vault_path(paths, state.uid)
    try:
        existing = _read_envelope(target)
    except WriteConflict:
        existing = None
    if existing and existing.get("source_sha256") == digest and existing.get("uid") == state.uid:
        _clear_forgotten(paths, state.uid)
        return VaultRecord(
            uid=state.uid,
            nickname=str(existing.get("nickname") or ""),
            account_type=str(existing.get("account_type") or state.account_type),
            captured_at=str(existing.get("captured_at") or ""),
            source_sha256=digest,
        )
    protected = protect_bytes(raw)
    captured_at = datetime.now().isoformat()
    envelope = {
        "version": VAULT_VERSION,
        "uid": state.uid,
        "nickname": state.nickname,
        "account_type": state.account_type,
        "captured_at": captured_at,
        "source_sha256": digest,
        "source": source,
        "expires_at_ms": _refresh_expiry_ms(raw),
        "protector": "windows-dpapi",
        "payload": base64.b64encode(protected).decode("ascii"),
    }
    try:
        _write_private(target, json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
    except OSError as exc:
        raise WriteConflict("账号密钥库写入失败") from exc
    _clear_forgotten(paths, state.uid)
    return VaultRecord(
        uid=state.uid,
        nickname=state.nickname,
        account_type=state.account_type,
        captured_at=captured_at,
        source_sha256=digest,
    )


def capture_current_session(paths: AppPaths, *, strict: bool = False) -> Optional[VaultRecord]:
    """Encrypt the active client session into the per-account vault."""
    auth = read_auth_account(paths.edition)
    if auth.status != "ok":
        if strict:
            raise ReauthenticationRequired("当前没有可保存的有效登录会话")
        return None
    source = auth_session_path(paths.edition)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        if strict:
            raise WriteConflict("无法读取当前客户端登录会话") from exc
        return None
    if not raw or len(raw) > MAX_SESSION_BYTES:
        if strict:
            raise WriteConflict("客户端登录会话大小异常，未保存")
        return None
    parsed = parse_auth_session_bytes(raw)
    if parsed.status != "ok" or parsed.uid != auth.uid:
        if strict:
            raise WriteConflict("客户端登录会话校验失败，未保存")
        return None
    try:
        return _write_vault_blob(paths, raw, auth, "active")
    except VaultUnavailable:
        if strict:
            raise
        return None
    except WriteConflict:
        if strict:
            raise
        return None


def import_client_backups(paths: AppPaths) -> int:
    """Import the newest valid per-account backups the client left behind."""
    active = auth_session_path(paths.edition)
    prefix = active.name[: -len(".info")] + "."
    imported = 0
    candidates: dict[str, tuple[int, bytes, object]] = {}
    try:
        files = list(active.parent.glob(f"{prefix}*.info"))
    except OSError:
        return 0
    for path in files:
        if path.name == active.name:
            continue
        try:
            if path.stat().st_size > MAX_SESSION_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        parsed = parse_auth_session_bytes(raw)
        if parsed.status != "ok":
            continue
        expires_at = _refresh_expiry_ms(raw)
        if expires_at is None or expires_at <= int(time.time() * 1000):
            continue
        try:
            if has_stored_session(paths, parsed.uid) or _is_forgotten(paths, parsed.uid):
                continue
            mtime = path.stat().st_mtime_ns
        except (OSError, SafetyError):
            continue
        previous = candidates.get(parsed.uid)
        if previous is None or mtime > previous[0]:
            candidates[parsed.uid] = (mtime, raw, parsed)
    for uid, (_, raw, parsed) in candidates.items():
        try:
            if has_stored_session(paths, uid) or _is_forgotten(paths, uid):
                continue
            _write_vault_blob(paths, raw, parsed, "client-backup")
            imported += 1
        except (SafetyError, OSError):
            continue
    return imported


def has_stored_session(paths: AppPaths, uid: str) -> bool:
    try:
        target = _vault_path(paths, uid)
        envelope = _read_envelope(target)
        if envelope is None or envelope.get("uid") != uid:
            return False
        expires_at = envelope.get("expires_at_ms")
        if isinstance(expires_at, (int, float)) and expires_at <= int(time.time() * 1000):
            return False
        return True
    except (SafetyError, OSError, ValueError, TypeError):
        return False


def remove_stored_session(paths: AppPaths, uid: str) -> bool:
    target = _vault_path(paths, uid)
    removed = False
    try:
        target.unlink()
        removed = True
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise WriteConflict("账号密钥删除失败") from exc
    tombstone = {
        "uid": validate_uid(uid),
        "forgotten_at": datetime.now().isoformat(),
        "reason": "user_cleared_key",
    }
    try:
        _write_private(_forgotten_path(paths, uid), json.dumps(tombstone, ensure_ascii=False).encode("utf-8"))
    except OSError as exc:
        raise WriteConflict("账号密钥删除标记写入失败") from exc
    return removed


def stored_session_uids(paths: AppPaths) -> List[str]:
    directory = _vault_dir(paths)
    if not directory.exists():
        return []
    uids = []
    for path in directory.glob("*.wbtvault"):
        uid = path.name[: -len(".wbtvault")]
        try:
            validate_uid(uid)
        except Exception:
            continue
        if path.is_file():
            uids.append(uid)
    return sorted(uids)


def write_private_file(path: Path, data: bytes) -> None:
    """Atomically replace a sensitive file with a random, cleaned-up temp."""
    _write_private(path, data)


def load_stored_session(paths: AppPaths, uid: str) -> Tuple[VaultRecord, bytes]:
    uid = validate_uid(uid)
    target = _vault_path(paths, uid)
    envelope = _read_envelope(target)
    if envelope is None:
        raise WriteConflict("该账号尚未保存可用登录会话")
    if envelope.get("uid") != uid:
        raise WriteConflict("账号密钥库身份校验失败")
    try:
        raw = unprotect_bytes(base64.b64decode(str(envelope.get("payload") or ""), validate=True))
    except (ValueError, VaultUnavailable) as exc:
        raise WriteConflict("账号密钥库解密失败，请重新登录该账号") from exc
    except OSError as exc:
        raise WriteConflict("账号密钥库读取失败") from exc
    if not raw or len(raw) > MAX_SESSION_BYTES:
        raise WriteConflict("账号密钥库会话大小异常")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != envelope.get("source_sha256"):
        raise WriteConflict("账号密钥库完整性校验失败")
    parsed = parse_auth_session_bytes(raw)
    if parsed.status != "ok" or parsed.uid != uid:
        raise WriteConflict("账号密钥库中的登录会话已失效")
    if parsed.account_type != envelope.get("account_type"):
        raise WriteConflict("账号密钥库账号类型不一致")
    expires_at = _refresh_expiry_ms(raw)
    if expires_at is None:
        raise WriteConflict("无法确认保存会话的有效期，请重新登录该账号")
    if expires_at <= int(time.time() * 1000):
        raise WriteConflict("保存的登录会话已过期，请重新登录该账号")
    return (
        VaultRecord(
            uid=uid,
            nickname=str(envelope.get("nickname") or parsed.nickname),
            account_type=parsed.account_type,
            captured_at=str(envelope.get("captured_at") or ""),
            source_sha256=digest,
        ),
        raw,
    )


def read_active_session_bytes(paths: AppPaths) -> bytes:
    path = auth_session_path(paths.edition)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise WriteConflict("无法读取当前客户端登录会话") from exc
    if not raw or len(raw) > MAX_SESSION_BYTES:
        raise WriteConflict("当前客户端登录会话大小异常")
    return raw


def install_session_bytes(paths: AppPaths, raw: bytes) -> None:
    parsed = parse_auth_session_bytes(raw)
    if parsed.status != "ok":
        raise WriteConflict("待恢复的客户端登录会话无效")
    target = auth_session_path(paths.edition)
    _write_private(target, raw)
    marker = logout_marker_path(paths.edition)
    if marker.exists():
        try:
            marker.unlink()
        except OSError as exc:
            raise WriteConflict("无法清除客户端退出登录标记") from exc

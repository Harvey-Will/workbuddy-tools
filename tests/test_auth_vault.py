from __future__ import annotations

import json
import os
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import api_accounts
from core import accounts
from core.auth_store import auth_session_path, logout_marker_path, read_auth_account
from core.auth_vault import (
    MAX_SESSION_BYTES,
    capture_current_session,
    import_client_backups,
    load_stored_session,
    remove_stored_session,
    stored_session_uids,
)
from core.editions import make_paths
from core.safety import ReauthenticationRequired, WriteConflict

UID_A = "user-alpha-0001"
UID_B = "user-beta-0002"
EDITIONS = (("domestic", ".workbuddy"), ("international", ".workbuddy-ai"))
_KEY = b"wbt-test-key"


def _fake_protect(data: bytes) -> bytes:
    masked = bytes(byte ^ _KEY[index % len(_KEY)] for index, byte in enumerate(data))
    return b"WBT-TEST-VAULT:" + masked


def _fake_unprotect(data: bytes) -> bytes:
    prefix = b"WBT-TEST-VAULT:"
    if not data.startswith(prefix):
        raise OSError("bad test vault")
    masked = data[len(prefix) :]
    return bytes(byte ^ _KEY[index % len(_KEY)] for index, byte in enumerate(masked))


class AuthVaultCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wbt-vault-test-")
        self.home = Path(self._tmp.name) / "home"
        self.auth_home = Path(self._tmp.name) / "auth-root"
        self.home.mkdir(parents=True)
        self._old_data_home = os.environ.get("WBT_DATA_HOME")
        self._old_auth_home = os.environ.get("WBT_AUTH_HOME")
        os.environ["WBT_DATA_HOME"] = str(self.home)
        os.environ["WBT_AUTH_HOME"] = str(self.auth_home)
        self._patches = [
            patch.object(accounts, "client_looks_running", return_value=False),
            patch("core.auth_vault.protect_bytes", side_effect=_fake_protect),
            patch("core.auth_vault.unprotect_bytes", side_effect=_fake_unprotect),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self._patches):
            item.stop()
        for key, old in (("WBT_DATA_HOME", self._old_data_home), ("WBT_AUTH_HOME", self._old_auth_home)):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self._tmp.cleanup()

    def write_snapshot(self, edition: str, uid: str, nickname: str, account_type: str = "personal") -> Path:
        path = make_paths(edition).account_snapshot_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "primary": {
                        "uid": uid,
                        "nickname": nickname,
                        "type": account_type,
                        "version": 1,
                        "savedAt": 1,
                    }
                }
            ),
            encoding="utf-8",
        )
        return path

    def write_auth(
        self,
        edition: str,
        uid: str,
        nickname: str,
        token: str = "synthetic-secret-access-token",
        account_type: str = "personal",
        refresh_expires_at: int = 4102444800000,
    ) -> Path:
        from core.auth_store import auth_session_path

        path = auth_session_path(edition)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "account": {"uid": uid, "nickname": nickname, "type": account_type},
                    "accounts": [{"uid": uid, "nickname": nickname, "type": account_type}],
                    "allAccounts": [{"uid": uid, "nickname": nickname, "type": account_type}],
                    "auth": {
                        "accessToken": token,
                        "refreshToken": "synthetic-secret-refresh-token",
                        "expiresAt": refresh_expires_at,
                        "refreshExpiresAt": refresh_expires_at,
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def capture(self, edition: str):
        return capture_current_session(make_paths(edition), strict=True)

    def test_auto_capture_encrypts_without_plaintext_token(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                token = f"never-store-in-plaintext-{edition}"
                self.write_snapshot(edition, UID_A, "Alpha")
                auth_path = self.write_auth(edition, UID_A, "Alpha", token=token)
                record = self.capture(edition)
                self.assertEqual(record.uid, UID_A)
                self.assertEqual(stored_session_uids(make_paths(edition)), [UID_A])
                vault_files = list((make_paths(edition).tools_meta_dir / "auth-vault" / edition).glob("*.wbtvault"))
                self.assertEqual(len(vault_files), 1)
                stored_text = vault_files[0].read_text(encoding="utf-8")
                self.assertNotIn(token, stored_text)
                self.assertNotIn("synthetic-secret-refresh-token", stored_text)
                loaded, raw = load_stored_session(make_paths(edition), UID_A)
                self.assertEqual(loaded.uid, UID_A)
                self.assertEqual(raw, auth_path.read_bytes())

    def test_two_stored_accounts_can_switch_back_and_forth(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                self.write_snapshot(edition, UID_A, "Alpha")
                self.write_auth(edition, UID_A, "Alpha")
                self.capture(edition)

                self.write_auth(edition, UID_B, "Beta")
                self.capture(edition)
                self.assertEqual(set(stored_session_uids(make_paths(edition))), {UID_A, UID_B})

                result = accounts.switch_account(edition, UID_A)
                self.assertTrue(result["session_restored"])
                self.assertEqual(read_auth_account(edition).uid, UID_A)
                snapshot = json.loads(make_paths(edition).account_snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(snapshot["primary"]["uid"], UID_A)

                result = accounts.switch_account(edition, UID_B)
                self.assertTrue(result["session_restored"])
                self.assertEqual(read_auth_account(edition).uid, UID_B)
                snapshot = json.loads(make_paths(edition).account_snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(snapshot["primary"]["uid"], UID_B)

    def test_switch_to_uncached_account_requires_login_and_preserves_state(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                snapshot = self.write_snapshot(edition, UID_A, "Alpha")
                auth = self.write_auth(edition, UID_A, "Alpha")
                snapshot_before = snapshot.read_bytes()
                auth_before = auth.read_bytes()
                with self.assertRaises(ReauthenticationRequired):
                    accounts.switch_account(edition, UID_B)
                self.assertEqual(snapshot.read_bytes(), snapshot_before)
                self.assertEqual(auth.read_bytes(), auth_before)
                self.assertEqual(read_auth_account(edition).uid, UID_A)
                self.assertIn(UID_A, stored_session_uids(make_paths(edition)))

    def test_corrupted_vault_fails_before_mutating_auth_or_snapshot(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                self.write_auth(edition, UID_A, "Alpha")
                self.capture(edition)
                self.write_auth(edition, UID_B, "Beta")
                self.capture(edition)
                snapshot = self.write_snapshot(edition, UID_A, "Alpha")
                auth = self.write_auth(edition, UID_A, "Alpha")
                vault = next((make_paths(edition).tools_meta_dir / "auth-vault" / edition).glob(f"{UID_B}.wbtvault"))
                vault.write_text("{broken", encoding="utf-8")
                snapshot_before = snapshot.read_bytes()
                auth_before = auth.read_bytes()
                with self.assertRaises(ReauthenticationRequired):
                    accounts.switch_account(edition, UID_B)
                self.assertEqual(snapshot.read_bytes(), snapshot_before)
                self.assertEqual(auth.read_bytes(), auth_before)
                self.assertEqual(read_auth_account(edition).uid, UID_A)

    def test_snapshot_failure_rolls_back_restored_session(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                self.write_auth(edition, UID_A, "Alpha")
                self.capture(edition)
                self.write_auth(edition, UID_B, "Beta")
                self.capture(edition)
                snapshot = self.write_snapshot(edition, UID_B, "Beta")
                auth = self.write_auth(edition, UID_B, "Beta")
                snapshot_before = snapshot.read_bytes()
                auth_before = auth.read_bytes()
                with patch("core.accounts._sync_snapshot_identity", side_effect=WriteConflict("forced")):
                    with self.assertRaises(WriteConflict):
                        accounts.switch_account(edition, UID_A)
                self.assertEqual(snapshot.read_bytes(), snapshot_before)
                self.assertEqual(auth.read_bytes(), auth_before)
                self.assertEqual(read_auth_account(edition).uid, UID_B)

    def test_install_failure_restores_session_marker_and_snapshot(self):
        edition = "international"
        self.write_auth(edition, UID_A, "Alpha")
        self.capture(edition)
        self.write_auth(edition, UID_B, "Beta")
        self.capture(edition)
        snapshot = self.write_snapshot(edition, UID_A, "Alpha")
        auth = self.write_auth(edition, UID_A, "Alpha")
        marker = logout_marker_path(edition)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("logout-owner", encoding="utf-8")
        auth_before = auth.read_bytes()
        snapshot_before = snapshot.read_bytes()
        marker_before = marker.read_bytes()
        real_install = accounts.install_session_bytes

        def fail_after_install(paths, raw):
            real_install(paths, raw)
            raise WriteConflict("forced install failure")

        with patch("core.accounts.install_session_bytes", side_effect=fail_after_install):
            with self.assertRaises(WriteConflict):
                accounts.switch_account(edition, UID_B)
        self.assertEqual(auth.read_bytes(), auth_before)
        self.assertEqual(snapshot.read_bytes(), snapshot_before)
        self.assertEqual(marker.read_bytes(), marker_before)

    def test_unreadable_current_session_aborts_before_mutation(self):
        edition = "international"
        self.write_auth(edition, UID_A, "Alpha")
        self.capture(edition)
        self.write_auth(edition, UID_B, "Beta")
        self.capture(edition)
        snapshot = self.write_snapshot(edition, UID_A, "Alpha")
        auth = self.write_auth(edition, UID_A, "Alpha")
        auth_before = auth.read_bytes()
        snapshot_before = snapshot.read_bytes()
        with patch("core.accounts.read_active_session_bytes", side_effect=WriteConflict("unreadable")):
            with self.assertRaises(WriteConflict):
                accounts.switch_account(edition, UID_B)
        self.assertEqual(auth.read_bytes(), auth_before)
        self.assertEqual(snapshot.read_bytes(), snapshot_before)

    def test_missing_expiry_is_rejected(self):
        edition = "international"
        self.write_auth(edition, UID_A, "Alpha")
        auth = auth_session_path(edition)
        data = json.loads(auth.read_text(encoding="utf-8"))
        data["auth"].pop("expiresAt", None)
        data["auth"].pop("refreshExpiresAt", None)
        auth.write_text(json.dumps(data), encoding="utf-8")
        self.capture(edition)
        with self.assertRaises(WriteConflict):
            load_stored_session(make_paths(edition), UID_A)

    def test_restoring_removes_client_logout_marker(self):
        edition = "international"
        self.write_auth(edition, UID_A, "Alpha")
        self.capture(edition)
        marker = logout_marker_path(edition)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("logged out", encoding="utf-8")
        self.write_snapshot(edition, UID_B, "Beta")
        result = accounts.switch_account(edition, UID_A)
        self.assertTrue(result["session_restored"])
        self.assertFalse(marker.exists())
        self.assertEqual(read_auth_account(edition).uid, UID_A)

    def test_api_accounts_auto_captures_current_session(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                self.write_snapshot(edition, UID_A, "Alpha")
                self.write_auth(edition, UID_A, "Alpha")
                with patch("backend.app.client_looks_running", return_value=False):
                    payload = api_accounts(edition=edition)
                row = next(item for item in payload["accounts"] if item["uid"] == UID_A)
                self.assertTrue(row["has_stored_session"])
                self.assertIn(UID_A, stored_session_uids(make_paths(edition)))
                rendered = json.dumps(payload)
                self.assertNotIn("synthetic-secret-access-token", rendered)
                self.assertNotIn("synthetic-secret-refresh-token", rendered)

    def test_api_accounts_captures_even_while_client_is_running(self):
        edition = "international"
        self.write_snapshot(edition, UID_A, "Alpha")
        self.write_auth(edition, UID_A, "Alpha")
        with patch("backend.app.client_looks_running", return_value=True):
            payload = api_accounts(edition=edition)
        row = next(item for item in payload["accounts"] if item["uid"] == UID_A)
        self.assertTrue(row["has_stored_session"])
        self.assertTrue(payload["client_running"])
        self.assertIn(UID_A, stored_session_uids(make_paths(edition)))

    def test_expired_stored_session_is_rejected(self):
        edition = "international"
        self.write_auth(edition, UID_A, "Alpha", refresh_expires_at=1)
        self.capture(edition)
        with self.assertRaises(WriteConflict):
            load_stored_session(make_paths(edition), UID_A)

    def test_client_backups_are_imported_for_fast_switch(self):
        edition = "international"
        self.write_snapshot(edition, UID_A, "Alpha")
        self.write_auth(edition, UID_B, "Beta")
        backup_bytes = auth_session_path(edition).read_bytes()
        self.write_auth(edition, UID_A, "Alpha")
        active = auth_session_path(edition)
        backup = active.with_name(f"{active.stem}.2026-01-01T00-00-00-000Z.1.test.info")
        backup.write_bytes(backup_bytes)
        self.assertEqual(import_client_backups(make_paths(edition)), 1)
        self.assertIn(UID_B, stored_session_uids(make_paths(edition)))
        result = accounts.switch_account(edition, UID_B)
        self.assertTrue(result["session_restored"])
        self.assertEqual(read_auth_account(edition).uid, UID_B)

    def test_removed_key_requires_login_again(self):
        edition = "international"
        self.write_auth(edition, UID_A, "Alpha")
        self.capture(edition)
        active = auth_session_path(edition)
        backup = active.with_name(f"{active.stem}.2026-01-02T00-00-00-000Z.1.test.info")
        backup.write_bytes(active.read_bytes())
        self.assertTrue(remove_stored_session(make_paths(edition), UID_A))
        self.assertFalse(remove_stored_session(make_paths(edition), UID_A))
        self.assertEqual(import_client_backups(make_paths(edition)), 0)
        self.assertNotIn(UID_A, stored_session_uids(make_paths(edition)))
        self.write_auth(edition, UID_B, "Beta")
        self.write_snapshot(edition, UID_B, "Beta")
        auth_before = read_auth_account(edition)
        with self.assertRaises(ReauthenticationRequired):
            accounts.switch_account(edition, UID_A)
        self.assertEqual(read_auth_account(edition).uid, auth_before.uid)

    def test_tampered_ciphertext_fails_integrity_check(self):
        edition = "international"
        self.write_auth(edition, UID_A, "Alpha")
        self.capture(edition)
        vault = next((make_paths(edition).tools_meta_dir / "auth-vault" / edition).glob(f"{UID_A}.wbtvault"))
        payload = json.loads(vault.read_text(encoding="utf-8"))
        payload["payload"] = payload["payload"][:-4] + "AAAA"
        vault.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(WriteConflict):
            load_stored_session(make_paths(edition), UID_A)


class TestWindowsDpapi(unittest.TestCase):
    @unittest.skipUnless(platform.system() == "Windows", "Windows DPAPI not available")
    def test_real_dpapi_roundtrip_hides_plaintext(self):
        from core.auth_vault import _dpapi_protect, _dpapi_unprotect

        raw = b"synthetic-dpapi-secret-never-plaintext"
        protected = _dpapi_protect(raw)
        self.assertNotIn(raw, protected)
        self.assertEqual(_dpapi_unprotect(protected), raw)


if __name__ == "__main__":
    unittest.main()

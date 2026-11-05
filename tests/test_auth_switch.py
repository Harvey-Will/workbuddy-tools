from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import CreateBackupBody, SwitchBody, api_accounts, api_backups_create, api_switch
from core import accounts
from core.auth_store import (
    auth_session_path,
    logout_marker_path,
    read_auth_account,
)
from core.editions import make_paths
from core.safety import ReauthenticationRequired, WriteConflict


UID_A = "user-alpha-0001"
UID_B = "user-beta-0002"
EDITIONS = (
    ("domestic", ".workbuddy"),
    ("international", ".workbuddy-ai"),
)


class AuthSwitchCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wbt-auth-test-")
        self.home = Path(self._tmp.name) / "home"
        self.auth_home = Path(self._tmp.name) / "auth-root"
        self.home.mkdir(parents=True)
        self._old_data_home = os.environ.get("WBT_DATA_HOME")
        self._old_auth_home = os.environ.get("WBT_AUTH_HOME")
        os.environ["WBT_DATA_HOME"] = str(self.home)
        os.environ["WBT_AUTH_HOME"] = str(self.auth_home)
        self._client_patch = patch.object(accounts, "client_looks_running", return_value=False)
        self._client_patch.start()

    def tearDown(self) -> None:
        self._client_patch.stop()
        for key, old in (("WBT_DATA_HOME", self._old_data_home), ("WBT_AUTH_HOME", self._old_auth_home)):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self._tmp.cleanup()

    def make_snapshot(
        self,
        edition: str,
        uid: str = UID_A,
        *,
        write: bool = True,
        nickname: str = "Snapshot Source",
        account_type: str = "personal",
    ) -> Path:
        paths = make_paths(edition)
        paths.account_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        if write:
            paths.account_snapshot_path.write_text(
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
        return paths.account_snapshot_path

    def write_auth(
        self,
        edition: str,
        uid: str,
        nickname: str = "Authenticated User",
        account_type: str | None = "personal",
    ) -> Path:
        path = auth_session_path(edition)
        path.parent.mkdir(parents=True, exist_ok=True)
        account = {
            "uid": uid,
            "nickname": nickname,
            "lastLogin": True,
            "pluginEnabled": True,
        }
        if account_type is not None:
            account["type"] = account_type
        if edition == "international":
            access_token = {"$wbEncrypted": True, "envelope": {"data": "synthetic-access-token-never-log"}}
            refresh_token = {"$wbEncrypted": True, "envelope": {"data": "synthetic-refresh-token-never-log"}}
        else:
            access_token = "synthetic-access-token-never-log"
            refresh_token = "synthetic-refresh-token-never-log"
        path.write_text(
            json.dumps(
                {
                    "account": account,
                    "accounts": [account],
                    "allAccounts": [account],
                    "auth": {
                        "accessToken": access_token,
                        "refreshToken": refresh_token,
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_switch_syncs_only_already_authenticated_target(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                snapshot = self.make_snapshot(edition)
                auth = self.write_auth(edition, UID_B, "Target User")
                auth_before = auth.read_bytes()
                result = accounts.switch_account(edition, UID_B)
                self.assertTrue(result["ok"])
                self.assertTrue(result["auth_verified"])
                primary = json.loads(snapshot.read_text(encoding="utf-8"))["primary"]
                self.assertEqual(primary["uid"], UID_B)
                self.assertEqual(primary["nickname"], "Target User")
                self.assertEqual(primary["version"], 1)
                self.assertEqual(primary["type"], "personal")
                self.assertEqual(auth.read_bytes(), auth_before)

    def test_other_active_account_requires_native_reauthentication(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                snapshot = self.make_snapshot(edition, UID_A)
                auth = self.write_auth(edition, UID_A)
                snapshot_before = snapshot.read_bytes()
                auth_before = auth.read_bytes()
                with self.assertRaises(ReauthenticationRequired):
                    accounts.switch_account(edition, UID_B)
                self.assertEqual(snapshot.read_bytes(), snapshot_before)
                self.assertEqual(auth.read_bytes(), auth_before)

    def test_missing_and_logged_out_auth_cannot_fake_success(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition, mode="missing"):
                snapshot = self.make_snapshot(edition, UID_A)
                before = snapshot.read_bytes()
                with self.assertRaises(ReauthenticationRequired):
                    accounts.switch_account(edition, UID_B)
                self.assertEqual(snapshot.read_bytes(), before)
            with self.subTest(edition=edition, mode="logout-marker"):
                snapshot = self.make_snapshot(edition, UID_A)
                self.write_auth(edition, UID_B)
                marker = logout_marker_path(edition)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("logged out", encoding="utf-8")
                before = snapshot.read_bytes()
                with self.assertRaises(ReauthenticationRequired):
                    accounts.switch_account(edition, UID_B)
                self.assertEqual(snapshot.read_bytes(), before)
                self.assertEqual(accounts.get_current_uid(make_paths(edition)), "")
                marker.unlink()

    def test_malformed_auth_fails_closed(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                snapshot = self.make_snapshot(edition, UID_A)
                auth = auth_session_path(edition)
                auth.parent.mkdir(parents=True, exist_ok=True)
                auth.write_text("{not-json", encoding="utf-8")
                before = snapshot.read_bytes()
                with self.assertRaises(WriteConflict):
                    accounts.switch_account(edition, UID_B)
                self.assertEqual(snapshot.read_bytes(), before)

    def test_missing_snapshot_gets_required_schema_from_verified_auth(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                snapshot = self.make_snapshot(edition, write=False)
                self.write_auth(edition, UID_B)
                result = accounts.switch_account(edition, UID_B)
                self.assertTrue(result["ok"])
                primary = json.loads(snapshot.read_text(encoding="utf-8"))["primary"]
                self.assertEqual(primary["uid"], UID_B)
                self.assertEqual(primary["version"], 1)
                self.assertEqual(primary["type"], "personal")

    def test_current_account_and_api_prefer_real_auth_over_stale_snapshot(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                self.make_snapshot(edition, UID_A)
                self.write_auth(edition, UID_B, "Real Login")
                current = accounts.get_current_account(make_paths(edition))
                self.assertEqual(current["uid"], UID_B)
                self.assertEqual(current["nickname"], "Real Login")
                with patch("backend.app.client_looks_running", return_value=False):
                    payload = api_accounts(edition=edition)
                self.assertEqual(payload["current_uid"], UID_B)
                self.assertEqual(payload["snapshot_uid"], UID_A)
                current_row = next(a for a in payload["accounts"] if a["uid"] == UID_B)
                self.assertTrue(current_row["is_current"])
                self.assertEqual(current_row["nickname"], "Real Login")

                # This is the UI's explicit post-login "同步快照" workflow.
                accounts.switch_account(edition, UID_B)
                with patch("backend.app.client_looks_running", return_value=False):
                    synced = api_accounts(edition=edition)
                self.assertEqual(synced["current_uid"], UID_B)
                self.assertEqual(synced["snapshot_uid"], UID_B)

    def test_default_backup_uses_verified_auth_not_stale_snapshot(self):
        self.make_snapshot("international", UID_A)
        self.write_auth("international", UID_B)
        fake_backup = str(Path(self._tmp.name) / "backup-id")
        with patch("backend.app.migrate_mod.create_backup", return_value=fake_backup) as create:
            result = api_backups_create(CreateBackupBody(edition="international", target_uid=None))
        self.assertTrue(result["ok"])
        self.assertEqual(create.call_args.kwargs["target_uid"], UID_B)

    def test_snapshot_type_is_replaced_by_verified_identity_type(self):
        for edition, _ in EDITIONS:
            with self.subTest(edition=edition):
                snapshot = self.make_snapshot(edition, UID_A, account_type="enterprise")
                self.write_auth(edition, UID_B, account_type="personal")
                accounts.switch_account(edition, UID_B)
                primary = json.loads(snapshot.read_text(encoding="utf-8"))["primary"]
                self.assertEqual(primary["uid"], UID_B)
                self.assertEqual(primary["type"], "personal")

    def test_missing_auth_account_type_fails_closed(self):
        snapshot = self.make_snapshot("international", UID_A, account_type="enterprise")
        self.write_auth("international", UID_B, account_type=None)
        before = snapshot.read_bytes()
        with self.assertRaises(WriteConflict):
            accounts.switch_account("international", UID_B)
        self.assertEqual(snapshot.read_bytes(), before)

    def test_empty_auth_nickname_never_reuses_other_snapshot_identity(self):
        paths = make_paths("international")
        self.make_snapshot("international", UID_A, nickname="Alice From A")
        self.write_auth("international", UID_B, nickname="")
        rows = accounts.list_accounts("international")
        current = next(row for row in rows if row.uid == UID_B)
        self.assertNotEqual(current.display_name, "Alice From A")
        self.assertNotEqual(accounts.load_nickname_cache(paths).get(UID_B), "Alice From A")

    def test_auth_paths_match_installed_client_contract(self):
        auth_dir = self.auth_home / "Data" / "Public" / "auth"
        self.assertEqual(auth_session_path("domestic"), auth_dir / "workbuddy-desktop.info")
        self.assertEqual(auth_session_path("international"), auth_dir / "workbuddy-desktop-ai.info")
        expected_marker = auth_dir / "workbuddy" / "file" / "auth" / "secure" / "logout" / "marker"
        self.assertEqual(logout_marker_path("domestic"), expected_marker)
        self.assertEqual(logout_marker_path("international"), expected_marker)

    def test_reauth_error_is_mapped_to_actionable_409(self):
        self.make_snapshot("international", UID_A)
        self.write_auth("international", UID_A)
        with self.assertRaises(Exception) as ctx:
            api_switch(SwitchBody(edition="international", target_uid=UID_B))
        exc = ctx.exception
        self.assertEqual(getattr(exc, "status_code", None), 409)
        self.assertEqual(exc.detail["code"], "reauth_required")

    def test_sanitized_auth_view_never_contains_session_secrets(self):
        self.write_auth("international", UID_B)
        state = read_auth_account("international")
        self.assertEqual(state.status, "ok")
        rendered = repr(state)
        self.assertNotIn("synthetic-access-token-never-log", rendered)
        self.assertNotIn("synthetic-refresh-token-never-log", rendered)
        self.assertFalse(hasattr(state, "accessToken"))
        self.assertFalse(hasattr(state, "refreshToken"))


if __name__ == "__main__":
    unittest.main()

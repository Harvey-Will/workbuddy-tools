from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException

from backend.app import (
    CreateBackupBody,
    MigrateRunBody,
    RestoreBody,
    SwitchBody,
    _migrate_lock,
    api_backups_create,
    api_backups_restore,
    api_migrate_create_job,
    api_migrate_get_job,
    api_switch,
)
from core import editions as editions_mod
from core import migrate as migrate_mod
from core.editions import make_paths
from core.migrate import create_backup, list_backups


class TestUXPhase3(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wbt-test-phase3-", ignore_cleanup_errors=True)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir(parents=True)
        self._old_env = os.environ.get("WBT_DATA_HOME")
        os.environ["WBT_DATA_HOME"] = str(self.home)

        self._orig_running_ed = editions_mod.client_looks_running
        self._orig_running_mig = migrate_mod.client_looks_running
        editions_mod.client_looks_running = lambda ed: False
        migrate_mod.client_looks_running = lambda ed: False

        self.dom_paths = make_paths("domestic")
        self.intl_paths = make_paths("international")
        self.dom_paths.root.mkdir(parents=True, exist_ok=True)
        self.intl_paths.root.mkdir(parents=True, exist_ok=True)

        self._init_db(self.dom_paths.db_path)
        self._init_db(self.intl_paths.db_path)

        # Ensure lock is released before each test
        if _migrate_lock.locked():
            try:
                _migrate_lock.release()
            except RuntimeError:
                pass

    def tearDown(self):
        if _migrate_lock.locked():
            try:
                _migrate_lock.release()
            except RuntimeError:
                pass
        editions_mod.client_looks_running = self._orig_running_ed
        migrate_mod.client_looks_running = self._orig_running_mig
        if self._old_env is None:
            os.environ.pop("WBT_DATA_HOME", None)
        else:
            os.environ["WBT_DATA_HOME"] = self._old_env
        self._tmp.cleanup()

    def _init_db(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id TEXT, title TEXT)")
        cur.execute("INSERT OR IGNORE INTO sessions (id, user_id, title) VALUES ('s1', 'u1', 'Session 1')")
        conn.commit()
        conn.close()

    def test_job_create_conflict_busy(self):
        """When _migrate_lock is acquired, api_migrate_create_job must synchronously return 409 busy."""
        self.assertTrue(_migrate_lock.acquire(blocking=False))
        try:
            body = MigrateRunBody(
                from_edition="domestic",
                to_edition="international",
                source_uid="u1",
            )
            with self.assertRaises(HTTPException) as cm:
                api_migrate_create_job(body)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail.get("code"), "busy")
        finally:
            _migrate_lock.release()

    def test_account_switch_blocked_during_migrate(self):
        """When _migrate_lock is acquired, api_switch must return 409 busy."""
        self.assertTrue(_migrate_lock.acquire(blocking=False))
        try:
            body = SwitchBody(edition="domestic", target_uid="u1")
            with self.assertRaises(HTTPException) as cm:
                api_switch(body)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail.get("code"), "busy")
        finally:
            _migrate_lock.release()

    def test_backup_restore_blocked_during_migrate(self):
        """When _migrate_lock is acquired, api_backups_restore must return 409 busy."""
        bk_path_str = create_backup(self.dom_paths, "u1", label="test_lock")
        bk_id = Path(bk_path_str).name

        self.assertTrue(_migrate_lock.acquire(blocking=False))
        try:
            body = RestoreBody(edition="domestic", backup_id=bk_id)
            with self.assertRaises(HTTPException) as cm:
                api_backups_restore(body)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail.get("code"), "busy")
        finally:
            _migrate_lock.release()

    def test_manual_backup_create_api(self):
        """POST /api/backups/create must create point-in-time snapshot and return backup_id."""
        body = CreateBackupBody(edition="domestic", target_uid="u1", label="manual_test")
        res = api_backups_create(body)
        self.assertTrue(res.get("ok"))
        self.assertIn("backup_id", res)
        self.assertEqual(res.get("edition"), "domestic")

        bk_dir = Path(res["path"])
        self.assertTrue(bk_dir.is_dir())
        self.assertTrue((bk_dir / "workbuddy.db").is_file())
        self.assertTrue((bk_dir / "manifest.json").is_file())

        # Verify busy lock protects backup creation as well
        self.assertTrue(_migrate_lock.acquire(blocking=False))
        try:
            with self.assertRaises(HTTPException) as cm:
                api_backups_create(body)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail.get("code"), "busy")
        finally:
            _migrate_lock.release()

    def test_manual_backup_client_running_safety(self):
        """POST /api/backups/create must abort with 409 client_running if client looks running."""
        migrate_mod.client_looks_running = lambda ed: True
        editions_mod.client_looks_running = lambda ed: True

        body = CreateBackupBody(edition="domestic", target_uid="u1", label="manual_running")
        with self.assertRaises(HTTPException) as cm:
            api_backups_create(body)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail.get("code"), "client_running")

    def test_list_backups_total_size(self):
        """list_backups must accurately compute total size and exclude subdirectories from file_count."""
        # 1. Create a modern manifest-based backup
        mem_file = self.dom_paths.memory_file("u1")
        mem_file.parent.mkdir(parents=True, exist_ok=True)
        mem_file.write_text("Hello Memory Profile", encoding="utf-8")

        conn_dir = self.dom_paths.connectors_user_dir("u1")
        conn_dir.mkdir(parents=True, exist_ok=True)
        (conn_dir / "mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")

        bk_path_str = create_backup(self.dom_paths, "u1", label="size_test")
        bk_dir = Path(bk_path_str)

        backups = list_backups(self.dom_paths)
        self.assertEqual(len(backups), 1)
        bk = backups[0]

        # Verify file_count does not count directory nodes
        disk_files = [p for p in bk_dir.rglob("*") if p.is_file()]
        self.assertEqual(bk["file_count"], len(disk_files))
        self.assertGreater(bk["size_bytes"], 0)

        # 2. Test legacy backup without manifest.json (meta.json only)
        legacy_dir = self.dom_paths.backup_root / "20260101000000_legacy_u1_abc123"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        sub_dir = legacy_dir / "sub"
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "file1.txt").write_text("12345", encoding="utf-8")
        (legacy_dir / "file2.txt").write_text("67890", encoding="utf-8")
        (legacy_dir / "meta.json").write_text(
            json.dumps({"backup_id": legacy_dir.name, "created_at": "2026-01-01T00:00:00", "target_uid": "u1"}),
            encoding="utf-8",
        )

        backups2 = list_backups(self.dom_paths)
        self.assertEqual(len(backups2), 2)
        legacy_bk = next(b for b in backups2 if b["backup_id"] == legacy_dir.name)
        # file_count should be 3 (file1.txt, file2.txt, meta.json) and NOT include sub_dir
        self.assertEqual(legacy_bk["file_count"], 3)
        self.assertEqual(legacy_bk["size_bytes"], sum(f.stat().st_size for f in [sub_dir / "file1.txt", legacy_dir / "file2.txt", legacy_dir / "meta.json"]))

    def test_manual_backup_unsafe_label(self):
        """POST /api/backups/create must reject unsafe label path traversal with 400 unsafe_path."""
        body = CreateBackupBody(edition="domestic", target_uid="u1", label="../../malicious")
        with self.assertRaises(HTTPException) as cm:
            api_backups_create(body)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(cm.exception.detail.get("code"), "unsafe_path")

    def test_job_create_payload_retains_items_and_locks(self):
        """api_migrate_create_job must atomically acquire lock and retain items in payload."""
        body = MigrateRunBody(
            from_edition="domestic",
            to_edition="international",
            source_uid="u1",
            target_uid="u1",
            items={"sessions": True, "skills": False},
        )
        res = api_migrate_create_job(body)
        self.assertEqual(res.get("status"), "pending")
        job_id = res.get("job_id")
        self.assertTrue(job_id)

        # Lock must be held immediately
        self.assertTrue(_migrate_lock.locked())

        # Concurrent job creation must fail with 409 busy
        with self.assertRaises(HTTPException) as cm:
            api_migrate_create_job(body)
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail.get("code"), "busy")

        # Job payload must contain the items mapping
        job_info = api_migrate_get_job(job_id)
        self.assertIsNotNone(job_info.get("payload"))
        self.assertEqual(job_info["payload"].get("items"), {"sessions": True, "skills": False})

        # Wait for worker to finish and verify lock is released
        import time
        for _ in range(50):
            time.sleep(0.05)
            if not _migrate_lock.locked():
                break
        self.assertFalse(_migrate_lock.locked())


if __name__ == "__main__":
    unittest.main()

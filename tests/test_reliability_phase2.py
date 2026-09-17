from __future__ import annotations

import hashlib
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

from core import migrate as migrate_mod
from core.editions import AppPaths, make_paths
from core.migrate import (
    create_backup,
    restore_backup,
    list_backups,
    find_reachable_blobs,
    migrate_session_content,
    migrate_shared_plugins,
    run_migrate,
)
from core.safety import BackupCorrupted, BackupNotFound, ClientRunningError


class TestReliabilityPhase2(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wbt-test-phase2-", ignore_cleanup_errors=True)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir(parents=True)
        self._old_env = os.environ.get("WBT_DATA_HOME")
        os.environ["WBT_DATA_HOME"] = str(self.home)
        self._orig_running = migrate_mod.client_looks_running
        migrate_mod.client_looks_running = lambda ed: False

        self.src_paths = make_paths("domestic")
        self.dst_paths = make_paths("international")
        self.src_paths.root.mkdir(parents=True, exist_ok=True)
        self.dst_paths.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        migrate_mod.client_looks_running = self._orig_running
        if self._old_env is None:
            os.environ.pop("WBT_DATA_HOME", None)
        else:
            os.environ["WBT_DATA_HOME"] = self._old_env
        self._tmp.cleanup()

    def _init_test_db(self, db_path: Path, rows: list) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id TEXT, title TEXT)"
        )
        for r in rows:
            cur.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)", r)
        conn.commit()
        conn.close()

    def test_sqlite_backup_and_manifest(self):
        # 1. Setup DB with WAL active
        self._init_test_db(self.src_paths.db_path, [("s1", "u1", "Session 1")])

        # Add memory and connector files
        mem_file = self.src_paths.memory_file("u1")
        mem_file.parent.mkdir(parents=True, exist_ok=True)
        mem_file.write_text("## Memory Block\nUser loves Python.", encoding="utf-8")

        conn_dir = self.src_paths.connectors_user_dir("u1")
        conn_dir.mkdir(parents=True, exist_ok=True)
        (conn_dir / "mcp.json").write_text('{"servers": {}}', encoding="utf-8")

        # 2. Create backup
        bk_path_str = create_backup(self.src_paths, "u1", label="test")
        bk_path = Path(bk_path_str)
        self.assertTrue(bk_path.is_dir())

        # 3. Verify manifest
        manifest_file = bk_path / "manifest.json"
        self.assertTrue(manifest_file.is_file())
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["target_uid"], "u1")
        self.assertEqual(manifest["edition"], "domestic")

        files = {f["rel_path"]: f for f in manifest["files"]}
        self.assertIn("workbuddy.db", files)
        self.assertIn(self.src_paths.memory_file("u1").name, files)
        self.assertIn("u1/mcp.json", files)

        # Verify backed up DB contains uncheckpointed WAL rows
        conn = sqlite3.connect(str(bk_path / "workbuddy.db"))
        cur = conn.cursor()
        cur.execute("SELECT title FROM sessions WHERE id='s1'")
        row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Session 1")

        # 4. Verify list_backups
        backups = list_backups(self.src_paths)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]["backup_id"], bk_path.name)
        self.assertEqual(backups[0]["target_uid"], "u1")

    def test_restore_backup_success_and_cleanup(self):
        self._init_test_db(self.src_paths.db_path, [("s1", "u1", "Initial")])
        bk_path_str = create_backup(self.src_paths, "u1", label="restore_test")
        tag = Path(bk_path_str).name

        # Modify active DB and create a dummy wal file
        conn = sqlite3.connect(str(self.src_paths.db_path))
        conn.execute("UPDATE sessions SET title='Modified' WHERE id='s1'")
        conn.commit()
        conn.close()
        dummy_wal = Path(str(self.src_paths.db_path) + "-wal")
        dummy_wal.write_text("stale-wal", encoding="utf-8")

        # Restore
        res = restore_backup(self.src_paths, tag)
        self.assertTrue(res["ok"])
        self.assertIn("workbuddy.db", res["restored_files"])

        # Stale wal should be cleaned up
        self.assertFalse(dummy_wal.exists())

        # DB should be restored to Initial
        conn = sqlite3.connect(str(self.src_paths.db_path))
        cur = conn.cursor()
        cur.execute("SELECT title FROM sessions WHERE id='s1'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], "Initial")

    def test_restore_corrupted_backup_rejected(self):
        self._init_test_db(self.src_paths.db_path, [("s1", "u1", "Initial")])
        bk_path_str = create_backup(self.src_paths, "u1", label="corrupt_test")
        tag = Path(bk_path_str).name

        # Tamper with the backed up DB
        bk_db = Path(bk_path_str) / "workbuddy.db"
        data = bytearray(bk_db.read_bytes())
        data[24] = (data[24] + 1) % 256
        bk_db.write_bytes(bytes(data))

        # Restore should fail closed with BackupCorrupted
        with self.assertRaises(BackupCorrupted):
            restore_backup(self.src_paths, tag)

    def test_restore_nonexistent_backup(self):
        with self.assertRaises(BackupNotFound):
            restore_backup(self.src_paths, "nonexistent_backup_id")

    def test_reachable_blobs_only(self):
        hash_a = "a" * 64
        hash_b = "b" * 64
        hash_c = "c" * 64
        hash_d = "d" * 64

        # Create blob files in source
        for h, ext in [(hash_a, ".png"), (hash_b, ".jpg"), (hash_c, ".webp"), (hash_d, ".txt")]:
            sub = self.src_paths.blobs_dir / h[:2]
            sub.mkdir(parents=True, exist_ok=True)
            (sub / f"{h}{ext}").write_text(f"content-of-{h}", encoding="utf-8")

        # s1 references hash_a in project jsonl, and hash_b in task
        proj_dir = self.src_paths.projects_dir / "proj1"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "s1.jsonl").write_text(
            json.dumps({"msg": f"image blob {hash_a}.png embedded"}), encoding="utf-8"
        )

        task_dir = self.src_paths.tasks_dir / "s1"
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "info.json").write_text(
            json.dumps({"attachment": hash_b}), encoding="utf-8"
        )

        # s2 references hash_c
        (proj_dir / "s2.jsonl").write_text(
            json.dumps({"msg": f"other blob {hash_c}"}), encoding="utf-8"
        )
        # hash_d is not referenced anywhere

        # 1. Test find_reachable_blobs for s1
        reachable_s1 = find_reachable_blobs(self.src_paths, ["s1"])
        names = {p.name for p in reachable_s1}
        self.assertIn(f"{hash_a}.png", names)
        self.assertIn(f"{hash_b}.jpg", names)
        self.assertNotIn(f"{hash_c}.webp", names)
        self.assertNotIn(f"{hash_d}.txt", names)

        # 2. Test migrate_session_content copies ONLY reachable blobs
        migrate_session_content(["s1"], self.src_paths, self.dst_paths)
        dst_blobs = [p.name for p in self.dst_paths.blobs_dir.rglob("*") if p.is_file()]
        self.assertIn(f"{hash_a}.png", dst_blobs)
        self.assertIn(f"{hash_b}.jpg", dst_blobs)
        self.assertNotIn(f"{hash_c}.webp", dst_blobs)
        self.assertNotIn(f"{hash_d}.txt", dst_blobs)

    def test_conservative_plugin_migration(self):
        p_dir = self.src_paths.plugins_dir
        p_dir.mkdir(parents=True, exist_ok=True)
        (p_dir / "installed_plugins.json").write_text(
            json.dumps({"version": 1, "plugins": {"p1": {"name": "Plugin 1"}}}),
            encoding="utf-8",
        )

        m_dir = p_dir / "marketplaces"
        m_dir.mkdir(parents=True, exist_ok=True)
        (m_dir / "market.json").write_text('{"market": true}', encoding="utf-8")

        cache_dir = p_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "cached.bin").write_text("gigabytes-of-cache", encoding="utf-8")

        data_dir = p_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "auth_tokens.json").write_text('{"token": "secret"}', encoding="utf-8")

        # Default conservative migration
        migrate_shared_plugins(self.src_paths, self.dst_paths, include_cache_and_data=False)

        dst_p = self.dst_paths.plugins_dir
        self.assertTrue((dst_p / "installed_plugins.json").exists())
        self.assertTrue((dst_p / "marketplaces" / "market.json").exists())
        self.assertFalse((dst_p / "cache").exists())
        self.assertFalse((dst_p / "data").exists())

    def test_progress_callback(self):
        self._init_test_db(self.src_paths.db_path, [("s1", "u1", "Session 1")])
        self._init_test_db(self.dst_paths.db_path, [])
        (self.dst_paths.root / "storage" / "skeleton").mkdir(parents=True, exist_ok=True)
        (self.dst_paths.root / "storage" / "skeleton" / "account-snapshot.json").write_text(
            json.dumps({"primary": {"uid": "u2", "nickname": "target"}}), encoding="utf-8"
        )

        stages_recorded = []

        def cb(stage: str, percent: int, msg: str):
            stages_recorded.append((stage, percent, msg))

        payload = {
            "from_edition": "domestic",
            "to_edition": "international",
            "source_uid": "u1",
            "target_uid": "u2",
            "items": {"sessions": True, "session_content": True},
        }

        res = run_migrate(payload, progress_callback=cb)
        self.assertTrue(res["ok"])
        self.assertTrue(len(stages_recorded) >= 3)
        stage_names = [s[0] for s in stages_recorded]
        self.assertIn("preflight", stage_names)
        self.assertIn("backup", stage_names)
        self.assertIn("completed", stage_names)
        self.assertEqual(stages_recorded[-1][1], 100)

    def test_job_and_backups_api_endpoints(self):
        try:
            from backend.app import (
                MigrateRunBody,
                RestoreBody,
                api_migrate_create_job,
                api_migrate_get_job,
                api_migrate_list_jobs,
                api_backups,
                api_backups_restore,
            )
        except ImportError:
            self.skipTest("backend dependencies not loaded in test env")
            return

        self._init_test_db(self.src_paths.db_path, [("s1", "u1", "Session 1")])
        self._init_test_db(self.dst_paths.db_path, [])
        (self.dst_paths.root / "storage" / "skeleton").mkdir(parents=True, exist_ok=True)
        (self.dst_paths.root / "storage" / "skeleton" / "account-snapshot.json").write_text(
            json.dumps({"primary": {"uid": "u2", "nickname": "target"}}), encoding="utf-8"
        )

        # 1. Create job
        body = MigrateRunBody(
            from_edition="domestic",
            to_edition="international",
            source_uid="u1",
            target_uid="u2",
            items={"sessions": True},
        )
        created = api_migrate_create_job(body)
        self.assertIn("job_id", created)
        job_id = created["job_id"]

        # 2. Poll job status
        import time
        for _ in range(50):
            job = api_migrate_get_job(job_id)
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["progress"], 100)
        self.assertIsNotNone(job["result"])

        # 3. List jobs
        jobs_res = api_migrate_list_jobs()
        self.assertTrue(any(j["job_id"] == job_id for j in jobs_res["jobs"]))

        # 4. Check backups API
        backups = api_backups(edition="international")
        self.assertTrue(len(backups["backups"]) >= 1)
        latest_bk = backups["backups"][0]["backup_id"]

        # 5. Restore backup via API
        restore_res = api_backups_restore(RestoreBody(edition="international", backup_id=latest_bk))
        self.assertTrue(restore_res["ok"])


if __name__ == "__main__":
    unittest.main()

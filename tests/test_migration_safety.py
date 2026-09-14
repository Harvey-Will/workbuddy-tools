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

UID_A = "user-alpha-0001"
UID_B = "user-beta-0002"


def snapshot_tree(root: Path) -> dict:
    out = {}
    root = Path(root)
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root)).replace("\\", "/")
            h = hashlib.sha256()
            h.update(p.read_bytes())
            out[rel] = h.hexdigest()
    return out


def _make_db(root: Path, uid_to_sessions: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    db = root / "workbuddy.db"
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS sessions ("
        "id TEXT PRIMARY KEY, user_id TEXT, title TEXT, cwd TEXT,"
        "created_at INTEGER, updated_at INTEGER, last_activity_at INTEGER)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS session_usage ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, model TEXT,"
        "input_tokens INTEGER, output_tokens INTEGER)"
    )
    for uid, sessions in uid_to_sessions.items():
        for sid in sessions:
            cur.execute(
                "INSERT OR IGNORE INTO sessions (id, user_id, title) VALUES (?,?,?)",
                (sid, uid, f"t-{sid}"),
            )
            cur.execute(
                "INSERT INTO session_usage (session_id, model, input_tokens, output_tokens)"
                " VALUES (?,?,?,?)",
                (sid, "test-model", 10, 5),
            )
    conn.commit()
    conn.close()


def _make_edition(home: Path, dir_name: str, uid_to_sessions: dict, orphan_task: bool = False) -> Path:
    root = home / dir_name
    _make_db(root, uid_to_sessions)
    (root / "storage" / "skeleton").mkdir(parents=True, exist_ok=True)
    snap = {
        "primary": {
            "uid": next(iter(uid_to_sessions)),
            "nickname": "测试账号",
            "savedAt": 1,
        }
    }
    (root / "storage" / "skeleton" / "account-snapshot.json").write_text(
        json.dumps(snap, ensure_ascii=False), encoding="utf-8"
    )
    mem = root / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    for uid in uid_to_sessions:
        (mem / f"{uid}_memory.md").write_text(
            f"# User Memory Profile\n\n## Memory Block\n\nhello {uid}\n",
            encoding="utf-8",
        )
    first_uid = next(iter(uid_to_sessions))
    sid = uid_to_sessions[first_uid][0]
    tdir = root / "tasks" / sid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "note.md").write_text("task", encoding="utf-8")
    if orphan_task:
        other = root / "tasks" / "orphan-other-task"
        other.mkdir(parents=True, exist_ok=True)
        (other / "secret.md").write_text("other", encoding="utf-8")
    return root


class SafetyCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wbt-test-", ignore_cleanup_errors=True)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir(parents=True)
        self._old_env = os.environ.get("WBT_DATA_HOME")
        os.environ["WBT_DATA_HOME"] = str(self.home)
        real_home = Path.home().resolve()
        from core.editions import data_home

        self.assertNotEqual(Path(data_home()).resolve(), real_home)
        self._saved = {}

    def tearDown(self) -> None:
        from core import accounts as accounts_mod
        from core import migrate as migrate_mod

        for mod, name in (
            (migrate_mod, "client_looks_running"),
            (accounts_mod, "client_looks_running"),
        ):
            key = (id(mod), name)
            if key in self._saved:
                setattr(mod, name, self._saved[key])
        if self._old_env is None:
            os.environ.pop("WBT_DATA_HOME", None)
        else:
            os.environ["WBT_DATA_HOME"] = self._old_env
        self._tmp.cleanup()

    def patch_running(self, mod, fn) -> None:
        key = (id(mod), "client_looks_running")
        if key not in self._saved:
            self._saved[key] = mod.client_looks_running
        mod.client_looks_running = fn

    def dual_edition(self) -> None:
        _make_edition(self.home, ".workbuddy", {UID_A: ["sess-a1", "sess-a2"]}, orphan_task=True)
        _make_edition(self.home, ".workbuddy-ai", {UID_B: ["sess-b1"]})

    def same_edition(self) -> None:
        _make_edition(self.home, ".workbuddy", {UID_A: ["sess-a1"], UID_B: ["sess-b2"]})

    def _no_client(self, migrate_mod=None, accounts_mod=None):
        if migrate_mod is not None:
            self.patch_running(migrate_mod, lambda e: False)
        if accounts_mod is not None:
            self.patch_running(accounts_mod, lambda e: False)


class TestValidateUid(SafetyCase):
    def test_rejects_traversal(self):
        from core.safety import InvalidUID, validate_uid

        bad_cases = [
            "../foo",
            "..\\foo",
            "a/b",
            "a\\b",
            ".",
            "..",
            "",
            "  ",
            "x" * 200,
            "a\x00b",
            "-lead",
            ".hid",
        ]
        for bad in bad_cases:
            with self.assertRaises(InvalidUID, msg=repr(bad)):
                validate_uid(bad)
        self.assertEqual(validate_uid(UID_A), UID_A)
        self.assertEqual(validate_uid("abc-123_XYZ.ok"), "abc-123_XYZ.ok")


class TestMigrationBlocks(SafetyCase):
    def test_same_edition_sessions_blocked_no_write(self):
        self.same_edition()
        from core import migrate as migrate_mod
        from core.safety import MigrationBlocked

        self._no_client(migrate_mod)
        before = snapshot_tree(self.home / ".workbuddy")
        with self.assertRaises(MigrationBlocked):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "domestic",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"sessions": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home / ".workbuddy"), before)

    def test_same_edition_session_content_blocked(self):
        self.same_edition()
        from core import migrate as migrate_mod
        from core.safety import MigrationBlocked

        self._no_client(migrate_mod)
        before = snapshot_tree(self.home / ".workbuddy")
        with self.assertRaises(MigrationBlocked):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "domestic",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"session_content": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home / ".workbuddy"), before)

    def test_same_edition_tasks_blocked(self):
        self.same_edition()
        from core import migrate as migrate_mod
        from core.safety import MigrationBlocked

        self._no_client(migrate_mod)
        before = snapshot_tree(self.home / ".workbuddy")
        with self.assertRaises(MigrationBlocked):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "domestic",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"tasks": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home / ".workbuddy"), before)

    def test_same_account_blocked(self):
        self.same_edition()
        from core import migrate as migrate_mod
        from core.safety import MigrationBlocked

        self._no_client(migrate_mod)
        before = snapshot_tree(self.home / ".workbuddy")
        with self.assertRaises(MigrationBlocked):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "domestic",
                    "source_uid": UID_A,
                    "target_uid": UID_A,
                    "items": {"user_memory": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home / ".workbuddy"), before)

    def test_empty_session_ids_no_task_fallback(self):
        self.dual_edition()
        from core.editions import make_paths
        from core.migrate import migrate_tasks

        source = make_paths("domestic")
        target = make_paths("international")
        n = migrate_tasks(source, target, [])
        self.assertEqual(n, 0)
        self.assertFalse((target.tasks_dir / "orphan-other-task").exists())
        self.assertFalse((target.tasks_dir / "sess-a1").exists())

    def test_traversal_uid_rejected_in_run(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import InvalidUID

        self._no_client(migrate_mod)
        before_s = snapshot_tree(self.home / ".workbuddy")
        before_t = snapshot_tree(self.home / ".workbuddy-ai")
        with self.assertRaises(InvalidUID):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": "../" + UID_A,
                    "target_uid": UID_B,
                    "items": {"user_memory": True},
                }
            )
        with self.assertRaises(InvalidUID):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": "../../foo",
                    "items": {"user_memory": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home / ".workbuddy"), before_s)
        self.assertEqual(snapshot_tree(self.home / ".workbuddy-ai"), before_t)

    def test_unknown_source_uid_blocked(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import AccountNotFound

        self._no_client(migrate_mod)
        before = snapshot_tree(self.home)
        with self.assertRaises(AccountNotFound):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": "user-missing-9999",
                    "target_uid": UID_B,
                    "items": {"user_memory": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)

    def test_unknown_target_uid_blocked(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import AccountNotFound

        self._no_client(migrate_mod)
        before = snapshot_tree(self.home)
        with self.assertRaises(AccountNotFound):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": "user-missing-9999",
                    "items": {"user_memory": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)

    def test_source_client_running_blocks(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import ClientRunningError

        self.patch_running(migrate_mod, lambda e: e == "domestic")
        before = snapshot_tree(self.home)
        with self.assertRaises(ClientRunningError):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"user_memory": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)

    def test_target_client_running_blocks(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import ClientRunningError

        self.patch_running(migrate_mod, lambda e: e == "international")
        before = snapshot_tree(self.home)
        with self.assertRaises(ClientRunningError):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"user_memory": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)

    def test_schema_missing_sessions_table_blocks(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import SchemaIncompatible

        self._no_client(migrate_mod)
        db = self.home / ".workbuddy" / "workbuddy.db"
        conn = sqlite3.connect(str(db))
        conn.execute("DROP TABLE sessions")
        conn.commit()
        conn.close()
        before = snapshot_tree(self.home)
        with self.assertRaises(SchemaIncompatible):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"sessions": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)

    def test_schema_missing_user_id_blocks(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import SchemaIncompatible

        self._no_client(migrate_mod)
        db = self.home / ".workbuddy" / "workbuddy.db"
        conn = sqlite3.connect(str(db))
        conn.execute("DROP TABLE sessions")
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT)")
        conn.commit()
        conn.close()
        before = snapshot_tree(self.home)
        with self.assertRaises(SchemaIncompatible):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"sessions": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)

    def test_run_fail_closed_empty_items(self):
        self.dual_edition()
        from core import migrate as migrate_mod

        self._no_client(migrate_mod)
        before = snapshot_tree(self.home)
        result = migrate_mod.run_migrate(
            {
                "from_edition": "domestic",
                "to_edition": "international",
                "source_uid": UID_A,
                "target_uid": UID_B,
                "items": {},
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"], [])
        self.assertEqual(snapshot_tree(self.home), before)

    def test_run_only_explicit_true_items(self):
        self.dual_edition()
        from core import migrate as migrate_mod

        self._no_client(migrate_mod)
        result = migrate_mod.run_migrate(
            {
                "from_edition": "domestic",
                "to_edition": "international",
                "source_uid": UID_A,
                "target_uid": UID_B,
                "items": {"user_memory": True, "sessions": False, "tasks": False},
            }
        )
        keys = {r["key"] for r in result["results"]}
        self.assertEqual(keys, {"user_memory"})
        conn = sqlite3.connect(str(self.home / ".workbuddy-ai" / "workbuddy.db"))
        n = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (UID_A,)).fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)

    def test_cross_edition_migration_ok_and_source_intact(self):
        self.dual_edition()
        from core import migrate as migrate_mod

        self._no_client(migrate_mod)
        result = migrate_mod.run_migrate(
            {
                "from_edition": "domestic",
                "to_edition": "international",
                "source_uid": UID_A,
                "target_uid": UID_B,
                "items": {
                    "user_memory": True,
                    "sessions": True,
                    "tasks": True,
                    "session_usage": True,
                },
            }
        )
        self.assertTrue(result["ok"], result)
        statuses = {r["key"]: r["status"] for r in result["results"]}
        self.assertEqual(statuses.get("sessions"), "success")
        self.assertEqual(statuses.get("session_usage"), "success")
        conn = sqlite3.connect(str(self.home / ".workbuddy" / "workbuddy.db"))
        n = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (UID_A,)).fetchone()[0]
        conn.close()
        self.assertEqual(n, 2)
        tconn = sqlite3.connect(str(self.home / ".workbuddy-ai" / "workbuddy.db"))
        usage_count = tconn.execute(
            "SELECT COUNT(*) FROM session_usage WHERE session_id IN (?, ?)",
            ("sess-a1", "sess-a2"),
        ).fetchone()[0]
        tconn.close()
        self.assertEqual(usage_count, 2)

    def test_malformed_target_mcp_blocked_preflight(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import WriteConflict

        self._no_client(migrate_mod)
        src_conn = self.home / ".workbuddy" / "connectors" / UID_A
        src_conn.mkdir(parents=True, exist_ok=True)
        (src_conn / "mcp.json").write_text(
            json.dumps({"mcpServers": {"a": {"command": "x"}}}), encoding="utf-8"
        )
        dst_conn = self.home / ".workbuddy-ai" / "connectors" / UID_B
        dst_conn.mkdir(parents=True, exist_ok=True)
        (dst_conn / "mcp.json").write_text("{broken", encoding="utf-8")
        before = snapshot_tree(self.home)
        with self.assertRaises(WriteConflict):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"mcp_connectors": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)
        self.assertEqual((dst_conn / "mcp.json").read_text(encoding="utf-8"), "{broken")

    def test_malformed_target_plugins_blocked_preflight(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import WriteConflict

        self._no_client(migrate_mod)
        src_plugins = self.home / ".workbuddy" / "plugins"
        src_plugins.mkdir(parents=True, exist_ok=True)
        (src_plugins / "installed_plugins.json").write_text(
            json.dumps({"version": 1, "plugins": {"p1": {"id": "p1"}}}), encoding="utf-8"
        )
        dst_plugins = self.home / ".workbuddy-ai" / "plugins"
        dst_plugins.mkdir(parents=True, exist_ok=True)
        (dst_plugins / "installed_plugins.json").write_text("{not-json", encoding="utf-8")
        before = snapshot_tree(self.home)
        with self.assertRaises(WriteConflict):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"shared_plugins": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)
        self.assertEqual(
            (dst_plugins / "installed_plugins.json").read_text(encoding="utf-8"),
            "{not-json",
        )

    def test_malformed_target_connector_states_blocked_preflight(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import WriteConflict

        self._no_client(migrate_mod)
        src_conn = self.home / ".workbuddy" / "connectors" / UID_A
        src_conn.mkdir(parents=True, exist_ok=True)
        (src_conn / "mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        (src_conn / "connector-states.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
        dst_conn = self.home / ".workbuddy-ai" / "connectors" / UID_B
        dst_conn.mkdir(parents=True, exist_ok=True)
        (dst_conn / "mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        (dst_conn / "connector-states.json").write_text("{broken", encoding="utf-8")
        before = snapshot_tree(self.home)
        with self.assertRaises(WriteConflict):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"mcp_connectors": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)
        self.assertEqual((dst_conn / "connector-states.json").read_text(encoding="utf-8"), "{broken")

    def test_malformed_source_mcp_blocked(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import WriteConflict

        self._no_client(migrate_mod)
        src_conn = self.home / ".workbuddy" / "connectors" / UID_A
        src_conn.mkdir(parents=True, exist_ok=True)
        (src_conn / "mcp.json").write_text("{bad", encoding="utf-8")
        before = snapshot_tree(self.home)
        with self.assertRaises(WriteConflict):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"mcp_connectors": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)

    def test_tasks_only_requires_sessions_columns(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import SchemaIncompatible

        self._no_client(migrate_mod)
        db = self.home / ".workbuddy" / "workbuddy.db"
        conn = sqlite3.connect(str(db))
        conn.execute("DROP TABLE sessions")
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT)")
        conn.commit()
        conn.close()
        before = snapshot_tree(self.home)
        with self.assertRaises(SchemaIncompatible):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"tasks": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)

    def test_malicious_session_id_blocked(self):
        self.dual_edition()
        from core import migrate as migrate_mod
        from core.safety import UnsafePath

        self._no_client(migrate_mod)
        db = self.home / ".workbuddy" / "workbuddy.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO sessions (id, user_id, title) VALUES (?,?,?)",
            ("../../escape", UID_A, "evil"),
        )
        conn.commit()
        conn.close()
        outside = self.home.parent / "escape-should-not-exist"
        before = snapshot_tree(self.home)
        with self.assertRaises(UnsafePath):
            migrate_mod.run_migrate(
                {
                    "from_edition": "domestic",
                    "to_edition": "international",
                    "source_uid": UID_A,
                    "target_uid": UID_B,
                    "items": {"tasks": True},
                }
            )
        self.assertEqual(snapshot_tree(self.home), before)
        self.assertFalse(outside.exists())

    def test_same_edition_plan_allows_safe_defaults(self):
        self.same_edition()
        from core import migrate as migrate_mod

        self._no_client(migrate_mod)
        plan = migrate_mod.plan_migrate("domestic", "domestic", UID_A, UID_B)
        self.assertFalse(plan["blocked"], plan.get("block_reason"))
        self.assertFalse(plan["default_items"]["sessions"])
        self.assertFalse(plan["default_items"]["tasks"])
        self.assertTrue(plan["default_items"]["user_memory"])
        self.assertIn("sessions", plan["blocked_item_keys"])

    def test_same_edition_memory_migration_allowed(self):
        self.same_edition()
        from core import migrate as migrate_mod

        self._no_client(migrate_mod)
        before_src_db = (self.home / ".workbuddy" / "workbuddy.db").read_bytes()
        result = migrate_mod.run_migrate(
            {
                "from_edition": "domestic",
                "to_edition": "domestic",
                "source_uid": UID_A,
                "target_uid": UID_B,
                "items": {"user_memory": True},
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.home / ".workbuddy" / "workbuddy.db").read_bytes(), before_src_db)


class TestSwitch(SafetyCase):
    def test_switch_client_running_blocks(self):
        self.same_edition()
        from core import accounts as accounts_mod
        from core.safety import ClientRunningError

        self.patch_running(accounts_mod, lambda e: True)
        snap = self.home / ".workbuddy" / "storage" / "skeleton" / "account-snapshot.json"
        before = snap.read_bytes()
        with self.assertRaises(ClientRunningError):
            accounts_mod.switch_account("domestic", UID_B)
        self.assertEqual(snap.read_bytes(), before)

    def test_switch_malformed_snapshot_preserved(self):
        self.same_edition()
        from core import accounts as accounts_mod
        from core.safety import WriteConflict

        self.patch_running(accounts_mod, lambda e: False)
        snap = self.home / ".workbuddy" / "storage" / "skeleton" / "account-snapshot.json"
        snap.write_text("{not-json", encoding="utf-8")
        before = snap.read_bytes()
        with self.assertRaises(WriteConflict):
            accounts_mod.switch_account("domestic", UID_B)
        self.assertEqual(snap.read_bytes(), before)

    def test_switch_happy_path(self):
        self.same_edition()
        from core import accounts as accounts_mod

        self.patch_running(accounts_mod, lambda e: False)
        result = accounts_mod.switch_account("domestic", UID_B)
        self.assertTrue(result["ok"])
        self.assertEqual(result["new_uid"], UID_B)
        data = json.loads(
            (self.home / ".workbuddy" / "storage" / "skeleton" / "account-snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(data["primary"]["uid"], UID_B)


class TestAtomicWrite(unittest.TestCase):
    def test_atomic_write_leaves_no_tmp(self):
        from core.safety import atomic_write_text

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.json"
            atomic_write_text(p, '{"ok":true}')
            self.assertEqual(p.read_text(encoding="utf-8"), '{"ok":true}')
            self.assertEqual(list(Path(td).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

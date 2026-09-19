from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.editions import make_paths
from core.safety import ClientRunningError, SchemaIncompatible
from core import sessions as sessions_mod
from backend.app import app
from fastapi.testclient import TestClient


class TestSessionsTab(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wbt-sess-test-", ignore_cleanup_errors=True)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        os.environ["WBT_DATA_HOME"] = str(self.home)

        # Setup domestic environment
        self.dom_paths = make_paths("domestic")
        self.dom_paths.root.mkdir(parents=True, exist_ok=True)
        self.dom_paths.projects_dir.mkdir(parents=True, exist_ok=True)

        # Setup international environment
        self.intl_paths = make_paths("international")
        self.intl_paths.root.mkdir(parents=True, exist_ok=True)
        self.intl_paths.projects_dir.mkdir(parents=True, exist_ok=True)

        self.uid_a = "user-alpha-1111"
        self.uid_b = "user-beta-2222"
        self.uid_intl = "user-global-3333"

        from unittest.mock import patch
        self._patch_sess = patch("core.sessions.client_looks_running", return_value=False)
        self._patch_mig = patch("core.migrate.client_looks_running", return_value=False)
        self._patch_sess.start()
        self._patch_mig.start()

        self._setup_databases()
        self._setup_accounts()
        self._setup_session_files()

    def tearDown(self) -> None:
        self._patch_sess.stop()
        self._patch_mig.stop()
        self._tmp.cleanup()

    def _setup_databases(self) -> None:
        # Domestic DB
        conn = sqlite3.connect(str(self.dom_paths.db_path))
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                custom_title TEXT,
                status TEXT,
                cwd TEXT,
                model TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                last_activity_at INTEGER,
                deleted_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS session_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER
            )
            """
        )

        now = int(time.time() * 1000)
        # Session 1 (User A)
        cur.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "sess-001",
                self.uid_a,
                "微服务架构设计",
                None,
                "completed",
                "E:\\projects\\svc",
                "claude-3-7-sonnet",
                now - 3600000,
                now - 1800000,
                now - 1800000,
                None,
            ),
        )
        # Session 2 (User A)
        cur.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "sess-002",
                self.uid_a,
                "前端组件重构",
                "重构工作流",
                "active",
                "E:\\projects\\ui",
                "deepseek-v3",
                now - 7200000,
                now - 600000,
                now - 600000,
                None,
            ),
        )
        # Session 3 (User B)
        cur.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "sess-003",
                self.uid_b,
                "数据库性能调优",
                None,
                "completed",
                "E:\\projects\\db",
                "gemini-2.5-pro",
                now - 10000000,
                now - 5000000,
                now - 5000000,
                None,
            ),
        )
        conn.commit()
        conn.close()

        # International DB
        iconn = sqlite3.connect(str(self.intl_paths.db_path))
        icur = iconn.cursor()
        icur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                custom_title TEXT,
                status TEXT,
                cwd TEXT,
                model TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                last_activity_at INTEGER,
                deleted_at INTEGER
            )
            """
        )
        icur.execute(
            """
            CREATE TABLE IF NOT EXISTS session_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER
            )
            """
        )
        icur.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "sess-intl-001",
                self.uid_intl,
                "Global Distributed Cluster",
                None,
                "completed",
                "C:\\Workspace\\global",
                "claude-3-7-sonnet",
                now - 2000000,
                now - 1000000,
                now - 1000000,
                None,
            ),
        )
        iconn.commit()
        iconn.close()

    def _setup_accounts(self) -> None:
        # Snapshots for domestic
        (self.dom_paths.storage_dir / "skeleton").mkdir(parents=True, exist_ok=True)
        snap = {
            "primary": {
                "uid": self.uid_a,
                "nickname": "AlphaDev",
                "savedAt": 1,
            }
        }
        (self.dom_paths.account_snapshot_path).write_text(json.dumps(snap), encoding="utf-8")

        # Snapshots for international
        (self.intl_paths.storage_dir / "skeleton").mkdir(parents=True, exist_ok=True)
        snap_intl = {
            "primary": {
                "uid": self.uid_intl,
                "nickname": "GlobalLead",
                "savedAt": 1,
            }
        }
        (self.intl_paths.account_snapshot_path).write_text(json.dumps(snap_intl), encoding="utf-8")

    def _setup_session_files(self) -> None:
        proj_dir = self.dom_paths.projects_dir / "workspace_proj"
        proj_dir.mkdir(parents=True, exist_ok=True)

        now_ms = int(time.time() * 1000)

        # sess-001 jsonl (contains rich messages, reasoning, tool calls, and token usages)
        # Event 1: prompt=1000, cache_read=800, out=200 -> total=1200
        # Hit rate = 800 / 1000 = 80.0%
        s1_lines = [
            json.dumps({
                "type": "message",
                "role": "user",
                "sessionId": "sess-001",
                "content": "<system-reminder>OS: win32</system-reminder><user_query>请帮我优化服务网关</user_query>",
            }),
            json.dumps({
                "type": "reasoning",
                "sessionId": "sess-001",
                "rawContent": [{"type": "text", "text": "思考如何进行限流与路由分发..."}],
            }),
            json.dumps({
                "type": "function_call",
                "sessionId": "sess-001",
                "name": "read_file",
                "callId": "call-123",
                "arguments": '{"path": "config.yaml"}',
            }),
            json.dumps({
                "type": "function_call_result",
                "sessionId": "sess-001",
                "name": "read_file",
                "callId": "call-123",
                "output": {"text": "max_connections: 10000"},
            }),
            json.dumps({
                "type": "message",
                "role": "assistant",
                "sessionId": "sess-001",
                "content": "建议采用令牌桶限流算法配合分布式网关集群。",
                "timestamp": now_ms - 500,
                "providerData": {"requestModelName": "claude-3-7-sonnet"},
                "usage": {
                    "input_tokens": 1000,
                    "cache_read_input_tokens": 800,
                    "output_tokens": 200,
                    "total_tokens": 1200,
                },
            }),
            json.dumps({
                "type": "message",
                "role": "user",
                "sessionId": "sess-001",
                "content": "好的，怎么配置超时重试？",
            }),
            json.dumps({
                "type": "message",
                "role": "assistant",
                "sessionId": "sess-001",
                "content": "可以配置指数退避重试，最大重试次数设为 3 次。",
                "timestamp": now_ms - 100,
                "providerData": {"requestModelName": "claude-3-7-sonnet"},
                "usage": {
                    "input_tokens": 1500,
                    "cache_read_input_tokens": 1200,
                    "output_tokens": 300,
                    "total_tokens": 1800,
                },
            }),
        ]
        (proj_dir / "sess-001.jsonl").write_text("\n".join(s1_lines) + "\n", encoding="utf-8")

        # sess-002 jsonl: 1 turn, input=500, cache_read=0, out=100
        s2_lines = [
            json.dumps({
                "type": "message",
                "role": "user",
                "sessionId": "sess-002",
                "content": "重构前端组件按钮样式",
            }),
            json.dumps({
                "type": "message",
                "role": "assistant",
                "sessionId": "sess-002",
                "content": "已更新 Button 组件 CSS 规范。",
                "timestamp": now_ms - 200,
                "providerData": {"requestModelName": "deepseek-v3"},
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 100,
                    "total_tokens": 600,
                },
            }),
        ]
        (proj_dir / "sess-002.jsonl").write_text("\n".join(s2_lines) + "\n", encoding="utf-8")

        # Prepare tasks directory for sess-001
        tdir = self.dom_paths.tasks_dir / "sess-001"
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "plan.md").write_text("# Gateway Architecture Plan", encoding="utf-8")

    def test_list_sessions_metrics_and_turns(self):
        sessions = sessions_mod.list_sessions("domestic")
        self.assertEqual(len(sessions), 3)

        s1 = next(s for s in sessions if s["id"] == "sess-001")
        # sess-001 has 2 user turns, 2 assistant messages = 4 total messages
        self.assertEqual(s1["turns"], 2)
        self.assertEqual(s1["message_count"], 4)
        # Token usage: ev1 (1000 in, 800 cache, 200 out) + ev2 (1500 in, 1200 cache, 300 out)
        # Total in = 2500, cache = 2000, out = 500, total = 3000
        self.assertEqual(s1["input_tokens"], 2500)
        self.assertEqual(s1["cache_read_tokens"], 2000)
        self.assertEqual(s1["output_tokens"], 500)
        self.assertEqual(s1["total_tokens"], 3000)
        # Cache hit rate = 2000 / 2500 = 80.0%
        self.assertAlmostEqual(s1["cache_hit_rate"], 0.8, places=3)
        self.assertEqual(s1["model"], "claude-3-7-sonnet")
        self.assertTrue(s1["has_jsonl"])

        # sess-002 has custom_title
        s2 = next(s for s in sessions if s["id"] == "sess-002")
        self.assertEqual(s2["title"], "重构工作流")
        self.assertEqual(s2["turns"], 1)
        self.assertEqual(s2["total_tokens"], 600)
        self.assertEqual(s2["cache_hit_rate"], 0.0)

    def test_list_sessions_filter_by_account(self):
        # Filter by uid_a
        sess_a = sessions_mod.list_sessions("domestic", uid=self.uid_a)
        self.assertEqual(len(sess_a), 2)
        self.assertTrue(all(s["user_id"] == self.uid_a for s in sess_a))

        # Filter by uid_b
        sess_b = sessions_mod.list_sessions("domestic", uid=self.uid_b)
        self.assertEqual(len(sess_b), 1)
        self.assertEqual(sess_b[0]["id"], "sess-003")

    def test_list_sessions_search_and_sort(self):
        # Search by keyword
        matched = sessions_mod.list_sessions("domestic", query="微服务")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["id"], "sess-001")

        # Sort by total tokens descending
        by_tokens = sessions_mod.list_sessions("domestic", sort_by="tokens", order="desc")
        self.assertEqual(by_tokens[0]["id"], "sess-001")
        self.assertGreaterEqual(by_tokens[0]["total_tokens"], by_tokens[1]["total_tokens"])

        # Sort by cache_hit_rate descending
        by_hit = sessions_mod.list_sessions("domestic", sort_by="cache_hit_rate", order="desc")
        self.assertEqual(by_hit[0]["id"], "sess-001")
        self.assertGreater(by_hit[0]["cache_hit_rate"], by_hit[1]["cache_hit_rate"])

    def test_clone_session_same_account_backup(self):
        # Clone sess-001 in current account (uid_a)
        res = sessions_mod.copy_sessions(
            from_edition="domestic",
            to_edition="domestic",
            session_ids=["sess-001"],
            target_uid=self.uid_a,
            clone_mode=True,
            title_suffix=" (备份副本)",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["copied"], 1)
        cloned_sid = res["session_id_map"]["sess-001"]
        self.assertNotEqual(cloned_sid, "sess-001")

        # Verify DB entry
        conn = sqlite3.connect(str(self.dom_paths.db_path))
        cur = conn.cursor()
        cur.execute("SELECT id, user_id, title FROM sessions WHERE id = ?", (cloned_sid,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], cloned_sid)
        self.assertEqual(row[1], self.uid_a)
        self.assertEqual(row[2], "微服务架构设计 (备份副本)")
        conn.close()

        # Verify rewritten jsonl
        cloned_jsonl = self.dom_paths.projects_dir / "workspace_proj" / f"{cloned_sid}.jsonl"
        self.assertTrue(cloned_jsonl.exists())
        lines = [json.loads(l) for l in cloned_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(lines[0]["sessionId"], cloned_sid)

        # Verify task cloned
        cloned_task = self.dom_paths.tasks_dir / cloned_sid / "plan.md"
        self.assertTrue(cloned_task.exists())
        self.assertEqual(cloned_task.read_text(encoding="utf-8"), "# Gateway Architecture Plan")

        # Verify original session untouched
        orig_sessions = sessions_mod.list_sessions("domestic", uid=self.uid_a)
        orig_s1 = next(s for s in orig_sessions if s["id"] == "sess-001")
        self.assertEqual(orig_s1["title"], "微服务架构设计")

    def test_copy_sessions_cross_edition(self):
        # Copy sess-001 from domestic to international under user-global-3333
        res = sessions_mod.copy_sessions(
            from_edition="domestic",
            to_edition="international",
            session_ids=["sess-001"],
            target_uid=self.uid_intl,
        )
        self.assertTrue(res["ok"])
        cloned_sid = res["session_id_map"]["sess-001"]

        # Check international DB
        iconn = sqlite3.connect(str(self.intl_paths.db_path))
        icur = iconn.cursor()
        icur.execute("SELECT id, user_id, title FROM sessions WHERE id = ?", (cloned_sid,))
        row = icur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], cloned_sid)
        self.assertEqual(row[1], self.uid_intl)
        self.assertEqual(row[2], "微服务架构设计")
        iconn.close()

        # Check international jsonl
        intl_jsonl = self.intl_paths.projects_dir / "workspace_proj" / f"{cloned_sid}.jsonl"
        self.assertTrue(intl_jsonl.exists())
        lines = [json.loads(l) for l in intl_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(lines[0]["sessionId"], cloned_sid)

    def test_export_session_markdown_clean_mode(self):
        fname, md = sessions_mod.export_session_markdown("domestic", "sess-001", mode="clean")
        self.assertTrue(fname.endswith(".md"))
        self.assertIn("微服务架构设计", fname)

        # Header check
        self.assertIn("# 微服务架构设计", md)
        self.assertIn("Token 统计", md)
        self.assertIn("Prompt 缓存命中率", md)
        self.assertIn("纯文本", md)

        # Content check: user and assistant messages present
        self.assertIn("### 👤 用户", md)
        self.assertIn("请帮我优化服务网关", md)
        self.assertIn("### 🤖 助手", md)
        self.assertIn("建议采用令牌桶限流算法配合分布式网关集群。", md)

        # System reminders and raw tool calls must be stripped
        self.assertNotIn("system-reminder", md)
        self.assertNotIn("read_file", md)
        self.assertNotIn("<details>", md)

    def test_export_session_markdown_full_mode(self):
        fname, md = sessions_mod.export_session_markdown("domestic", "sess-001", mode="full")
        self.assertIn("# 微服务架构设计", md)
        self.assertIn("完整模式", md)

        # Reasoning block present
        self.assertIn("💭 思考过程 (Reasoning)", md)
        self.assertIn("思考如何进行限流与路由分发...", md)

        # Tool call and execution output present
        self.assertIn("🛠️ 工具调用: <code>read_file</code>", md)
        self.assertIn("config.yaml", md)
        self.assertIn("max_connections: 10000", md)

    def test_batch_export_and_zip(self):
        batch = sessions_mod.export_sessions_batch("domestic", ["sess-001", "sess-002"], mode="clean")
        self.assertEqual(len(batch), 2)
        self.assertEqual(batch[0]["session_id"], "sess-001")
        self.assertEqual(batch[1]["session_id"], "sess-002")

        # Create zip
        zip_bytes = sessions_mod.create_export_zip(batch)
        self.assertGreater(len(zip_bytes), 100)

        # Decompress and verify
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            self.assertEqual(len(names), 2)
            self.assertTrue(all(n.endswith(".md") for n in names))
            content = zf.read(names[0]).decode("utf-8")
            self.assertIn("# ", content)

    def test_api_sessions_endpoints(self):
        client = TestClient(app)

        # 1. GET /api/sessions
        resp = client.get("/api/sessions?edition=domestic")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("total") >= 3)
        self.assertEqual(len(data.get("sessions")), 3)

        # 2. POST /api/sessions/copy
        copy_resp = client.post(
            "/api/sessions/copy",
            json={
                "from_edition": "domestic",
                "to_edition": "domestic",
                "session_ids": ["sess-001"],
                "target_uid": self.uid_a,
                "clone_mode": True,
                "title_suffix": " (测试克隆)",
            },
        )
        self.assertEqual(copy_resp.status_code, 200)
        cdata = copy_resp.json()
        self.assertTrue(cdata.get("ok"))
        self.assertEqual(cdata.get("copied"), 1)

        # 3. POST /api/sessions/export JSON format
        export_resp = client.post(
            "/api/sessions/export",
            json={
                "edition": "domestic",
                "session_ids": ["sess-001"],
                "mode": "clean",
                "format": "json",
            },
        )
        self.assertEqual(export_resp.status_code, 200)
        edata = export_resp.json()
        self.assertTrue(edata.get("ok"))
        self.assertEqual(edata.get("count"), 1)
        self.assertTrue(len(edata.get("zip_base64")) > 0)

    def test_copy_sessions_client_running_safety(self):
        from unittest.mock import patch
        with patch("core.sessions.client_looks_running", return_value=True):
            with self.assertRaises(ClientRunningError):
                sessions_mod.copy_sessions(
                    from_edition="domestic",
                    to_edition="domestic",
                    session_ids=["sess-001"],
                    target_uid=self.uid_a,
                )


if __name__ == "__main__":
    unittest.main()

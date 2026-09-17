from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.editions import make_paths
from core.tokens import summarize_tokens


class TestTokensSummary(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wbt-test-tokens-", ignore_cleanup_errors=True)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir(parents=True)
        self._old_env = os.environ.get("WBT_DATA_HOME")
        os.environ["WBT_DATA_HOME"] = str(self.home)

        self.paths = make_paths("domestic")
        self.paths.projects_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("WBT_DATA_HOME", None)
        else:
            os.environ["WBT_DATA_HOME"] = self._old_env
        self._tmp.cleanup()

    def test_summarize_tokens_empty(self):
        res = summarize_tokens("domestic", "7d")
        self.assertEqual(res["totals"]["total"], 0)
        self.assertEqual(res["totals"]["input"], 0)
        self.assertEqual(res["totals"]["output"], 0)
        self.assertEqual(res["totals"]["cache_read"], 0)
        self.assertEqual(res["totals"]["cache_hit_rate"], 0.0)
        self.assertEqual(res["totals"]["events"], 0)
        self.assertEqual(res["by_model"], [])
        self.assertEqual(res["by_day"], [])

    def test_summarize_tokens_with_cache_hit_rate(self):
        proj_dir = self.paths.projects_dir / "workspace1"
        proj_dir.mkdir(parents=True, exist_ok=True)
        jsonl = proj_dir / "session1.jsonl"

        import time
        now_ms = int(time.time() * 1000)

        # Event 1: input=200, cache_read=800, output=100 -> total=1100
        # cache_hit_rate = 800 / (200 + 800) = 0.8 (80%)
        ev1 = {
            "timestamp": now_ms - 1000,
            "providerData": {"requestModelName": "claude-3-7-sonnet"},
            "usage": {
                "prompt_tokens": 200,
                "cache_read_input_tokens": 800,
                "output_tokens": 100,
                "total_tokens": 1100,
            },
        }
        # Event 2: input=500, cache_read=0, output=200 -> total=700
        # for gemini: cache_hit_rate = 0.0
        ev2 = {
            "timestamp": now_ms - 500,
            "providerData": {"requestModelName": "gemini-2.5-pro"},
            "usage": {
                "input_tokens": 500,
                "output_tokens": 200,
                "total_tokens": 700,
            },
        }

        jsonl.write_text(json.dumps(ev1) + "\n" + json.dumps(ev2) + "\n", encoding="utf-8")

        res = summarize_tokens("domestic", "today")
        t = res["totals"]
        self.assertEqual(t["total"], 1800)
        self.assertEqual(t["input"], 1500)
        self.assertEqual(t["output"], 300)
        self.assertEqual(t["cache_read"], 800)
        # Total prompt = 1500. Hit rate = 800 / 1500 = 0.5333
        self.assertAlmostEqual(t["cache_hit_rate"], 800 / 1500, places=3)
        self.assertEqual(t["events"], 2)

        by_m = {m["model"]: m for m in res["by_model"]}
        self.assertIn("claude-3-7-sonnet", by_m)
        self.assertIn("gemini-2.5-pro", by_m)

        claude = by_m["claude-3-7-sonnet"]
        self.assertEqual(claude["input"], 1000)
        self.assertEqual(claude["output"], 100)
        self.assertAlmostEqual(claude["cache_hit_rate"], 800 / 1000, places=3)
        self.assertAlmostEqual(claude["ratio"], 1100 / 1800, places=3)
        self.assertEqual(claude["percent"], round((1100 / 1800) * 100, 1))

        gemini = by_m["gemini-2.5-pro"]
        self.assertEqual(gemini["input"], 500)
        self.assertEqual(gemini["output"], 200)
        self.assertEqual(gemini["cache_hit_rate"], 0.0)
        self.assertAlmostEqual(gemini["ratio"], 700 / 1800, places=3)

        self.assertEqual(len(res["by_day"]), 1)
        day_entry = res["by_day"][0]
        self.assertEqual(day_entry["total"], 1800)
        self.assertEqual(day_entry["input"], 1500)
        self.assertEqual(day_entry["output"], 300)
        self.assertEqual(day_entry["cache_read"], 800)
        self.assertAlmostEqual(day_entry["cache_hit_rate"], 800 / 1500, places=3)

    def test_workbuddy_native_cache_hit_rate(self):
        # WorkBuddy log format: input_tokens already includes cache_read_input_tokens
        proj_dir = self.paths.projects_dir / "workspace_wb"
        proj_dir.mkdir(parents=True, exist_ok=True)
        jsonl = proj_dir / "session_wb.jsonl"

        import time
        now_ms = int(time.time() * 1000)
        # Real WorkBuddy sample: input_tokens=56914, cache_read_input_tokens=54464, output=2576, total=59490
        # Hit rate = 54464 / 56914 = 95.69% (>= 90% 高效命中)
        ev = {
            "timestamp": now_ms - 300,
            "providerData": {"requestModelName": "deepseek-v3"},
            "usage": {
                "input_tokens": 56914,
                "output_tokens": 2576,
                "total_tokens": 59490,
                "cache_read_input_tokens": 54464,
            },
        }
        jsonl.write_text(json.dumps(ev) + "\n", encoding="utf-8")

        res = summarize_tokens("domestic", "today")
        t = res["totals"]
        self.assertEqual(t["input"], 56914)
        self.assertEqual(t["output"], 2576)
        self.assertEqual(t["total"], 59490)
        self.assertEqual(t["cache_read"], 54464)
        # Hit rate must be 54464 / 56914 ≈ 0.957, NOT 54464 / (56914 + 54464) ≈ 0.489
        self.assertAlmostEqual(t["cache_hit_rate"], 54464 / 56914, places=3)
        self.assertGreaterEqual(t["cache_hit_rate"], 0.9)

    def test_total_tokens_computed_with_cache_read(self):
        proj_dir = self.paths.projects_dir / "workspace2"
        proj_dir.mkdir(parents=True, exist_ok=True)
        jsonl = proj_dir / "session2.jsonl"

        import time
        now_ms = int(time.time() * 1000)

        # Event with total_tokens omitted (0): input=150, cache=850, output=100
        # total must include cache_read: 150 + 100 + 850 = 1100
        ev = {
            "timestamp": now_ms - 200,
            "providerData": {"requestModelName": "claude-3-5-sonnet"},
            "usage": {
                "input_tokens": 150,
                "cache_read_input_tokens": 850,
                "output_tokens": 100,
                "total_tokens": 0,
            },
        }
        jsonl.write_text(json.dumps(ev) + "\n", encoding="utf-8")

        res = summarize_tokens("domestic", "24h")
        self.assertEqual(res["totals"]["total"], 1100)
        self.assertEqual(res["totals"]["cache_read"], 850)
        self.assertAlmostEqual(res["totals"]["cache_hit_rate"], 850 / 1000, places=3)

    def test_all_ranges(self):
        for r in ("today", "24h", "7d", "30d", "90d"):
            res = summarize_tokens("domestic", r)
            self.assertIn("range", res)
            self.assertEqual(res["range"]["key"], r)
            self.assertIn("totals", res)
            self.assertIn("by_model", res)
            self.assertIn("by_day", res)


if __name__ == "__main__":
    unittest.main()

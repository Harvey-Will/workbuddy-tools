"""Unit tests for display-name resolution (synthetic data only)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.accounts import fallback_display_name, resolve_display_name  # noqa: E402
from core.editions import AppPaths  # noqa: E402


class DisplayNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wbt-name-"))
        self.paths = AppPaths(edition="domestic", root=self.tmp / "data-root")
        (self.paths.storage_dir / "skeleton").mkdir(parents=True, exist_ok=True)
        self.paths.tools_meta_dir.mkdir(parents=True, exist_ok=True)

    def test_fallback_never_empty_and_distinguishable(self) -> None:
        uid_a = "aaaaaaaa-1111-2222-3333-444444444444"
        uid_b = "bbbbbbbb-1111-2222-3333-444444444444"
        name_a = fallback_display_name(self.paths, uid_a)
        name_b = fallback_display_name(self.paths, uid_b)
        self.assertTrue(name_a.strip())
        self.assertNotIn("未命名", name_a)
        self.assertNotEqual(name_a, name_b)
        self.assertIn("aaaaaaaa", name_a)
        self.assertIn(self.paths.short, name_a)

    def test_snapshot_nickname_only_for_matching_uid(self) -> None:
        uid = "cccccccc-0000-0000-0000-000000000000"
        other = "dddddddd-0000-0000-0000-000000000000"
        self.paths.account_snapshot_path.write_text(
            json.dumps({"primary": {"uid": uid, "nickname": "DemoUser"}}),
            encoding="utf-8",
        )
        name, source = resolve_display_name(
            self.paths, uid, current_uid=uid, snap_nickname="DemoUser"
        )
        self.assertEqual(name, "DemoUser")
        self.assertEqual(source, "snapshot")

        name2, source2 = resolve_display_name(self.paths, other)
        self.assertNotEqual(name2, "DemoUser")
        self.assertEqual(source2, "fallback")
        self.assertNotIn("未命名", name2)

    def test_profile_label_overrides_cache(self) -> None:
        uid = "eeeeeeee-0000-0000-0000-000000000000"
        (self.paths.tools_meta_dir / "nicknames.json").write_text(
            json.dumps({uid: "CachedName"}), encoding="utf-8"
        )
        (self.paths.tools_meta_dir / "profiles.json").write_text(
            json.dumps([{"uid": uid, "label": "CustomLabel"}]), encoding="utf-8"
        )
        name, source = resolve_display_name(self.paths, uid)
        self.assertEqual(name, "CustomLabel")
        self.assertEqual(source, "profile")


if __name__ == "__main__":
    unittest.main()

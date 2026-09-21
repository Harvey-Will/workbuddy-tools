"""Unit tests for v0.1.5.1: Migration Auto-Refresh & Client Detection."""

import unittest
from unittest.mock import patch

from backend.app import APP_VERSION, api_migrate_plan, api_system_version
from core import migrate as migrate_mod
from tests.test_migration_safety import SafetyCase, UID_A, UID_B


class TestMigrateAutoRefresh(SafetyCase):
    def test_version_bump(self):
        self.assertEqual(APP_VERSION, "0.1.5.1")
        sys_ver = api_system_version()
        self.assertEqual(sys_ver["version"], "0.1.5.1")

    def test_client_running_blocks_and_unblocks(self):
        self.same_edition()

        # Case 1: Client is running -> client_running=True, blocked=True
        with patch("core.migrate.client_looks_running", return_value=True):
            plan_running = migrate_mod.plan_migrate("domestic", "domestic", UID_A, UID_B)
            self.assertTrue(plan_running["client_running"])
            self.assertTrue(plan_running["blocked"])
            self.assertIn("客户端正在运行", plan_running["block_reason"])

        # Case 2: Client has closed -> client_running=False, blocked=False -> enters migratable mode
        with patch("core.migrate.client_looks_running", return_value=False):
            plan_closed = migrate_mod.plan_migrate("domestic", "domestic", UID_A, UID_B)
            self.assertFalse(plan_closed["client_running"])
            self.assertFalse(plan_closed["blocked"])
            self.assertFalse(plan_closed["block_reason"])
            self.assertTrue(plan_closed["same_edition"])
            self.assertFalse(plan_closed["same_account"])
            self.assertTrue(plan_closed["default_items"]["sessions"])

    def test_same_account_blocked(self):
        self.same_edition()
        with patch("core.migrate.client_looks_running", return_value=False):
            plan = migrate_mod.plan_migrate("domestic", "domestic", UID_A, UID_A)
            self.assertFalse(plan["client_running"])
            self.assertTrue(plan["blocked"])
            self.assertIn("源账号和目标账号相同", plan["block_reason"])

    def test_api_migrate_plan_endpoint(self):
        self.same_edition()
        with patch("core.migrate.client_looks_running", return_value=False):
            res = api_migrate_plan(
                from_edition="domestic",
                to_edition="domestic",
                source_uid=UID_A,
                target_uid=UID_B,
            )
            self.assertIn("client_running", res)
            self.assertFalse(res["client_running"])
            self.assertFalse(res["blocked"])
            self.assertIn("items", res)
            self.assertIn("default_items", res)


if __name__ == "__main__":
    unittest.main()

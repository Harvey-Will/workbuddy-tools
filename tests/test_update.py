from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.update import parse_semver, is_newer_version, check_github_update


class TestUpdateModule(unittest.TestCase):
    def test_parse_semver(self):
        self.assertEqual(parse_semver("0.1.3"), (0, 1, 3))
        self.assertEqual(parse_semver("v0.1.3"), (0, 1, 3))
        self.assertEqual(parse_semver("v1.2.3-beta"), (1, 2, 3))
        self.assertEqual(parse_semver("10.2"), (10, 2, 0))
        self.assertEqual(parse_semver(""), (0, 0, 0))
        self.assertEqual(parse_semver(None), (0, 0, 0))

    def test_is_newer_version(self):
        self.assertTrue(is_newer_version("0.1.3", "0.1.4"))
        self.assertTrue(is_newer_version("0.1.3", "v0.2.0"))
        self.assertTrue(is_newer_version("0.1.3", "1.0.0"))
        self.assertFalse(is_newer_version("0.1.3", "0.1.3"))
        self.assertFalse(is_newer_version("0.1.3", "0.1.2"))
        self.assertFalse(is_newer_version("0.1.3", "v0.1.3"))
        self.assertFalse(is_newer_version("0.1.3", ""))

    @patch("urllib.request.urlopen")
    def test_check_github_update_api_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "tag_name": "v0.2.0",
            "name": "WorkBuddy Tools v0.2.0",
            "body": "重大更新日志",
            "published_at": "2026-09-17T12:00:00Z",
            "html_url": "https://github.com/Harvey-Will/workbuddy-tools/releases/tag/v0.2.0",
            "assets": [{"browser_download_url": "https://github.com/Harvey-Will/workbuddy-tools/releases/download/v0.2.0/setup.exe"}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = check_github_update(current_version="0.1.3")
        self.assertTrue(res["has_update"])
        self.assertEqual(res["latest_version"], "0.2.0")
        self.assertEqual(res["release_name"], "WorkBuddy Tools v0.2.0")
        self.assertIn("重大更新日志", res["release_notes"])
        self.assertEqual(res["download_url"], "https://github.com/Harvey-Will/workbuddy-tools/releases/download/v0.2.0/setup.exe")

    @patch("urllib.request.urlopen")
    def test_check_github_update_fallback_raw_config(self, mock_urlopen):
        # 1st call fails (HTTP 403 API rate limit)
        # 2nd call succeeds (raw tauri.conf.json)
        mock_resp2 = MagicMock()
        mock_resp2.status = 200
        mock_resp2.read.return_value = json.dumps({"version": "0.1.4"}).encode("utf-8")
        mock_resp2.__enter__.return_value = mock_resp2

        mock_urlopen.side_effect = [Exception("HTTP Error 403: rate limit exceeded"), mock_resp2]

        res = check_github_update(current_version="0.1.3")
        self.assertTrue(res["has_update"])
        self.assertEqual(res["latest_version"], "0.1.4")
        self.assertIsNone(res["error"])

    @patch("urllib.request.urlopen")
    def test_check_github_update_fallback_same_version(self, mock_urlopen):
        mock_resp2 = MagicMock()
        mock_resp2.status = 200
        mock_resp2.read.return_value = json.dumps({"version": "0.1.3"}).encode("utf-8")
        mock_resp2.__enter__.return_value = mock_resp2

        mock_urlopen.side_effect = [Exception("HTTP Error 403: rate limit exceeded"), mock_resp2]

        res = check_github_update(current_version="0.1.3")
        self.assertFalse(res["has_update"])
        self.assertEqual(res["latest_version"], "0.1.3")
        self.assertIn("一致", res["release_notes"])
        self.assertIsNone(res["error"])

    @patch("urllib.request.urlopen")
    def test_check_github_update_offline_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network unreachable")

        res = check_github_update(current_version="0.1.3")
        self.assertFalse(res["has_update"])
        self.assertIsNotNone(res["error"])
        self.assertEqual(res["latest_version"], "0.1.3")

    def test_backend_system_endpoints(self):
        from backend.app import api_system_version, api_open_url, OpenUrlBody, HTTPException, __version__
        v = api_system_version()
        self.assertEqual(v["version"], __version__)
        self.assertEqual(v["version"], "0.1.5.1")
        self.assertIn("github.com", v["repo_url"])

        with patch("webbrowser.open") as mock_open:
            r = api_open_url(OpenUrlBody(url="https://github.com/Harvey-Will/workbuddy-tools"))
            self.assertTrue(r["ok"])
            mock_open.assert_called_once_with("https://github.com/Harvey-Will/workbuddy-tools")

        # Invalid URL should raise 400
        with self.assertRaises(HTTPException):
            api_open_url(OpenUrlBody(url="file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()

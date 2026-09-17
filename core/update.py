from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

DEFAULT_REPO = "Harvey-Will/workbuddy-tools"


def parse_semver(v: str) -> Tuple[int, int, int]:
    """Parse a semver string like '0.1.3', 'v0.1.3', '0.2.0-beta' into (major, minor, patch)."""
    if not v or not isinstance(v, str):
        return (0, 0, 0)
    cleaned = v.strip().lstrip("vV")
    nums = [int(p) for p in re.findall(r"\d+", cleaned)]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])  # type: ignore[return-value]


def is_newer_version(current: str, candidate: str) -> bool:
    """Return True if candidate is strictly greater than current version."""
    c_ver = parse_semver(current)
    cand_ver = parse_semver(candidate)
    return cand_ver > c_ver


def check_github_update(
    current_version: str,
    repo: str = DEFAULT_REPO,
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """Check for new release on GitHub.

    Handles GitHub API rate-limits gracefully by falling back to raw repo config.
    """
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    raw_conf_url = f"https://raw.githubusercontent.com/{repo}/main/src-tauri/tauri.conf.json"
    releases_web_url = f"https://github.com/{repo}/releases"

    headers = {
        "User-Agent": f"WorkBuddy-Tools/{current_version}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Strategy 1: Try GitHub Releases API
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                tag = data.get("tag_name") or data.get("name") or ""
                clean_ver = tag.strip().lstrip("vV")
                has_update = is_newer_version(current_version, clean_ver)

                html_url = data.get("html_url") or releases_web_url
                download_url = html_url
                assets = data.get("assets", [])
                if assets and isinstance(assets, list):
                    for a in assets:
                        if isinstance(a, dict) and a.get("browser_download_url"):
                            download_url = a["browser_download_url"]
                            break

                return {
                    "current_version": current_version,
                    "latest_version": clean_ver or current_version,
                    "has_update": has_update,
                    "release_name": data.get("name") or tag or f"v{clean_ver}",
                    "release_notes": data.get("body") or "暂无版本更新说明。",
                    "published_at": data.get("published_at", ""),
                    "html_url": html_url,
                    "download_url": download_url,
                    "error": None,
                }
    except Exception:
        pass

    # Strategy 2: Fallback to raw tauri.conf.json to check version if API rate limited
    try:
        req = urllib.request.Request(raw_conf_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_data = json.loads(resp.read().decode("utf-8"))
                remote_ver = (raw_data.get("version") or "").strip().lstrip("vV")
                if remote_ver:
                    has_update = is_newer_version(current_version, remote_ver)
                    return {
                        "current_version": current_version,
                        "latest_version": remote_ver,
                        "has_update": has_update,
                        "release_name": f"v{remote_ver}",
                        "release_notes": (
                            "检测到远程仓库更新版本，详情请访问 GitHub Releases 页面。"
                            if has_update
                            else "当前版本与远程仓库最新版本一致。"
                        ),
                        "published_at": "",
                        "html_url": releases_web_url,
                        "download_url": f"{releases_web_url}/tag/v{remote_ver}" if has_update else releases_web_url,
                        "error": None,
                    }
    except Exception:
        pass

    # Strategy 3: Both failed (network offline or unreachable)
    return {
        "current_version": current_version,
        "latest_version": current_version,
        "has_update": False,
        "release_name": f"v{current_version}",
        "release_notes": "",
        "published_at": "",
        "html_url": releases_web_url,
        "download_url": releases_web_url,
        "error": "检查更新失败，可能网络离线或 GitHub 请求达到限制。您可以直接访问 GitHub Releases 页面查看。",
    }

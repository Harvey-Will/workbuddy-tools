from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestClientProcessClassification(unittest.TestCase):
    """Real argv samples captured on macOS 26 (WorkBuddy 5.7.6).

    pgrep -f matches any argv containing the name, so the classifier must tell
    the client's main UI process apart from Electron helpers, the crashpad
    handler, sandbox workers, daemon children, the prewarmed CLI pool, and this
    tool's own bundle. Getting this wrong either blocks backup/migration while
    the client is closed (false positive) or lets a migration run while the
    client is live (false negative).
    """

    CLIENT = "/Applications/WorkBuddy.app/Contents/MacOS/Electron"

    def _classify(self, cmdline: str, name: str = "WorkBuddy") -> bool:
        from core.editions import _looks_like_client_process

        return _looks_like_client_process(cmdline, name)

    def test_main_ui_process_counts_as_running(self):
        self.assertTrue(self._classify(self.CLIENT))
        # WorkBuddyAI uses the same bundle layout under a different name.
        self.assertTrue(
            self._classify("/Applications/WorkBuddyAI.app/Contents/MacOS/Electron", "WorkBuddyAI")
        )

    def test_electron_helpers_do_not_count(self):
        samples = [
            "/Applications/WorkBuddy.app/Contents/Frameworks/WorkBuddy Helper.app/Contents/MacOS/WorkBuddy Helper --type=utility",
            "/Applications/WorkBuddy.app/Contents/Frameworks/WorkBuddy Helper (GPU).app/Contents/MacOS/WorkBuddy Helper (GPU) --type=gpu-process",
            "/Applications/WorkBuddy.app/Contents/Frameworks/WorkBuddy Helper (Renderer).app/Contents/MacOS/WorkBuddy Helper (Renderer) --type=renderer",
            "/Applications/WorkBuddy.app/Contents/Frameworks/Electron Framework.framework/Helpers/chrome_crashpad_handler --no-rate-limit",
        ]
        for s in samples:
            with self.subTest(sample=s[:60]):
                self.assertFalse(self._classify(s))

    def test_daemon_and_sandbox_children_do_not_count(self):
        samples = [
            self.CLIENT + " /Applications/WorkBuddy.app/Contents/Resources/app.asar/main/daemon-app-server-entry.js --stdio",
            self.CLIENT + " /Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy --prewarm --prewarm-id wb-pool-123",
            "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/vendor/sandbox/5.7.10/sandbox-center --config {}",
            "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/vendor/sandbox/5.7.10/sandbox-cli-gc --workspace /x",
            "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/vendor/sandbox/5.7.10/betterleaks serve --config /x",
        ]
        for s in samples:
            with self.subTest(sample=s[-60:]):
                self.assertFalse(self._classify(s))

    def test_own_bundle_never_matches(self):
        samples = [
            "/Volumes/Data/workbuddy-tools/dist-deliverable/WorkBuddy Tools.app/Contents/MacOS/workbuddy-tools",
            "/Applications/WorkBuddy Tools.app/Contents/MacOS/workbuddy-tools",
        ]
        for s in samples:
            with self.subTest(sample=s[-60:]):
                self.assertFalse(self._classify(s))

    def test_unrelated_processes_do_not_count(self):
        # A path that merely mentions the name outside a bundle must not match.
        self.assertFalse(self._classify("/tmp/WorkBuddy notes.txt"))
        self.assertFalse(self._classify("/usr/bin/vim /Users/x/WorkBuddy.md"))


class TestPgrepLineParsing(unittest.TestCase):
    def test_pid_prefix_is_stripped(self):
        from core.editions import _pgrep_lines
        import core.editions as ed

        real_run = ed.subprocess.run

        class R:
            returncode = 0
            stdout = "123 /Applications/WorkBuddy.app/Contents/MacOS/Electron\n456 /a b/c\n"
            stderr = ""

        ed.subprocess.run = lambda *a, **k: R()
        try:
            lines = _pgrep_lines("/usr/bin/pgrep", "WorkBuddy")
        finally:
            ed.subprocess.run = real_run

        self.assertEqual(lines, ["/Applications/WorkBuddy.app/Contents/MacOS/Electron", "/a b/c"])


if __name__ == "__main__":
    unittest.main()

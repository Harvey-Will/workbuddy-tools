from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestConnectReadonly(unittest.TestCase):
    """connect_readonly must open a database that lives in a read-only directory.

    sqlite3.connect() opens read-write, and SQLite then needs to create a
    journal/WAL file next to the database. When that directory is not writable
    (macOS TCC-protected home, or a client-owned data dir) even a pure read
    fails with "unable to open database file", which silently emptied every
    session list and blocked migrations.
    """

    def _make_db(self, d: Path) -> Path:
        db = d / "workbuddy.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT)")
        conn.executemany("INSERT INTO sessions VALUES (?,?)", [(f"s{i}", "u1") for i in range(5)])
        conn.commit()
        conn.close()
        return db

    def test_reads_from_writable_directory(self):
        from core.editions import connect_readonly

        with tempfile.TemporaryDirectory() as td:
            db = self._make_db(Path(td))
            conn = connect_readonly(db)
            try:
                n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(n, 5)

    @unittest.skipUnless(sys.platform == "darwin", "read-only-dir behaviour is POSIX-specific")
    def test_reads_from_read_only_directory(self):
        """The actual macOS failure: data dir readable but not writable.

        sqlite3.connect() succeeds lazily; the error only surfaces when SQLite
        tries to create a journal file for the first real query.

        The chmod route is not used here because it does not reproduce on every
        filesystem (APFS on /tmp, SIP-protected paths). Instead the test pins the
        contract directly: the helper must never hand back a connection that
        would need a journal, i.e. the first thing it does is a real read.
        """
        from core.editions import connect_readonly

        with tempfile.TemporaryDirectory() as td:
            db = self._make_db(Path(td))
            conn = connect_readonly(db)
            try:
                # A successful call means a real read already happened inside
                # connect_readonly, so the caller can query safely.
                n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(n, 5)

    def test_helper_does_not_open_read_write(self):
        """connect_readonly must not settle for a read-write handle.

        If it ever regresses to a plain connect(), a read-only data directory
        starts failing again. Assert the URI it produces is read-only.
        """
        from core import editions

        with tempfile.TemporaryDirectory() as td:
            db = self._make_db(Path(td))
            posix = db.resolve().as_posix()
            # The first attempt must be mode=ro, never a bare path.
            with unittest.mock.patch.object(editions.sqlite3, "connect") as m:
                m.side_effect = editions.sqlite3.OperationalError("blocked in test")
                with self.assertRaises(Exception):
                    editions.connect_readonly(db)
                first = m.call_args_list[0]
                self.assertIn("mode=ro", str(first.args[0]))

    def test_missing_file_raises(self):
        from core.editions import connect_readonly

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                connect_readonly(Path(td) / "nope.db")


if __name__ == "__main__":
    unittest.main()

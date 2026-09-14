from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestValidateUidBoundary(unittest.TestCase):
    def test_boundary(self):
        from core.safety import InvalidUID, validate_uid

        self.assertEqual(validate_uid("a"), "a")
        self.assertEqual(validate_uid("A1._-z"), "A1._-z")
        with self.assertRaises(InvalidUID):
            validate_uid("-leading")
        with self.assertRaises(InvalidUID):
            validate_uid(".hidden")


if __name__ == "__main__":
    unittest.main()

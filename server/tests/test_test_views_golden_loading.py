from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from test_views import load_reference_golden_parts


class TestGoldenLoading(unittest.TestCase):
    def test_all_uses_managed_subset_merge(self):
        parts, require_golden_entry, source = load_reference_golden_parts("all", None)
        self.assertFalse(require_golden_entry)
        self.assertIn("baseline", source)
        self.assertIn("real_priority", source)
        self.assertIn("u_channel_assembly", parts)
        self.assertIn("202500521_EOAT Versteifung_V1.0", parts)

    def test_real_uses_real_priority_subset(self):
        parts, require_golden_entry, source = load_reference_golden_parts("real", None)
        self.assertFalse(require_golden_entry)
        self.assertIn("real_priority", source)
        self.assertIn("202500521_EOAT Versteifung_V1.0", parts)

    def test_explicit_golden_stays_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            golden_path = Path(tmp) / "golden.json"
            golden_path.write_text(
                json.dumps({"parts": {"demo": {"foo": "bar"}}}),
                encoding="utf-8",
            )
            parts, require_golden_entry, source = load_reference_golden_parts("all", golden_path)
        self.assertTrue(require_golden_entry)
        self.assertEqual(source, str(golden_path))
        self.assertEqual(parts["demo"]["foo"], "bar")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python
"""Unit tests for export metadata normalization/validation."""

import unittest

from main import MetadataValidationError, build_metadata


class MetadataProfileTests(unittest.TestCase):
    def test_defaults_use_norm_profile(self) -> None:
        meta = build_metadata(None, None, None, None, None)
        self.assertEqual(meta["title"], "Bauteilzeichnung")
        self.assertEqual(meta["drawing_no"], "DF-0001")
        self.assertEqual(meta["revision"], "A")
        self.assertEqual(meta["unit"], "mm")
        self.assertEqual(meta["sheet"], "auto")
        self.assertEqual(meta["scale"], "auto")
        self.assertEqual(meta["standard"], "DIN EN ISO 128/129-1")
        self.assertEqual(meta["projection"], "1. Winkel (DIN EN ISO 5456-2)")
        self.assertEqual(meta["general_tolerance"], "DIN ISO 2768-mK")
        self.assertEqual(meta["views"], ["Top", "Front", "Left", "Iso"])

    def test_accepts_supported_aliases(self) -> None:
        meta = build_metadata(
            "Teil 1",
            "DF-1001",
            "B2",
            "Max Mustermann",
            "Drawform GmbH",
            scale=" 1:2 ",
            standard="iso 128/129-1",
            projection="first_angle",
            general_tolerance="din iso 2768-mk",
            unit="MM",
            sheet="a3",
        )
        self.assertEqual(meta["scale"], "1:2")
        self.assertEqual(meta["standard"], "DIN EN ISO 128/129-1")
        self.assertEqual(meta["projection"], "1. Winkel (DIN EN ISO 5456-2)")
        self.assertEqual(meta["general_tolerance"], "DIN ISO 2768-mK")
        self.assertEqual(meta["unit"], "mm")
        self.assertEqual(meta["sheet"], "A3")
        meta_a2 = build_metadata(None, None, None, None, None, sheet="a2")
        self.assertEqual(meta_a2["sheet"], "A2")
        meta_auto = build_metadata(None, None, None, None, None, sheet="AUTO")
        self.assertEqual(meta_auto["sheet"], "auto")

    def test_rejects_invalid_scale(self) -> None:
        with self.assertRaises(MetadataValidationError):
            build_metadata(None, None, None, None, None, scale="3:7")

    def test_rejects_invalid_projection(self) -> None:
        with self.assertRaises(MetadataValidationError):
            build_metadata(None, None, None, None, None, projection="third_angle")

    def test_rejects_invalid_drawing_no(self) -> None:
        with self.assertRaises(MetadataValidationError):
            build_metadata(None, "DF 1001", None, None, None)

    def test_rejects_invalid_tolerance(self) -> None:
        with self.assertRaises(MetadataValidationError):
            build_metadata(None, None, None, None, None, general_tolerance="DIN ISO 2768-xZ")

    def test_rejects_invalid_unit_and_sheet(self) -> None:
        with self.assertRaises(MetadataValidationError):
            build_metadata(None, None, None, None, None, unit="inch")
        with self.assertRaises(MetadataValidationError):
            build_metadata(None, None, None, None, None, sheet="A4")


if __name__ == "__main__":
    unittest.main()

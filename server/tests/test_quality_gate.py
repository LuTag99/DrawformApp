from __future__ import annotations

import unittest

from run_quality_gate import build_steps


class QualityGateStepTests(unittest.TestCase):
    def test_fast_mode_uses_only_unit_discovery(self) -> None:
        steps = build_steps(
            "python",
            mode="fast",
            update_golden=False,
            stability_runs=2,
        )

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0][0], "Python unit discovery")
        self.assertEqual(steps[0][1], ["python", "-m", "unittest", "discover"])

    def test_full_mode_includes_render_regression_steps(self) -> None:
        steps = build_steps(
            "python",
            mode="full",
            update_golden=True,
            stability_runs=3,
        )
        labels = [label for label, _command, _cwd in steps]

        self.assertIn("Python unit discovery", labels)
        self.assertIn("Update golden baseline", labels)
        self.assertIn("View regression", labels)
        self.assertIn("View stability loop", labels)
        self.assertIn("Generate PDF review checklist", labels)
        stability_command = next(command for label, command, _cwd in steps if label == "View stability loop")
        self.assertEqual(stability_command[-1], "3")


if __name__ == "__main__":
    unittest.main()

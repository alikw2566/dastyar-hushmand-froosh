import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "run_load.py"
SPEC = importlib.util.spec_from_file_location("run_load", MODULE_PATH)
run_load = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(run_load)


class LoadRunnerTests(unittest.TestCase):
    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(run_load.percentile([1, 2, 3, 4], 95), 4)

    def test_health_dry_run_is_valid_without_token(self):
        args = run_load.parse_args(
            ["--scenario", "health", "--requests", "1", "--dry-run"]
        )
        run_load.validate_args(args)

    def test_retry_storm_requires_explicit_mutation_flag(self):
        args = run_load.parse_args(
            ["--scenario", "retry-storm", "--requests", "1", "--token", "x"]
        )
        with self.assertRaises(ValueError):
            run_load.validate_args(args)

    def test_non_positive_rate_is_rejected(self):
        args = run_load.parse_args(
            ["--scenario", "health", "--requests", "1", "--rate-per-second", "0"]
        )
        with self.assertRaises(ValueError):
            run_load.validate_args(args)


if __name__ == "__main__":
    unittest.main()

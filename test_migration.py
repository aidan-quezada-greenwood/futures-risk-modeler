"""CSV schema migration should preserve trade data and back it up first."""

import os
from pathlib import Path
import shutil
import tempfile
import unittest

import pandas as pd

from modules.migration import ALL_COLUMNS, migrate_trades_schema


class MigrationTests(unittest.TestCase):
    def test_migration_retains_original_values_and_creates_backup(self):
        original_dir = os.getcwd()
        sample = Path(__file__).resolve().parents[1] / "data" / "sample_trades.csv"
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                Path("data").mkdir()
                shutil.copyfile(sample, Path("data/trades.csv"))
                original = pd.read_csv("data/trades.csv", dtype=str, keep_default_na=False)
                self.assertTrue(migrate_trades_schema())
                migrated = pd.read_csv("data/trades.csv", dtype=str, keep_default_na=False)
                for field in original.columns:
                    self.assertEqual(original[field].tolist(), migrated[field].tolist())
                for field in ALL_COLUMNS:
                    self.assertIn(field, migrated.columns)
                self.assertEqual(len(migrated), len(original))
                self.assertTrue(list(Path("data/backups").glob("*.csv")))
                self.assertFalse(migrate_trades_schema())
            finally:
                os.chdir(original_dir)


if __name__ == "__main__":
    unittest.main()

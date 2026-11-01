from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.migrations import MIGRATIONS
from scripts.check_database_migrations import migrate, rehearse


class MigrationRehearsalTests(unittest.IsolatedAsyncioTestCase):
    async def test_historical_rows_survive_and_source_is_never_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "version12.db", root / "rehearsal"
            with patch("app.migrations.MIGRATIONS", MIGRATIONS[:12]):
                await migrate(source)
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("""INSERT INTO characters
                    (slug, name, race, stats, skills_primary, skills_secondary, inventory, notes)
                    VALUES ('legacy', 'Legacy hero', 'Human', '{}', '[]', '[]', '[]', 'Preserve me')""")
                connection.commit()
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch("builtins.print"):
                await rehearse(source, output)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(report["versions_before"]), 12)
            self.assertEqual(len(report["versions_after"]), len(MIGRATIONS))
            self.assertEqual(report["preserved_rows"]["characters"], 1)
            self.assertEqual(report["schema_differences_from_fresh"], [])
            self.assertTrue(report["second_run_unchanged"])

    async def test_existing_rehearsal_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.db", root / "existing"
            source.write_bytes(b"source untouched")
            output.mkdir()
            sentinel = output / "important.txt"
            sentinel.write_text("keep")
            with self.assertRaises(FileExistsError):
                await rehearse(source, output)
            self.assertEqual(sentinel.read_text(), "keep")
            self.assertEqual(source.read_bytes(), b"source untouched")


if __name__ == "__main__":
    unittest.main()

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.sqlite_backup import DatabaseSnapshotError, create_sqlite_snapshot

ROOT = Path(__file__).resolve().parents[1]


class SqliteBackupTests(unittest.TestCase):
    def test_wal_commits_are_backed_up_and_uncommitted_writes_excluded(self):
        with tempfile.TemporaryDirectory(prefix="sqlite backup ") as directory:
            root = Path(directory)
            source, target, raw = (root / name for name in ["live.db", "backup.db", "raw.db"])
            with closing(sqlite3.connect(source)) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, content TEXT)")
                writer.commit()
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                writer.execute("INSERT INTO notes VALUES (1, 'committed in WAL')")
                writer.commit()
                shutil.copyfile(source, raw)
                with closing(sqlite3.connect(raw)) as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)
                writer.execute("INSERT INTO notes VALUES (2, 'not committed')")
                create_sqlite_snapshot(source, target)
                with closing(sqlite3.connect(target)) as restored:
                    self.assertEqual(restored.execute("SELECT * FROM notes").fetchall(), [(1, "committed in WAL")])
                    self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                writer.rollback()
                self.assertEqual(writer.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 1)

    def test_missing_source_is_never_created(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "missing.db", Path(directory) / "backup.db"
            with self.assertRaises(DatabaseSnapshotError):
                create_sqlite_snapshot(source, target)
            self.assertFalse(source.exists())
            self.assertFalse(target.exists())

    def test_existing_backup_and_source_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "live.db", Path(directory) / "backup.db"
            source.write_bytes(b"original database")
            target.write_bytes(b"previous backup")
            for destination in [source, target]:
                with self.assertRaises(DatabaseSnapshotError):
                    create_sqlite_snapshot(source, destination)
            self.assertEqual(source.read_bytes(), b"original database")
            self.assertEqual(target.read_bytes(), b"previous backup")

    def test_corrupt_source_does_not_leave_a_partial_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "bad.db", Path(directory) / "backup.db"
            source.write_bytes(b"not a SQLite file")
            with self.assertRaises(DatabaseSnapshotError):
                create_sqlite_snapshot(source, target)
            self.assertFalse(target.exists())

    def test_tool_can_run_from_stdin_without_installed_app_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "live.db", root / "backup.db"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE notes (content TEXT)")
                connection.execute("INSERT INTO notes VALUES ('saved')")
                connection.commit()
            command = [sys.executable, "-", str(source), str(target)]
            script = (ROOT / "app/sqlite_backup.py").read_text(encoding="utf-8")
            result = subprocess.run(command, input=script, text=True, capture_output=True, cwd=root, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            repeated = subprocess.run(command, input=script, text=True, capture_output=True, cwd=root, timeout=10)
            self.assertEqual(repeated.returncode, 1)
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(connection.execute("SELECT * FROM notes").fetchall(), [("saved",)])

    def test_s3_upload_receives_the_same_verified_backup(self):
        from app.config import Settings
        from app.db_snapshot import create_and_upload_database_snapshot

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "live.db"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE notes (content TEXT)")
                connection.execute("INSERT INTO notes VALUES ('preserved')")
                connection.commit()
            settings = Settings(_env_file=None, database_url="sqlite:///" + source.as_posix(),
                                db_snapshot_on_shutdown=True)
            uploaded = []

            def inspect_upload(path, key, content_type):
                with closing(sqlite3.connect(path)) as connection:
                    self.assertEqual(connection.execute("SELECT * FROM notes").fetchall(), [("preserved",)])
                uploaded.append(path)

            with patch("app.db_snapshot.ScalewayObjectStorage") as storage:
                storage.return_value.upload_file.side_effect = inspect_upload
                self.assertTrue(create_and_upload_database_snapshot(settings).startswith("save/"))
            self.assertEqual(len(uploaded), 1)
            self.assertFalse(uploaded[0].exists())


if __name__ == "__main__":
    unittest.main()

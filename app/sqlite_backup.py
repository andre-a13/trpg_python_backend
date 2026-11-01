"""SQLite backup shared by deployment and S3 snapshots; runnable via stdin."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3


class DatabaseSnapshotError(RuntimeError):
    pass


def create_sqlite_snapshot(source_path: Path, snapshot_path: Path) -> None:
    source_path = source_path.resolve()
    snapshot_path = snapshot_path.resolve()
    if not source_path.is_file():
        raise DatabaseSnapshotError(f"SQLite database does not exist: {source_path}")
    if snapshot_path.exists():
        raise DatabaseSnapshotError(f"Refusing to overwrite an existing file: {snapshot_path}")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True, timeout=30)) as source:
            with closing(sqlite3.connect(snapshot_path)) as snapshot:
                source.backup(snapshot)
                if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise DatabaseSnapshotError("SQLite backup integrity check failed")
    except (sqlite3.Error, DatabaseSnapshotError) as error:
        snapshot_path.unlink(missing_ok=True)
        raise DatabaseSnapshotError(f"SQLite backup failed: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        create_sqlite_snapshot(args.source, args.destination)
    except (DatabaseSnapshotError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Saved verified SQLite backup: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

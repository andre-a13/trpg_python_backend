from contextlib import closing
import logging
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings
from app.storage.scaleway import ScalewayObjectStorage


logger = logging.getLogger(__name__)


class DatabaseSnapshotError(RuntimeError):
    pass


def create_and_upload_database_snapshot(settings: Settings) -> str | None:
    if not settings.db_snapshot_on_shutdown:
        logger.info("Database snapshot on shutdown is disabled")
        return None

    db_path = _sqlite_database_path(settings.database_url)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"data-{timestamp}.db"
    object_key = _object_key(settings.db_snapshot_prefix, filename)

    with tempfile.TemporaryDirectory() as temp_dir:
        snapshot_path = Path(temp_dir) / filename
        _create_sqlite_snapshot(db_path, snapshot_path)

        storage = ScalewayObjectStorage(settings)
        storage.upload_file(
            snapshot_path,
            object_key,
            content_type="application/vnd.sqlite3",
        )

    return object_key


def _sqlite_database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        raise DatabaseSnapshotError("Database shutdown snapshots only support SQLite")
    if not url.database or url.database == ":memory:":
        raise DatabaseSnapshotError("Cannot snapshot an in-memory SQLite database")

    db_path = Path(url.database)
    if not db_path.exists():
        raise DatabaseSnapshotError(f"SQLite database does not exist: {db_path}")
    return db_path


def _create_sqlite_snapshot(source_path: Path, snapshot_path: Path) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(source_path, timeout=30)) as source:
        with closing(sqlite3.connect(snapshot_path)) as snapshot:
            source.backup(snapshot)


def _object_key(prefix: str, filename: str) -> str:
    clean_prefix = prefix.strip("/")
    if not clean_prefix:
        return filename
    return f"{clean_prefix}/{filename}"

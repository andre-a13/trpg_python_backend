"""Rehearse migrations on a verified copy; never migrate the source database."""
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import MIGRATIONS, run_migrations
from app.sqlite_backup import create_sqlite_snapshot


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def inventory(path: Path, columns=None):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result = {}
        for table in tables if columns is None else columns:
            names = (columns[table]["columns"] if columns is not None else
                     [row[1] for row in connection.execute(f"PRAGMA table_info({quote(table)})")])
            rows = connection.execute(f"SELECT {', '.join(map(quote, names))} FROM {quote(table)}").fetchall()
            encoded = sorted(json.dumps(row, ensure_ascii=False, default=repr) for row in rows)
            result[table] = {"columns": names, "rows": len(rows),
                             "sha256": hashlib.sha256("\n".join(encoded).encode()).hexdigest()}
        return result


def schema(path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: {
            "columns": sorted(tuple(row[1:]) for row in connection.execute(f"PRAGMA table_info({quote(table)})")),
            "foreign_keys": sorted(tuple(row[2:]) for row in connection.execute(f"PRAGMA foreign_key_list({quote(table)})")),
            "indexes": sorted((row[1], row[2], row[3], row[4], tuple(
                tuple(column[2:]) for column in connection.execute(f"PRAGMA index_xinfo({quote(row[1])})")
            )) for row in connection.execute(f"PRAGMA index_list({quote(table)})")),
        } for table in tables}


def validate(path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("Migrated database failed integrity_check")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Migrated database has foreign-key violations")
        return [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]


async def migrate(path: Path):
    engine = create_async_engine("sqlite+aiosqlite:///" + path.resolve().as_posix())
    try:
        await run_migrations(engine)
    finally:
        await engine.dispose()


async def rehearse(source: Path, output: Path):
    if not source.is_file():
        raise ValueError("Source database must already exist")
    output.mkdir(parents=True, exist_ok=False)
    restored, fresh = output / "migrated.db", output / "fresh.db"
    create_sqlite_snapshot(source, restored)
    before = inventory(restored)
    previous = validate(restored) if "schema_migrations" in before else []
    await migrate(restored)
    retained = {name: value for name, value in before.items() if name != "schema_migrations"}
    if inventory(restored, retained) != retained:
        raise RuntimeError("Pre-existing rows changed; inspect the migrated copy before deploying")
    versions = validate(restored)
    if versions != sorted(version for version, _ in MIGRATIONS):
        raise RuntimeError("Migration ledger does not match the application")
    once = inventory(restored)
    await migrate(restored)
    if inventory(restored) != once:
        raise RuntimeError("A second migration pass changed the data")
    await migrate(fresh)
    expected, actual = schema(fresh), schema(restored)
    differences = [name for name in set(expected) | set(actual) if expected.get(name) != actual.get(name)]
    report = {"source": str(source.resolve()), "copy": str(restored.resolve()),
              "versions_before": previous, "versions_after": versions,
              "preserved_rows": {name: info["rows"] for name, info in retained.items()},
              "integrity_check": "ok", "foreign_key_check": "ok", "second_run_unchanged": True,
              "schema_differences_from_fresh": sorted(differences)}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if differences:
        raise RuntimeError(f"Historical/fresh schema differences require review: {', '.join(differences)}. See {output / 'report.json'}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="New directory for migrated/fresh copies and a report; must not exist")
    args = parser.parse_args()
    asyncio.run(rehearse(args.source, args.output_dir))


if __name__ == "__main__":
    main()

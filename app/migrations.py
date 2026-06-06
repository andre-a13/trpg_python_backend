from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


Migration = tuple[str, Callable[[AsyncConnection], Awaitable[None]]]


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(100) NOT NULL PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
            """
        )
        rows = await conn.exec_driver_sql("SELECT version FROM schema_migrations")
        applied = {row[0] for row in rows.fetchall()}

        for version, migration in MIGRATIONS:
            if version in applied:
                continue
            await migration(conn)
            await conn.exec_driver_sql(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.utcnow().isoformat(timespec="seconds")),
            )


async def _column_exists(conn: AsyncConnection, table: str, column: str) -> bool:
    rows = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in rows.fetchall())


async def _add_column_if_missing(conn: AsyncConnection, table: str, column: str, ddl: str) -> None:
    if not await _column_exists(conn, table, column):
        await conn.exec_driver_sql(ddl)


async def _initial_schema(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER NOT NULL,
            slug VARCHAR(100) NOT NULL,
            name VARCHAR(100) NOT NULL,
            race VARCHAR(50) NOT NULL,
            portrait_url VARCHAR(2048),
            background_url VARCHAR(2048),
            stats JSON NOT NULL,
            skills_primary JSON NOT NULL,
            skills_secondary JSON NOT NULL,
            inventory JSON NOT NULL,
            gold INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            current_hp INTEGER NOT NULL DEFAULT 0,
            bonus_health INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (id)
        )
        """
    )
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_characters_name ON characters (name)")


async def _character_gold(conn: AsyncConnection) -> None:
    await _add_column_if_missing(
        conn,
        "characters",
        "gold",
        "ALTER TABLE characters ADD COLUMN gold INTEGER NOT NULL DEFAULT 0",
    )


async def _character_notes(conn: AsyncConnection) -> None:
    await _add_column_if_missing(
        conn,
        "characters",
        "notes",
        "ALTER TABLE characters ADD COLUMN notes TEXT",
    )


async def _character_current_hp(conn: AsyncConnection) -> None:
    await _add_column_if_missing(
        conn,
        "characters",
        "current_hp",
        "ALTER TABLE characters ADD COLUMN current_hp INTEGER NOT NULL DEFAULT 0",
    )


async def _unique_character_slug(conn: AsyncConnection) -> None:
    duplicates = await conn.exec_driver_sql(
        "SELECT slug, COUNT(*) FROM characters GROUP BY slug HAVING COUNT(*) > 1"
    )
    duplicate_slugs = [row[0] for row in duplicates.fetchall()]
    if duplicate_slugs:
        raise RuntimeError(f"Cannot add unique slug index; duplicate slugs exist: {duplicate_slugs}")

    indexes = await conn.exec_driver_sql("PRAGMA index_list('characters')")
    for row in indexes.fetchall():
        if row[1] == "ix_characters_slug" and not row[2]:
            await conn.exec_driver_sql("DROP INDEX ix_characters_slug")
            break

    await conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_characters_slug ON characters (slug)")


async def _character_bonus_health(conn: AsyncConnection) -> None:
    await _add_column_if_missing(
        conn,
        "characters",
        "bonus_health",
        "ALTER TABLE characters ADD COLUMN bonus_health INTEGER NOT NULL DEFAULT 0",
    )


async def _teams(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS teams (
            uuid VARCHAR(36) NOT NULL,
            name VARCHAR(100) NOT NULL,
            illustration_url VARCHAR(2048),
            PRIMARY KEY (uuid)
        )
        """
    )
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_teams_name ON teams (name)")
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS character_teams (
            character_id INTEGER NOT NULL,
            team_uuid VARCHAR(36) NOT NULL,
            PRIMARY KEY (character_id, team_uuid),
            FOREIGN KEY(character_id) REFERENCES characters (id) ON DELETE CASCADE,
            FOREIGN KEY(team_uuid) REFERENCES teams (uuid) ON DELETE CASCADE
        )
        """
    )


async def _accounts(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER NOT NULL,
            username VARCHAR(100) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id)
        )
        """
    )
    await conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)")
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            token_hash VARCHAR(64) NOT NULL,
            expires_at DATETIME NOT NULL,
            revoked_at DATETIME,
            created_at DATETIME NOT NULL,
            replaced_by_token_id INTEGER,
            PRIMARY KEY (id),
            FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY(replaced_by_token_id) REFERENCES refresh_tokens (id)
        )
        """
    )
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id ON refresh_tokens (user_id)")
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_refresh_tokens_token_hash ON refresh_tokens (token_hash)"
    )


async def _custom_inventory_tables(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS inventory_categories (
            id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_inventory_categories_character_name UNIQUE (character_id, name),
            FOREIGN KEY(character_id) REFERENCES characters (id) ON DELETE CASCADE
        )
        """
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_inventory_categories_character_id ON inventory_categories (character_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_inventory_categories_sort_order ON inventory_categories (sort_order)"
    )
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS inventory_contents (
            id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            notes TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(category_id) REFERENCES inventory_categories (id) ON DELETE CASCADE
        )
        """
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_inventory_contents_category_id ON inventory_contents (category_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_inventory_contents_sort_order ON inventory_contents (sort_order)"
    )


async def _character_background_url(conn: AsyncConnection) -> None:
    await _add_column_if_missing(
        conn,
        "characters",
        "background_url",
        "ALTER TABLE characters ADD COLUMN background_url VARCHAR(2048)",
    )


async def _character_note_tabs(conn: AsyncConnection) -> None:
    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS character_notes (
            id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            title VARCHAR(100) NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_character_notes_character_title UNIQUE (character_id, title),
            FOREIGN KEY(character_id) REFERENCES characters (id) ON DELETE CASCADE
        )
        """
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_character_notes_character_id ON character_notes (character_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_character_notes_sort_order ON character_notes (sort_order)"
    )
    await conn.exec_driver_sql(
        """
        INSERT INTO character_notes (character_id, title, content, sort_order, created_at, updated_at)
        SELECT characters.id, 'Notes', COALESCE(characters.notes, ''), 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM characters
        WHERE NOT EXISTS (
            SELECT 1
            FROM character_notes
            WHERE character_notes.character_id = characters.id
        )
        """
    )


MIGRATIONS: list[Migration] = [
    ("001_initial_schema", _initial_schema),
    ("002_character_gold", _character_gold),
    ("003_character_notes", _character_notes),
    ("004_character_current_hp", _character_current_hp),
    ("005_unique_character_slug", _unique_character_slug),
    ("006_character_bonus_health", _character_bonus_health),
    ("007_teams", _teams),
    ("008_accounts", _accounts),
    ("009_custom_inventory_tables", _custom_inventory_tables),
    ("010_character_background_url", _character_background_url),
    ("011_character_note_tabs", _character_note_tabs),
]

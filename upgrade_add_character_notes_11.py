import asyncio

from app.db import engine


async def main():
    async with engine.begin() as conn:
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

    await engine.dispose()


asyncio.run(main())

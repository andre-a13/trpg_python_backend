import asyncio

from app.db import engine


async def main():
    async with engine.begin() as conn:
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
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_teams_name ON teams (name)"
        )
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
    await engine.dispose()


asyncio.run(main())

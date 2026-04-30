import asyncio

from app.db import engine


async def main():
    async with engine.begin() as conn:
        columns = await conn.exec_driver_sql("PRAGMA table_info(characters)")
        existing_columns = {row[1] for row in columns}

        if "bonus_health" not in existing_columns:
            await conn.exec_driver_sql(
                "ALTER TABLE characters ADD COLUMN bonus_health INTEGER NOT NULL DEFAULT 0"
            )

    await engine.dispose()


asyncio.run(main())

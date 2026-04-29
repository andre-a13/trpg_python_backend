import asyncio
from app.db import engine

async def main():
    async with engine.begin() as conn:
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
    await engine.dispose()

asyncio.run(main())

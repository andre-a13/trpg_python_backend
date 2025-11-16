import asyncio
from app.db import engine
async def main():
    async with engine.begin() as conn:
        await conn.exec_driver_sql("ALTER TABLE characters ADD COLUMN current_hp INTEGER NOT NULL DEFAULT 0")
    await engine.dispose()
asyncio.run(main())
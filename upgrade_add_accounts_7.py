import asyncio

from app.db import engine


async def main():
    async with engine.begin() as conn:
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
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"
        )
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
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id ON refresh_tokens (user_id)"
        )
        await conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_refresh_tokens_token_hash ON refresh_tokens (token_hash)"
        )
    await engine.dispose()


asyncio.run(main())

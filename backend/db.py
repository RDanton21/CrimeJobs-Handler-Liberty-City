from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    from . import models  # noqa: F401  ensure models registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Inline-Migrationen (SQLite ALTER TABLE ADD COLUMN)
        await _migrate_add_column_if_missing(conn, "missions", "archived_at", "DATETIME")
        await _migrate_add_column_if_missing(
            conn, "crews", "info_channel_id", "VARCHAR(40) NOT NULL DEFAULT ''"
        )


async def _migrate_add_column_if_missing(conn, table: str, column: str, sql_type: str) -> None:
    res = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    cols = [row[1] for row in res.fetchall()]
    if column not in cols:
        await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

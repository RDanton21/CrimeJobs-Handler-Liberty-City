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
        await _migrate_add_column_if_missing(
            conn, "crews", "district", "VARCHAR(40) NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(conn, "missions", "deadline_at", "DATETIME")
        await _migrate_add_column_if_missing(
            conn, "missions", "archived_boss_info", "TEXT NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(
            conn, "missions", "expiry_message_id", "VARCHAR(40) NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(
            conn, "missions", "expiry_text", "TEXT NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(conn, "missions", "scheduled_send_at", "DATETIME")
        await _migrate_add_column_if_missing(
            conn, "missions", "reaction_reply_message_id", "VARCHAR(40) NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(
            conn, "missions", "reaction_reply_text", "TEXT NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(
            conn, "crews", "crime_business", "TEXT NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(
            conn, "crews", "crime_business_channel_id", "VARCHAR(40) NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(
            conn, "crews", "bonus_points", "INTEGER NOT NULL DEFAULT 0"
        )
        # Aktiv-Flag: bestehende Gangs bleiben durch DEFAULT 1 aktiv
        await _migrate_add_column_if_missing(
            conn, "crews", "is_active", "INTEGER NOT NULL DEFAULT 1"
        )
        # Personal-Briefing pro Mission (Admin-intern, Dashboard-Widget)
        await _migrate_add_column_if_missing(
            conn, "missions", "personnel_brief", "TEXT NOT NULL DEFAULT ''"
        )
        await _migrate_add_column_if_missing(
            conn, "missions", "personnel_updated_at", "DATETIME"
        )
        await _migrate_add_column_if_missing(
            conn, "missions", "personnel_discord_message_id",
            "VARCHAR(40) NOT NULL DEFAULT ''"
        )
        # Ankuendigung der Personal-Boerse im Jobs-Announce-Channel:
        # ID merken, damit sie beim Archivieren mitgeloescht werden kann
        await _migrate_add_column_if_missing(
            conn, "missions", "jobs_announce_message_id",
            "VARCHAR(40) NOT NULL DEFAULT ''"
        )


async def _migrate_add_column_if_missing(conn, table: str, column: str, sql_type: str) -> None:
    res = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    cols = [row[1] for row in res.fetchall()]
    if column not in cols:
        await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

# -*- coding: utf-8 -*-
"""Async-SQLite-Anbindung fuer die eigene jobs.db (Player + Slot-Belegungen)."""
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from . import config

# 3 Slashes + absoluter Pfad ergibt z.B. sqlite+aiosqlite:////app/data/jobs.db
DATABASE_URL = f"sqlite+aiosqlite:///{config.JOBS_DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Tabellen beim Startup anlegen (create_all ist idempotent).

    create_all legt nur fehlende TABELLEN an — neue SPALTEN in bereits
    existierenden Tabellen muessen von Hand nachgezogen werden.
    """
    parent = os.path.dirname(config.JOBS_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_column_if_missing(conn, "players", "last_seen", "DATETIME")
        # Anwesenheit (None=offen, 1=erschienen, 0=No-Show) auf beiden Tabellen
        await _add_column_if_missing(conn, "slot_assignments", "attended", "INTEGER")
        await _add_column_if_missing(conn, "completed_participations", "attended", "INTEGER")


async def _add_column_if_missing(conn, table: str, column: str, sql_type: str) -> None:
    res = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    if column not in [row[1] for row in res.fetchall()]:
        await conn.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
        )

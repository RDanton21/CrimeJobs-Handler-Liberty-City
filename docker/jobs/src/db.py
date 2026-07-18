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
    """Tabellen beim Startup anlegen (create_all ist idempotent)."""
    parent = os.path.dirname(config.JOBS_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

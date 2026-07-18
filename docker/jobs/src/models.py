# -*- coding: utf-8 -*-
"""SQLAlchemy-Modelle der jobs.db gemaess API-Kontrakt.

players:          eingeloggte Discord-Spieler (Upsert bei jedem Login)
slot_assignments: wer sich in welchen Personal-Slot eingetragen hat
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    discord_user_id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, default="")
    avatar: Mapped[str] = mapped_column(String, default="")
    last_login: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SlotAssignment(Base):
    __tablename__ = "slot_assignments"
    # Derselbe Slot pro Spieler nur 1x — Mehrfachbuchung ueber verschiedene Slots ok
    __table_args__ = (
        UniqueConstraint("slot_id", "player_discord_id", name="uq_slot_player"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(Integer, index=True)
    mission_id: Mapped[int] = mapped_column(Integer, index=True)
    player_discord_id: Mapped[str] = mapped_column(String, index=True)
    username: Mapped[str] = mapped_column(String, default="")
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

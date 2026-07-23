# -*- coding: utf-8 -*-
"""SQLAlchemy-Modelle der jobs.db gemaess API-Kontrakt.

players:            eingeloggte Discord-Spieler (Upsert bei jedem Login)
slot_assignments:   wer sich in welchen Personal-Slot eingetragen hat
completed_parts:    Historie abgeschlossener Einsaetze (fuer die Admin-Statistik)
dismissed_missions: vom Admin vorzeitig ausgeblendete Auftraege
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
    # Letzter Board-Aufruf — daraus leitet sich "gerade aktiv" ab
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
    # Anwesenheit, vom Admin gesetzt: None = noch offen, 1 = erschienen, 0 = No-Show.
    # Wird beim Archivieren in CompletedParticipation uebernommen.
    attended: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CompletedParticipation(Base):
    """Wer hat welchen Auftrag tatsaechlich mitgemacht.

    Wird festgeschrieben, sobald der Auftrag im Crime-Dashboard archiviert
    (= erledigt) ist. Bleibt bestehen, auch wenn der Auftrag spaeter vom
    Board verschwindet — sonst waere die Statistik nach einer Stunde leer.
    """
    __tablename__ = "completed_participations"
    __table_args__ = (
        UniqueConstraint("slot_id", "player_discord_id", name="uq_done_slot_player"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(Integer, index=True)
    mission_id: Mapped[int] = mapped_column(Integer, index=True)
    player_discord_id: Mapped[str] = mapped_column(String, index=True)
    username: Mapped[str] = mapped_column(String, default="")
    crew_name: Mapped[str] = mapped_column(String, default="")
    slot_name: Mapped[str] = mapped_column(String, default="")
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Anwesenheit aus dem Live-Assignment uebernommen (None/1/0), s. SlotAssignment.
    attended: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WaitlistEntry(Base):
    """Warteliste fuer volle Slots — FIFO nach joined_at. Beim Freiwerden
    eines Platzes rueckt der aelteste Eintrag automatisch nach (inkl. DM)."""
    __tablename__ = "waitlist_entries"
    __table_args__ = (
        UniqueConstraint("slot_id", "player_discord_id", name="uq_wait_slot_player"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(Integer, index=True)
    mission_id: Mapped[int] = mapped_column(Integer, index=True)
    player_discord_id: Mapped[str] = mapped_column(String, index=True)
    username: Mapped[str] = mapped_column(String, default="")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SentReminder(Base):
    """Bereits verschickte Erinnerungs-DMs — verhindert Doppel-DMs, auch
    ueber Container-Neustarts hinweg. kind laesst spaeter weitere
    Erinnerungsarten zu (z.B. 'day_before')."""
    __tablename__ = "sent_reminders"
    __table_args__ = (
        UniqueConstraint("slot_id", "player_discord_id", "kind", name="uq_reminder"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(Integer, index=True)
    mission_id: Mapped[int] = mapped_column(Integer, index=True)
    player_discord_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, default="pre_start")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DismissedMission(Base):
    """Vom Admin vorzeitig ausgeblendeter Auftrag — er verschwindet sofort
    vom Board, statt die uebliche Stunde stehen zu bleiben."""
    __tablename__ = "dismissed_missions"

    mission_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    dismissed_by: Mapped[str] = mapped_column(String, default="")

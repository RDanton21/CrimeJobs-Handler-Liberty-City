from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class MissionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    DRAFT = "draft"


class RelationType(str, Enum):
    ALLIED = "allied"
    RIVAL = "rival"
    NEUTRAL = "neutral"
    BUSINESS = "business"
    HOSTILE = "hostile"


class Crew(Base):
    __tablename__ = "crews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    story_background: Mapped[str] = mapped_column(Text, default="")
    crime_business: Mapped[str] = mapped_column(Text, default="")
    crime_business_channel_id: Mapped[str] = mapped_column(String(40), default="")
    discord_channel_id: Mapped[str] = mapped_column(String(40), default="")
    info_channel_id: Mapped[str] = mapped_column(String(40), default="")
    district: Mapped[str] = mapped_column(String(40), default="")
    color_hex: Mapped[str] = mapped_column(String(7), default="#b91c1c")
    bonus_points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    missions: Mapped[list["Mission"]] = relationship(
        back_populates="crew", cascade="all, delete-orphan", order_by="Mission.created_at.desc()"
    )

    relations_a: Mapped[list["CrewRelation"]] = relationship(
        "CrewRelation",
        foreign_keys="CrewRelation.crew_a_id",
        back_populates="crew_a",
        cascade="all, delete-orphan",
    )
    relations_b: Mapped[list["CrewRelation"]] = relationship(
        "CrewRelation",
        foreign_keys="CrewRelation.crew_b_id",
        back_populates="crew_b",
        cascade="all, delete-orphan",
    )


class CrewRelation(Base):
    __tablename__ = "crew_relations"
    __table_args__ = (UniqueConstraint("crew_a_id", "crew_b_id", name="uq_relation_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crew_a_id: Mapped[int] = mapped_column(ForeignKey("crews.id", ondelete="CASCADE"))
    crew_b_id: Mapped[int] = mapped_column(ForeignKey("crews.id", ondelete="CASCADE"))
    relation_type: Mapped[RelationType] = mapped_column(SAEnum(RelationType), default=RelationType.NEUTRAL)
    notes: Mapped[str] = mapped_column(Text, default="")

    crew_a: Mapped["Crew"] = relationship("Crew", foreign_keys=[crew_a_id], back_populates="relations_a")
    crew_b: Mapped["Crew"] = relationship("Crew", foreign_keys=[crew_b_id], back_populates="relations_b")


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id", ondelete="CASCADE"))

    ai_provider: Mapped[str] = mapped_column(String(20), default="anthropic")
    ai_model: Mapped[str] = mapped_column(String(80), default="")
    prompt_used: Mapped[str] = mapped_column(Text, default="")

    content_generated: Mapped[str] = mapped_column(Text, default="")
    content_final: Mapped[str] = mapped_column(Text, default="")

    image_path: Mapped[str] = mapped_column(String(255), default="")

    discord_message_id: Mapped[str] = mapped_column(String(40), default="")
    discord_channel_id: Mapped[str] = mapped_column(String(40), default="")

    status: Mapped[MissionStatus] = mapped_column(SAEnum(MissionStatus), default=MissionStatus.DRAFT)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_boss_info: Mapped[str] = mapped_column(Text, default="")
    expiry_message_id: Mapped[str] = mapped_column(String(40), default="")
    expiry_text: Mapped[str] = mapped_column(Text, default="")
    scheduled_send_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reaction_reply_message_id: Mapped[str] = mapped_column(String(40), default="")
    reaction_reply_text: Mapped[str] = mapped_column(Text, default="")
    # Admin-internes Personal-Briefing: welche NPCs/Mittler die Mission braucht.
    # Markdown-Text, sichtbar im Dashboard-Widget & Mission-Detail.
    personnel_brief: Mapped[str] = mapped_column(Text, default="")
    personnel_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # ID der letzten Discord-Message im Admin-Channel (für Replace-Previous-Pattern)
    personnel_discord_message_id: Mapped[str] = mapped_column(String(40), default="")

    crew: Mapped["Crew"] = relationship(back_populates="missions")


class PersonnelSlot(Base):
    """Spieler-NPC-Slot pro Mission — strukturiert aus dem Personal-Brief
    geparst (per KI oder manuell). Wird vom externen Jobs-Dashboard ueber
    die Public-API (X-API-Key) gelesen; Spieler tragen sich dort ein."""
    __tablename__ = "personnel_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), index=True
    )
    npc_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    function: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    costume: Mapped[str] = mapped_column(String(255), default="")
    required_count: Mapped[int] = mapped_column(Integer, default=1)
    slot_window: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, default="")


class ExpiryMessage(Base):
    """Pool von Sprüchen, die bei abgelaufener Mission-Deadline zufällig
    im Auftrags-Channel gepostet werden."""
    __tablename__ = "expiry_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReactionMessage(Base):
    """Pool von Sprüchen, die nach jeder Boss-Reaktion (👍/👎/❌) zufällig
    als Reply im Auftrags-Channel gepostet werden."""
    __tablename__ = "reaction_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Top3TitlePoolMessage(Base):
    """Pool von Embed-Titeln, die beim täglichen Top-3-Hype-Post zufällig
    gewählt werden. Fallback: settings.ranking_top3_title wenn Pool leer."""
    __tablename__ = "top3_title_pool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SystemPrompt(Base):
    """Benannte System-Prompt-Varianten. Genau einer kann aktiv sein
    (is_active=True) — wird beim Generieren genutzt."""
    __tablename__ = "system_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

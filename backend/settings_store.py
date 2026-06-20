"""Persistente Settings (API-Keys etc.) in DB. Override .env zur Laufzeit."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Settings as SettingsRow

KEYS = {
    "anthropic_api_key",
    "openai_api_key",
    "default_provider",
    "default_claude_model",
    "default_openai_model",
    "system_prompt",
    # Tägliches Ranking-Posting in Discord
    "ranking_daily_enabled",
    "ranking_daily_channel_id",
    "ranking_daily_time",       # "HH:MM" lokal
    "ranking_daily_range",      # 'today' | '7d' | '30d' | 'all'
    "ranking_daily_crime_only",
    "ranking_daily_show_districts",
    "ranking_daily_title",
    "ranking_daily_intro",
    # Zweite Konfig: täglicher Top-3-Hype-Post (eigener Channel + Zeit)
    "ranking_top3_enabled",
    "ranking_top3_channel_id",
    "ranking_top3_time",
    "ranking_top3_range",
    "ranking_top3_crime_only",
    "ranking_top3_title",
    "ranking_top3_intro",
    # IDs der letzten geposteten Messages — fürs Auto-Replace
    "ranking_daily_last_message_id",
    "ranking_top3_last_message_id",
    # Reset-Stichtag: ab diesem Zeitpunkt zählen Missions im Ranking
    "ranking_reset_at",
    # Reset-Stichtag: ab diesem Zeitpunkt zählen Missions in der
    # Reaktions-Statistik im Dashboard (Soft-Reset).
    "stats_reset_at",
    # Admin-Channel für Personal-Bedarf-Posts (Spielleitung sieht hier
    # pro Mission Crew + Slot + NPC-Plan)
    "personnel_admin_channel_id",
}


async def get_all(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(select(SettingsRow))
    return {row.key: row.value for row in result.scalars().all()}


async def get(session: AsyncSession, key: str, default: str = "") -> str:
    result = await session.execute(select(SettingsRow).where(SettingsRow.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def set_value(session: AsyncSession, key: str, value: str) -> None:
    if key not in KEYS:
        raise ValueError(f"unknown setting {key}")
    result = await session.execute(select(SettingsRow).where(SettingsRow.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        session.add(SettingsRow(key=key, value=value))
    else:
        row.value = value
    await session.commit()

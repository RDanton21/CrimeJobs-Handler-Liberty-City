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

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_admin
from .config import settings as env_settings
from .db import get_session
from .prompts import DEFAULT_SYSTEM_PROMPT
from .schemas import SettingsUpdate
from .settings_store import get_all, set_value

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


@router.get("")
async def get_settings(session: AsyncSession = Depends(get_session)):
    db_vals = await get_all(session)

    def merged(key_db: str, env_default: str) -> str:
        return db_vals.get(key_db, "") or env_default

    return {
        "anthropic_api_key_set": bool(merged("anthropic_api_key", env_settings.anthropic_api_key)),
        "openai_api_key_set": bool(merged("openai_api_key", env_settings.openai_api_key)),
        "default_provider": merged("default_provider", env_settings.default_ai_provider),
        "default_claude_model": merged("default_claude_model", env_settings.default_claude_model),
        "default_openai_model": merged("default_openai_model", env_settings.default_openai_model),
        "system_prompt": db_vals.get("system_prompt", ""),
        "system_prompt_default": DEFAULT_SYSTEM_PROMPT,
        # Tägliches Ranking-Posting
        "ranking_daily_enabled": db_vals.get("ranking_daily_enabled", ""),
        "ranking_daily_channel_id": db_vals.get("ranking_daily_channel_id", ""),
        "ranking_daily_time": db_vals.get("ranking_daily_time", "03:33"),
        "ranking_daily_range": db_vals.get("ranking_daily_range", "all"),
        "ranking_daily_crime_only": db_vals.get("ranking_daily_crime_only", "true"),
        "ranking_daily_show_districts": db_vals.get("ranking_daily_show_districts", "true"),
        "ranking_daily_title": db_vals.get("ranking_daily_title", "🏆 Crew-Ranking — Liberty City"),
        "ranking_daily_intro": db_vals.get("ranking_daily_intro", ""),
        # Daily Top 3 Hype-Post (zweite Konfig)
        "ranking_top3_enabled": db_vals.get("ranking_top3_enabled", ""),
        "ranking_top3_channel_id": db_vals.get("ranking_top3_channel_id", ""),
        "ranking_top3_time": db_vals.get("ranking_top3_time", "08:00"),
        "ranking_top3_range": db_vals.get("ranking_top3_range", "all"),
        "ranking_top3_crime_only": db_vals.get("ranking_top3_crime_only", "true"),
        "ranking_top3_title": db_vals.get("ranking_top3_title", "🥇 Die Spitze von Liberty City"),
        "ranking_top3_intro": db_vals.get("ranking_top3_intro", ""),
        # Personal-Bedarf Admin-Channel (Dashboard-Widget "📤 Posten")
        "personnel_admin_channel_id": db_vals.get("personnel_admin_channel_id", ""),
        # Jobs-Dashboard: Ankündigungs-Ping bei neuen/erhöhten Spieler-Slots
        "jobs_announce_channel_id": db_vals.get("jobs_announce_channel_id", ""),
        "jobs_ping_role_id": db_vals.get("jobs_ping_role_id", "1528099740649127977"),
        "jobs_dashboard_url": db_vals.get("jobs_dashboard_url", "https://jobs.bots.sektorrp.eu"),
    }


@router.patch("")
async def update_settings(
    payload: SettingsUpdate, session: AsyncSession = Depends(get_session)
):
    data = payload.model_dump(exclude_unset=True)
    mapping = {
        "anthropic_api_key": "anthropic_api_key",
        "openai_api_key": "openai_api_key",
        "default_provider": "default_provider",
        "default_claude_model": "default_claude_model",
        "default_openai_model": "default_openai_model",
        "system_prompt": "system_prompt",
        "ranking_daily_enabled": "ranking_daily_enabled",
        "ranking_daily_channel_id": "ranking_daily_channel_id",
        "ranking_daily_time": "ranking_daily_time",
        "ranking_daily_range": "ranking_daily_range",
        "ranking_daily_crime_only": "ranking_daily_crime_only",
        "ranking_daily_show_districts": "ranking_daily_show_districts",
        "ranking_daily_title": "ranking_daily_title",
        "ranking_daily_intro": "ranking_daily_intro",
        "ranking_top3_enabled": "ranking_top3_enabled",
        "ranking_top3_channel_id": "ranking_top3_channel_id",
        "ranking_top3_time": "ranking_top3_time",
        "ranking_top3_range": "ranking_top3_range",
        "ranking_top3_crime_only": "ranking_top3_crime_only",
        "ranking_top3_title": "ranking_top3_title",
        "ranking_top3_intro": "ranking_top3_intro",
        "personnel_admin_channel_id": "personnel_admin_channel_id",
        "jobs_announce_channel_id": "jobs_announce_channel_id",
        "jobs_ping_role_id": "jobs_ping_role_id",
        "jobs_dashboard_url": "jobs_dashboard_url",
    }
    for field, val in data.items():
        if val is None:
            continue
        key = mapping.get(field)
        if not key:
            # Unbekanntes Settings-Feld → defensiv überspringen, nicht 500'en.
            # Heißt: jemand hat Schema erweitert ohne Mapping zu pflegen.
            continue
        await set_value(session, key, val)
    return {"ok": True}

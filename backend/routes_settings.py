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
    }
    for field, val in data.items():
        if val is None:
            continue
        await set_value(session, mapping[field], val)
    return {"ok": True}

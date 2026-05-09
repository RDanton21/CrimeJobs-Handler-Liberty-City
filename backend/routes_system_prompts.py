from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_admin
from .db import get_session
from .models import SystemPrompt
from .prompts import DEFAULT_SYSTEM_PROMPT
from .schemas import SystemPromptCreate, SystemPromptOut, SystemPromptUpdate

router = APIRouter(
    prefix="/api/system-prompts",
    tags=["system-prompts"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[SystemPromptOut])
async def list_system_prompts(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(SystemPrompt).order_by(SystemPrompt.id))
    return res.scalars().all()


@router.get("/default")
async def get_default_text():
    """Liefert den hardgecodeten Default-Prompt aus prompts.py — als
    Vorlage für neue Einträge."""
    return {"text": DEFAULT_SYSTEM_PROMPT}


@router.post("", response_model=SystemPromptOut, status_code=201)
async def create_system_prompt(
    payload: SystemPromptCreate, session: AsyncSession = Depends(get_session)
):
    name = payload.name.strip()
    text = payload.text.strip()
    if not name:
        raise HTTPException(400, "Name darf nicht leer sein")
    if not text:
        raise HTTPException(400, "Text darf nicht leer sein")
    sp = SystemPrompt(name=name, text=text, is_active=False)
    session.add(sp)
    await session.commit()
    await session.refresh(sp)
    return sp


@router.patch("/{sp_id}", response_model=SystemPromptOut)
async def update_system_prompt(
    sp_id: int, payload: SystemPromptUpdate, session: AsyncSession = Depends(get_session)
):
    sp = await session.get(SystemPrompt, sp_id)
    if not sp:
        raise HTTPException(404, "Prompt nicht gefunden")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is None:
            continue
        if k == "name" and not v.strip():
            raise HTTPException(400, "Name darf nicht leer sein")
        if k == "text" and not v.strip():
            raise HTTPException(400, "Text darf nicht leer sein")
        setattr(sp, k, v.strip() if isinstance(v, str) else v)
    await session.commit()
    await session.refresh(sp)
    return sp


@router.post("/{sp_id}/activate", response_model=SystemPromptOut)
async def activate_system_prompt(sp_id: int, session: AsyncSession = Depends(get_session)):
    sp = await session.get(SystemPrompt, sp_id)
    if not sp:
        raise HTTPException(404, "Prompt nicht gefunden")
    # alle anderen deaktivieren
    await session.execute(
        update(SystemPrompt).where(SystemPrompt.id != sp_id).values(is_active=False)
    )
    sp.is_active = True
    await session.commit()
    await session.refresh(sp)
    return sp


@router.post("/deactivate", status_code=204)
async def deactivate_all(session: AsyncSession = Depends(get_session)):
    """Setzt alle Prompts auf inaktiv → Default greift."""
    await session.execute(update(SystemPrompt).values(is_active=False))
    await session.commit()


@router.delete("/{sp_id}", status_code=204)
async def delete_system_prompt(sp_id: int, session: AsyncSession = Depends(get_session)):
    sp = await session.get(SystemPrompt, sp_id)
    if not sp:
        raise HTTPException(404, "Prompt nicht gefunden")
    await session.delete(sp)
    await session.commit()

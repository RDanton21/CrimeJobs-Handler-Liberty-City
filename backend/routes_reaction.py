from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_admin
from .db import get_session
from .models import ReactionMessage
from .schemas import ReactionMessageCreate, ReactionMessageOut

router = APIRouter(
    prefix="/api/reaction-messages",
    tags=["reaction-messages"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ReactionMessageOut])
async def list_reaction_messages(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(ReactionMessage).order_by(ReactionMessage.id.desc()))
    return res.scalars().all()


@router.post("", response_model=ReactionMessageOut, status_code=201)
async def create_reaction_message(
    payload: ReactionMessageCreate, session: AsyncSession = Depends(get_session)
):
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "Text darf nicht leer sein")
    rm = ReactionMessage(text=text)
    session.add(rm)
    await session.commit()
    await session.refresh(rm)
    return rm


@router.delete("/{rm_id}", status_code=204)
async def delete_reaction_message(rm_id: int, session: AsyncSession = Depends(get_session)):
    rm = await session.get(ReactionMessage, rm_id)
    if not rm:
        raise HTTPException(404, "Spruch nicht gefunden")
    await session.delete(rm)
    await session.commit()

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_admin
from .db import get_session
from .models import ExpiryMessage
from .schemas import ExpiryMessageCreate, ExpiryMessageOut

router = APIRouter(
    prefix="/api/expiry-messages",
    tags=["expiry-messages"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ExpiryMessageOut])
async def list_expiry_messages(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(ExpiryMessage).order_by(ExpiryMessage.id.desc()))
    return res.scalars().all()


@router.post("", response_model=ExpiryMessageOut, status_code=201)
async def create_expiry_message(
    payload: ExpiryMessageCreate, session: AsyncSession = Depends(get_session)
):
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "Text darf nicht leer sein")
    em = ExpiryMessage(text=text)
    session.add(em)
    await session.commit()
    await session.refresh(em)
    return em


@router.delete("/{em_id}", status_code=204)
async def delete_expiry_message(em_id: int, session: AsyncSession = Depends(get_session)):
    em = await session.get(ExpiryMessage, em_id)
    if not em:
        raise HTTPException(404, "Spruch nicht gefunden")
    await session.delete(em)
    await session.commit()

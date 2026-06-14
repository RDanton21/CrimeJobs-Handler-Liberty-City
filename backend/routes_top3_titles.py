"""Pool von Embed-Titeln für den täglichen Top-3-Hype-Post.
Wenn Pool nicht leer ist, wird beim Posten zufällig ein Titel daraus gewählt
(ranking_top3_title in settings dient als Fallback bei leerem Pool)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_admin
from .db import get_session
from .models import Top3TitlePoolMessage
from .schemas import Top3TitlePoolCreate, Top3TitlePoolOut

router = APIRouter(
    prefix="/api/top3-title-pool",
    tags=["top3-title-pool"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[Top3TitlePoolOut])
async def list_top3_titles(session: AsyncSession = Depends(get_session)):
    res = await session.execute(
        select(Top3TitlePoolMessage).order_by(Top3TitlePoolMessage.id.desc())
    )
    return res.scalars().all()


@router.post("", response_model=Top3TitlePoolOut, status_code=201)
async def create_top3_title(
    payload: Top3TitlePoolCreate, session: AsyncSession = Depends(get_session)
):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(400, "Titel darf nicht leer sein")
    item = Top3TitlePoolMessage(text=text)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{title_id}", status_code=204)
async def delete_top3_title(
    title_id: int, session: AsyncSession = Depends(get_session)
):
    item = await session.get(Top3TitlePoolMessage, title_id)
    if not item:
        raise HTTPException(404, "Titel nicht gefunden")
    await session.delete(item)
    await session.commit()

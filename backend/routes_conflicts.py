"""API fuer selbst gemeldete Konflikte/Beef der Gruppierungen."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_admin
from .conflicts import load_conflicts, save_conflicts
from .db import get_session
from .models import Crew

router = APIRouter(prefix="/api/conflicts", tags=["conflicts"], dependencies=[Depends(require_admin)])


@router.get("")
async def get_conflicts(session: AsyncSession = Depends(get_session)):
    """Liefert die Konflikt-Map + alle Gang-Namen (fuer die Bearbeitung)."""
    crews = (await session.execute(select(Crew).order_by(Crew.name))).scalars().all()
    return {
        "conflicts": load_conflicts(),
        "crew_names": [c.name for c in crews],
    }


@router.put("")
async def put_conflicts(payload: dict):
    """Speichert die komplette Konflikt-Map. Body: {conflicts: {name: [feind,...]}}"""
    data = payload.get("conflicts") if isinstance(payload, dict) else None
    save_conflicts(data or {})
    return {"ok": True, "conflicts": load_conflicts()}

import asyncio
import json
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .ai import get_provider
from .auth import require_admin
from .config import settings
from .db import get_session
from .models import Crew, CrewRelation, Mission, RelationType
from .prompts import (
    build_crew_enrichment_prompt,
    build_crime_business_briefing_prompt,
)
from .schemas import (
    CrewCreate,
    CrewEnrichApplyRequest,
    CrewEnrichPreviewResponse,
    CrewEnrichRelationSuggestion,
    CrewEnrichRequest,
    CrewOut,
    CrewRelationBase,
    CrewRelationOut,
    CrewUpdate,
    CrimeBusinessPostRequest,
    CrimeBusinessSendRequest,
)
from .settings_store import get as settings_get_value

router = APIRouter(prefix="/api/crews", tags=["crews"], dependencies=[Depends(require_admin)])


async def _attach_last_mission(session: AsyncSession, crew: Crew) -> Crew:
    res = await session.execute(
        select(Mission)
        .where(Mission.crew_id == crew.id, Mission.archived_at.is_(None))
        .order_by(Mission.created_at.desc())
        .limit(1)
    )
    last = res.scalar_one_or_none()
    if last:
        crew.last_mission_status = last.status
        crew.last_mission_at = last.reacted_at or last.sent_at or last.created_at
    else:
        crew.last_mission_status = None
        crew.last_mission_at = None
    return crew


@router.get("/notifications")
async def crew_notifications(session: AsyncSession = Depends(get_session)):
    """Liefert pro Crew mit info_channel_id den Zeitstempel der jüngsten
    Nicht-Bot-Message im Info-Channel — fürs Blink-Indicator auf dem Dashboard.
    Bot-Calls laufen parallel, damit Polling auch bei vielen Crews schnell ist.

    WICHTIG: Diese Route MUSS vor allen `/{crew_id}`-Routes stehen, sonst matcht
    FastAPI 'notifications' als int crew_id und wirft 422."""
    res = await session.execute(
        select(Crew).where(Crew.info_channel_id != "").order_by(Crew.id)
    )
    crews_with_info = list(res.scalars().all())

    if not crews_with_info:
        return []

    async def _fetch_latest(channel_id: str) -> str | None:
        # Limit hoch genug, damit Bot-Messages oben nicht alles wegfiltern.
        try:
            async with httpx.AsyncClient(timeout=5.0) as cli:
                r = await cli.post(
                    "http://127.0.0.1:8001/read_channel",
                    json={"channel_id": channel_id, "limit": 10, "oldest_first": False},
                )
            if r.status_code >= 400:
                return None
            msgs = r.json()
            if not msgs:
                return None
            return msgs[0].get("posted_at")
        except Exception:
            return None

    timestamps = await asyncio.gather(
        *[_fetch_latest(c.info_channel_id) for c in crews_with_info]
    )

    return [
        {"crew_id": c.id, "latest_boss_message_at": ts}
        for c, ts in zip(crews_with_info, timestamps)
    ]


@router.get("", response_model=list[CrewOut])
async def list_crews(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Crew).order_by(Crew.name))
    crews = result.scalars().all()
    for c in crews:
        await _attach_last_mission(session, c)
    return crews


@router.post("", response_model=CrewOut, status_code=201)
async def create_crew(payload: CrewCreate, session: AsyncSession = Depends(get_session)):
    crew = Crew(**payload.model_dump())
    session.add(crew)
    await session.commit()
    await session.refresh(crew)
    await _attach_last_mission(session, crew)
    return crew


@router.get("/{crew_id}", response_model=CrewOut)
async def get_crew(crew_id: int, session: AsyncSession = Depends(get_session)):
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    await _attach_last_mission(session, crew)
    return crew


@router.patch("/{crew_id}", response_model=CrewOut)
async def update_crew(
    crew_id: int, payload: CrewUpdate, session: AsyncSession = Depends(get_session)
):
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(crew, k, v)
    await session.commit()
    await session.refresh(crew)
    await _attach_last_mission(session, crew)
    return crew


@router.delete("/{crew_id}", status_code=204)
async def delete_crew(crew_id: int, session: AsyncSession = Depends(get_session)):
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    await session.delete(crew)
    await session.commit()


# ---- Relations ----


@router.get("/{crew_id}/relations", response_model=list[CrewRelationOut])
async def list_relations(crew_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(CrewRelation).where(
            (CrewRelation.crew_a_id == crew_id) | (CrewRelation.crew_b_id == crew_id)
        )
    )
    return result.scalars().all()


@router.post("/{crew_id}/relations", response_model=CrewRelationOut, status_code=201)
async def add_relation(
    crew_id: int,
    payload: CrewRelationBase,
    session: AsyncSession = Depends(get_session),
):
    if crew_id not in (payload.crew_a_id, payload.crew_b_id):
        raise HTTPException(400, "crew_id muss in Relation enthalten sein")
    if payload.crew_a_id == payload.crew_b_id:
        raise HTTPException(400, "Self-Relation nicht erlaubt")
    rel = CrewRelation(**payload.model_dump())
    session.add(rel)
    await session.commit()
    await session.refresh(rel)
    return rel


@router.delete("/relations/{relation_id}", status_code=204)
async def delete_relation(relation_id: int, session: AsyncSession = Depends(get_session)):
    rel = await session.get(CrewRelation, relation_id)
    if not rel:
        raise HTTPException(404, "Relation nicht gefunden")
    await session.delete(rel)
    await session.commit()


# ---- Boss-Info aus Zusatz-Channel ----


@router.get("/{crew_id}/boss_info")
async def get_crew_boss_info(crew_id: int, session: AsyncSession = Depends(get_session)):
    """Liest den Zusatzinfo-Channel der Crew via Bot, mappt Boss-Texte auf
    aktive (nicht-archivierte, gesendete) Missionen anhand des Zeitfensters
    zwischen Mission.sent_at und der nächsten sent_at."""
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    if not crew.info_channel_id:
        return []

    res = await session.execute(
        select(Mission)
        .where(
            Mission.crew_id == crew_id,
            Mission.archived_at.is_(None),
            Mission.sent_at.is_not(None),
        )
        .order_by(Mission.sent_at)
    )
    missions = list(res.scalars().all())
    if not missions:
        return []

    earliest = missions[0].sent_at

    async with httpx.AsyncClient(timeout=15.0) as cli:
        try:
            r = await cli.post(
                "http://127.0.0.1:8001/read_channel",
                json={
                    "channel_id": crew.info_channel_id,
                    "after_iso": earliest.isoformat(),
                    "limit": 100,
                },
            )
        except Exception as exc:
            raise HTTPException(503, f"Bot nicht erreichbar: {exc}") from exc

    if r.status_code >= 400:
        raise HTTPException(502, f"Bot Fehler: {r.text}")

    bot_msgs = r.json()

    out: list[dict] = []
    for i, m in enumerate(missions):
        start = m.sent_at
        end = missions[i + 1].sent_at if i + 1 < len(missions) else None
        bucket: list[dict] = []
        for bm in bot_msgs:
            try:
                ts = datetime.fromisoformat(bm["posted_at"])
            except (KeyError, ValueError):
                continue
            if ts < start:
                continue
            if end and ts >= end:
                continue
            bucket.append(bm)
        out.append({"mission_id": m.id, "messages": bucket})

    return out


# ---- Crime-Business: KI-Vorschau + Senden an separaten Channel ----

@router.post("/{crew_id}/crime-business/preview")
async def preview_crime_business(
    crew_id: int,
    payload: CrimeBusinessSendRequest,
    session: AsyncSession = Depends(get_session),
):
    """Generiert den Crime-Business-Briefing-Text per KI im Big-Boss-Stil,
    OHNE ihn an Discord zu senden. Liefert den Text zur Anzeige + Bearbeitung
    im Frontend zurueck. Der eigentliche Send-Schritt erfolgt anschliessend
    ueber /crime-business/post."""
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    if not (crew.crime_business or "").strip():
        raise HTTPException(400, "Keine Crime-Business-Beschreibung hinterlegt")

    # AI-Provider aufbauen (gleiche Konfiguration wie Mission-Generator)
    keys = {
        "anthropic": await settings_get_value(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get_value(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get_value(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get_value(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = payload.provider or await settings_get_value(
        session, "default_provider", settings.default_ai_provider
    )
    provider = await get_provider(provider_name, keys=keys, models=models)

    system_prompt, user_prompt = build_crime_business_briefing_prompt(
        crew_name=crew.name,
        crew_story=crew.story_background or "",
        crime_business=crew.crime_business,
    )

    try:
        text = await provider.generate(user_prompt, model=payload.model, system_prompt=system_prompt)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    text = (text or "").strip()

    # Pflicht-Eroeffnung garantieren — auch wenn die KI sie weglaesst oder leicht
    # umformuliert. Wir pruefen auf den exakten Wortlaut; falls die KI eine eigene
    # Eroeffnung gewaehlt hat, wird sie durch die feste ersetzt/vorangestellt.
    FIXED_OPENING = (
        "Ihr wollt wissen, mit welchem Business ich euch betreuen werde: Dann passt gut auf..."
    )
    if not text.startswith(FIXED_OPENING):
        # Wenn ein aehnlicher Satz am Anfang steht (KI hat es umformuliert), erste
        # Zeile entfernen und durch FIXED ersetzen. Heuristik: erste Zeile enthaelt
        # 'Business' oder 'betreuen' -> ersetzen.
        first_line, _, rest = text.partition("\n")
        if "business" in first_line.lower() or "betreuen" in first_line.lower():
            text = f"{FIXED_OPENING}\n\n{rest.lstrip()}"
        else:
            text = f"{FIXED_OPENING}\n\n{text}"

    # Sicherheits-Trim fuer Discord (2000 Zeichen max — kleines Polster)
    if len(text) > 1990:
        text = text[:1985] + "…"

    return {
        "ok": True,
        "ai_provider": provider.name,
        "ai_model": payload.model or "",
        "char_count": len(text),
        "text": text,
    }


@router.post("/{crew_id}/crime-business/post")
async def post_crime_business(
    crew_id: int,
    payload: CrimeBusinessPostRequest,
    session: AsyncSession = Depends(get_session),
):
    """Postet einen (ggf. vom User editierten) Briefing-Text an den
    crime_business_channel_id der Crew. Keine KI-Generierung — der Text
    kommt vom Frontend nach Preview/Edit."""
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")
    if not (crew.crime_business_channel_id or "").strip():
        raise HTTPException(400, "Kein Crime-Business-Channel hinterlegt")

    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(400, "Content darf nicht leer sein")
    if len(content) > 1990:
        raise HTTPException(400, f"Content zu lang ({len(content)} > 1990 Zeichen)")

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                "http://127.0.0.1:8001/post_text",
                json={"channel_id": crew.crime_business_channel_id, "content": content},
            )
        if r.status_code >= 400:
            try:
                detail = r.json().get("error", r.text)
            except Exception:
                detail = r.text
            raise HTTPException(r.status_code, f"Bot-Fehler: {detail}")
        bot_result = r.json()
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Bot nicht erreichbar: {exc}") from exc

    return {
        "ok": True,
        "char_count": len(content),
        "discord_message_id": bot_result.get("message_id"),
    }


# ==================================================================
# KI-Enrichment: Story + Business + Farbe + Rivalitaeten fuer neue
# oder unvollstaendige Crews per KI vorschlagen lassen
# ==================================================================


async def _load_enrich_context(
    session: AsyncSession, crew: Crew
) -> tuple[list[dict], list[dict]]:
    """Laedt Kontext fuer die Enrichment-KI: Crews im selben Stadtteil (fuer
    Rivalitaets-Vorschlaege priorisieren) + alle anderen Crews (fuer optionale
    Ueberkreuz-Beziehungen)."""
    q = await session.execute(select(Crew).order_by(Crew.name))
    all_crews = q.scalars().all()

    same_district: list[dict] = []
    all_summary: list[dict] = []
    for c in all_crews:
        if c.id == crew.id:
            continue
        summary = {
            "id": c.id,
            "name": c.name,
            "district": c.district or "",
        }
        all_summary.append(summary)
        if crew.district and c.district == crew.district:
            same_district.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "story_background": c.story_background or "",
                    "crime_business": c.crime_business or "",
                }
            )
    return same_district, all_summary


@router.post("/{crew_id}/enrich/preview", response_model=CrewEnrichPreviewResponse)
async def enrich_crew_preview(
    crew_id: int,
    payload: CrewEnrichRequest,
    session: AsyncSession = Depends(get_session),
):
    """KI-Vorschlaege fuer eine bestehende Crew generieren. Gibt Story +
    Business + Farbe + Rivalitaeten/Verbuendeten-Vorschlaege zurueck. Der User
    reviewt und ruft dann /apply auf, um die gewuenschten Felder zu uebernehmen.

    Wird sowohl von Variante A (Wizard: Crew wird VOR dem Enrich mit
    minimalen Feldern angelegt) als auch von Variante B (existierende
    Crew mit leeren Feldern) genutzt.
    """
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    keys = {
        "anthropic": await settings_get_value(
            session, "anthropic_api_key", settings.anthropic_api_key
        ),
        "openai": await settings_get_value(
            session, "openai_api_key", settings.openai_api_key
        ),
    }
    models = {
        "claude": await settings_get_value(
            session, "default_claude_model", settings.default_claude_model
        ),
        "openai": await settings_get_value(
            session, "default_openai_model", settings.default_openai_model
        ),
    }
    provider_name = payload.provider or await settings_get_value(
        session, "default_provider", settings.default_ai_provider
    )
    provider = await get_provider(provider_name, keys=keys, models=models)

    same_district, all_summary = await _load_enrich_context(session, crew)

    system_prompt, user_prompt = build_crew_enrichment_prompt(
        crew_name=crew.name,
        district=crew.district or "",
        hint=payload.hint,
        existing_crews_in_district=same_district,
        all_crews_summary=all_summary,
    )

    try:
        text = await provider.generate(
            user_prompt, model=payload.model, system_prompt=system_prompt
        )
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    raw = (text or "").strip()

    # JSON-Parsing mit Fallback (Markdown-Fence entfernen wenn vorhanden)
    parsed: dict | None = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = raw[start : end + 1]
            try:
                parsed = json.loads(snippet)
            except json.JSONDecodeError:
                parsed = None

    if parsed is None or not isinstance(parsed, dict):
        return CrewEnrichPreviewResponse(
            ok=False,
            ai_provider=provider.name,
            ai_model=payload.model or "",
            raw=raw,
        )

    # Namen aus all_summary in Rivalitaets-Vorschlaege einfuellen (fuer UI)
    id_to_name = {c["id"]: c["name"] for c in all_summary}

    def normalize_relations(items: list) -> list[CrewEnrichRelationSuggestion]:
        out: list[CrewEnrichRelationSuggestion] = []
        if not isinstance(items, list):
            return out
        for it in items[:6]:  # max 6 pro Kategorie
            if not isinstance(it, dict):
                continue
            cid = it.get("crew_id")
            if not isinstance(cid, int) or cid not in id_to_name:
                continue
            rt = str(it.get("relation_type", "rival")).strip().lower()
            if rt not in {"rival", "hostile", "allied", "business", "neutral"}:
                rt = "rival"
            out.append(
                CrewEnrichRelationSuggestion(
                    crew_id=cid,
                    crew_name=id_to_name[cid],
                    relation_type=rt,
                    notes=str(it.get("notes", "")).strip(),
                )
            )
        return out

    color_hex = str(parsed.get("color_hex", "")).strip()
    if not (
        color_hex.startswith("#")
        and len(color_hex) == 7
        and all(c in "0123456789abcdefABCDEF" for c in color_hex[1:])
    ):
        color_hex = "#b91c1c"

    return CrewEnrichPreviewResponse(
        ok=True,
        ai_provider=provider.name,
        ai_model=payload.model or "",
        story_background=str(parsed.get("story_background", "")).strip(),
        crime_business=str(parsed.get("crime_business", "")).strip(),
        color_hex=color_hex,
        rivalries=normalize_relations(parsed.get("rivalries", [])),
        allies=normalize_relations(parsed.get("allies", [])),
        raw="",  # bei Erfolg nicht mitschicken
    )


@router.post("/{crew_id}/enrich/apply")
async def enrich_crew_apply(
    crew_id: int,
    payload: CrewEnrichApplyRequest,
    session: AsyncSession = Depends(get_session),
):
    """User hat Preview reviewt und uebernimmt selektiv Felder + Relationen.
    Bestehende Werte in nicht uebergebenen Feldern bleiben erhalten.
    Beziehungen werden hinzugefuegt (bestehende Beziehungen zu denselben
    Crews werden per Update ueberschrieben).
    """
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    changed_fields: list[str] = []
    if payload.story_background is not None:
        crew.story_background = payload.story_background
        changed_fields.append("story_background")
    if payload.crime_business is not None:
        crew.crime_business = payload.crime_business
        changed_fields.append("crime_business")
    if payload.color_hex is not None:
        crew.color_hex = payload.color_hex
        changed_fields.append("color_hex")

    added_rels = 0
    updated_rels = 0
    all_rel_suggestions = list(payload.apply_rivalries) + list(payload.apply_allies)
    for suggestion in all_rel_suggestions:
        other = await session.get(Crew, suggestion.crew_id)
        if not other or other.id == crew.id:
            continue

        # Bestehende Beziehung suchen (in beide Richtungen)
        existing_q = await session.execute(
            select(CrewRelation).where(
                (
                    (CrewRelation.crew_a_id == crew.id)
                    & (CrewRelation.crew_b_id == other.id)
                )
                | (
                    (CrewRelation.crew_a_id == other.id)
                    & (CrewRelation.crew_b_id == crew.id)
                )
            )
        )
        existing = existing_q.scalar_one_or_none()

        try:
            rt = RelationType(suggestion.relation_type)
        except ValueError:
            rt = RelationType.NEUTRAL

        if existing:
            existing.relation_type = rt
            if suggestion.notes:
                existing.notes = suggestion.notes
            updated_rels += 1
        else:
            new_rel = CrewRelation(
                crew_a_id=crew.id,
                crew_b_id=other.id,
                relation_type=rt,
                notes=suggestion.notes or "",
            )
            session.add(new_rel)
            added_rels += 1

    await session.commit()
    await session.refresh(crew)

    return {
        "ok": True,
        "crew_id": crew.id,
        "changed_fields": changed_fields,
        "added_relations": added_rels,
        "updated_relations": updated_rels,
    }

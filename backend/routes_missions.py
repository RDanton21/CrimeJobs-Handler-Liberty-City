import asyncio
import json
import random
import re
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4


async def _resolve_active_system_prompt(session) -> str | None:
    """Aktiver SystemPrompt aus DB > legacy settings.system_prompt > None (Default greift)."""
    res = await session.execute(select(SystemPrompt).where(SystemPrompt.is_active.is_(True)))
    sp = res.scalar_one_or_none()
    if sp and sp.text.strip():
        return sp.text
    legacy = await settings_get(session, "system_prompt", "")
    return legacy or None


def _normalize_naive_utc(dt: datetime | None) -> datetime | None:
    """Pydantic kann tz-aware datetimes liefern (z.B. ISO mit Z-Suffix).
    SQLite DATETIME ist naive — wir konvertieren zu naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

import aiofiles
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import get_provider
from .auth import require_admin
from .config import settings
from .db import get_session
from .models import Crew, CrewRelation, Mission, MissionStatus, SystemPrompt, Top3TitlePoolMessage
from .personnel_ai import generate_personnel_brief as ai_personnel_brief


# Matched z.B. "Vorgang 091-14.", "Vorgang 047-B.", "Vorgang 5/2026.",
# auch mit Markdown-Quote-Prefix ">" davor und auch wenn direkt mit dem
# ersten Satz auf derselben Zeile fortgesetzt wird.
_CASE_NUMBER_PREFIX_RE = re.compile(
    r"^\s*>?\s*(Vorgang|Akte|Aktenzeichen|Fall)\s*#?\s*[\w\d/\-–]+\.?\s+",
    re.IGNORECASE,
)

# Matched am ENDE des Textes Konstruktionen wie
# "👍 oder 👎.", "👍/👎", "👎 oder 👍 oder ❌."
# — die KI hängt das als pseudo-Call-to-Action an, obwohl die Reaktionen
# eh über Discord-Reactions kommen.
_REACTION_TAIL_RE = re.compile(
    r"[\s\n]*[👍👎❌](?:[\s/.,·]*(?:oder|or)?[\s/.,·]*[👍👎❌])+\s*[.!]?\s*\Z",
    re.IGNORECASE,
)


def _strip_case_number_prefix(text: str) -> str:
    """Entfernt führendes „Vorgang XYZ-XX." aus KI-generierten Texten.
    Die KI hängt das gerne als Pseudo-Aktennummer dran, obwohl der
    System-Prompt es nicht verlangt. Sicherheitsnetz, das unabhängig
    vom aktiven System-Prompt funktioniert."""
    if not text:
        return text
    return _CASE_NUMBER_PREFIX_RE.sub("", text, count=1).lstrip()


def _strip_reaction_tail(text: str) -> str:
    """Entfernt am Ende stehende „👍 oder 👎."-Konstruktionen — die
    Reaktionen kommen ohnehin über Discord-Emoji-Reactions, der Hinweis
    im Text ist Lärm."""
    if not text:
        return text
    return _REACTION_TAIL_RE.sub("", text).rstrip()


def _clean_ai_output(text: str) -> str:
    """Kombi: Aktennummer am Anfang + Reaktions-Aufforderung am Ende +
    ausgeschriebene Zahlen in Ziffern."""
    return _digitize_german_numbers(
        _strip_reaction_tail(_strip_case_number_prefix(text))
    )


# Deutsche Zahlwörter → Ziffern. Wird auf jeden KI-Output angewandt, weil
# die KI gerne literarisch ausschreibt („acht Minuten") auch wenn der
# System-Prompt es verbietet. Defensive Linie 2.
def _build_german_number_map() -> dict[str, int]:
    base = {
        "zwei": 2, "zwo": 2, "drei": 3, "vier": 4, "fünf": 5,
        "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
        "zehn": 10, "elf": 11, "zwölf": 12,
        "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15,
        "sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
        "zwanzig": 20, "dreißig": 30, "vierzig": 40, "fünfzig": 50,
        "sechzig": 60, "siebzig": 70, "achtzig": 80, "neunzig": 90,
        "hundert": 100, "tausend": 1000,
    }
    tens = ["zwanzig", "dreißig", "vierzig", "fünfzig",
            "sechzig", "siebzig", "achtzig", "neunzig"]
    ones = ["ein", "zwei", "drei", "vier", "fünf",
            "sechs", "sieben", "acht", "neun"]
    # Komposita 21–99 ("einundzwanzig" .. "neunundneunzig")
    for t_idx, t_word in enumerate(tens, start=2):
        for o_idx, o_word in enumerate(ones, start=1):
            base[f"{o_word}und{t_word}"] = t_idx * 10 + o_idx
    return base


_NUM_WORDS = _build_german_number_map()
# Sortieren nach Länge absteigend — sonst würde z.B. "drei" in
# "dreiundzwanzig" zuerst greifen und Müll erzeugen.
_NUM_PATTERN = re.compile(
    r"\b(" + "|".join(
        re.escape(w) for w, _ in sorted(_NUM_WORDS.items(),
                                       key=lambda kv: -len(kv[0]))
    ) + r")\b",
    re.IGNORECASE,
)


def _digitize_german_numbers(text: str) -> str:
    """Wandelt ausgeschriebene deutsche Zahlwörter in Ziffern um.
    Erkennt 2–99 plus 'hundert'/'tausend'. Lässt 'ein/eine/einen' bewusst
    in Ruhe (zu hohes Risiko, einen Artikel zu zerstören)."""
    if not text:
        return text

    def _replace(m: re.Match) -> str:
        word_lower = m.group(1).lower()
        digit = _NUM_WORDS.get(word_lower)
        return str(digit) if digit is not None else m.group(0)

    return _NUM_PATTERN.sub(_replace, text)


async def _resolve_default_provider(session: AsyncSession):
    """Lädt Default-Provider aus Settings — für Sub-Calls wie Personal-Brief
    in /manual und /bulk_send, wo der User keinen Provider explizit angibt."""
    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = await settings_get(session, "default_provider", settings.default_ai_provider)
    try:
        return await get_provider(provider_name, keys=keys, models=models)
    except Exception:
        return None


async def _generate_personnel_safe(session: AsyncSession, mission_text: str,
                                   crew_name: str, crew_district: str) -> str:
    """Defensiv: lädt Default-Provider und ruft Personal-AI. Bei jedem
    Fehler leerer String — Mission soll NICHT blockieren wegen Personal."""
    if not mission_text or not mission_text.strip():
        return ""
    provider = await _resolve_default_provider(session)
    if provider is None:
        return ""
    return await ai_personnel_brief(provider, mission_text, crew_name, crew_district)
from .prompts import (
    MissionContext,
    build_mission_suggestions_prompt,
    build_rewrite_prompt,
    build_user_prompt,
)
from .schemas import (
    BulkSendRequest,
    MissionGenerateRequest,
    MissionManualRequest,
    MissionOut,
    MissionRewriteRequest,
    MissionSuggestionsRequest,
    MissionUpdate,
    RankingPostRequest,
    StatusOverrideRequest,
)
from .settings_store import get as settings_get

router = APIRouter(prefix="/api/missions", tags=["missions"], dependencies=[Depends(require_admin)])


async def _load_context(session: AsyncSession, crew: Crew, extra: str) -> MissionContext:
    rel_q = await session.execute(
        select(CrewRelation).where(
            (CrewRelation.crew_a_id == crew.id) | (CrewRelation.crew_b_id == crew.id)
        )
    )
    relations: list[dict] = []
    for r in rel_q.scalars().all():
        other_id = r.crew_b_id if r.crew_a_id == crew.id else r.crew_a_id
        other = await session.get(Crew, other_id)
        if other is None:
            continue
        relations.append(
            {
                "name": other.name,
                "story": other.story_background,
                "relation_type": r.relation_type.value,
                "notes": r.notes,
            }
        )

    hist_q = await session.execute(
        select(Mission)
        .where(
            Mission.crew_id == crew.id,
            Mission.status != MissionStatus.DRAFT,
            Mission.archived_at.is_(None),
        )
        .order_by(desc(Mission.created_at))
        .limit(5)
    )
    history: list[dict] = []
    for m in hist_q.scalars().all():
        history.append(
            {
                "content": m.content_final or m.content_generated,
                "status": m.status.value,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
        )

    return MissionContext(
        crew_name=crew.name,
        crew_story=crew.story_background,
        related_crews=relations,
        history=history,
        extra_instructions=extra,
        crime_business=getattr(crew, "crime_business", "") or "",
    )


@router.post("/generate", response_model=MissionOut)
async def generate_mission(
    payload: MissionGenerateRequest, session: AsyncSession = Depends(get_session)
):
    crew = await session.get(Crew, payload.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = payload.provider or await settings_get(
        session, "default_provider", settings.default_ai_provider
    )

    provider = await get_provider(provider_name, keys=keys, models=models)

    ctx = await _load_context(session, crew, payload.extra_instructions)
    user_prompt = build_user_prompt(ctx)
    system_prompt_val = await _resolve_active_system_prompt(session)

    try:
        text = await provider.generate(user_prompt, model=payload.model, system_prompt=system_prompt_val)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc
    text = _clean_ai_output(text)

    deadline_at = None
    if payload.deadline_minutes and payload.deadline_minutes > 0:
        deadline_at = datetime.utcnow() + timedelta(minutes=payload.deadline_minutes)

    final_text = text
    if payload.append_text and payload.append_text.strip():
        final_text = f"{text}\n\n---\n\n{payload.append_text.strip()}"

    # KI-Vorschlag fürs Personal-Briefing (defensiv: bei Fehler leer)
    personnel = await ai_personnel_brief(
        provider, final_text, crew.name, crew.district or "", model=payload.model
    )

    mission = Mission(
        crew_id=crew.id,
        ai_provider=provider.name,
        ai_model=payload.model or "",
        prompt_used=user_prompt,
        content_generated=text,
        content_final=final_text,
        discord_channel_id=crew.discord_channel_id,
        status=MissionStatus.DRAFT,
        deadline_at=deadline_at,
        scheduled_send_at=_normalize_naive_utc(payload.scheduled_send_at),
        personnel_brief=personnel,
        personnel_updated_at=datetime.utcnow() if personnel else None,
    )
    session.add(mission)
    await session.commit()
    await session.refresh(mission)
    return mission


@router.post("/rewrite", response_model=MissionOut)
async def rewrite_mission(
    payload: MissionRewriteRequest, session: AsyncSession = Depends(get_session)
):
    if not payload.raw_input.strip():
        raise HTTPException(400, "raw_input darf nicht leer sein")

    crew = await session.get(Crew, payload.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = payload.provider or await settings_get(
        session, "default_provider", settings.default_ai_provider
    )

    provider = await get_provider(provider_name, keys=keys, models=models)

    ctx = await _load_context(session, crew, payload.extra_instructions)
    user_prompt = build_rewrite_prompt(ctx, payload.raw_input)
    system_prompt_val = await _resolve_active_system_prompt(session)

    try:
        text = await provider.generate(user_prompt, model=payload.model, system_prompt=system_prompt_val)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc
    text = _clean_ai_output(text)

    deadline_at = None
    if payload.deadline_minutes and payload.deadline_minutes > 0:
        deadline_at = datetime.utcnow() + timedelta(minutes=payload.deadline_minutes)

    final_text = text
    if payload.append_text and payload.append_text.strip():
        final_text = f"{text}\n\n---\n\n{payload.append_text.strip()}"

    # KI-Vorschlag fürs Personal-Briefing (defensiv: bei Fehler leer)
    personnel = await ai_personnel_brief(
        provider, final_text, crew.name, crew.district or "", model=payload.model
    )

    mission = Mission(
        crew_id=crew.id,
        ai_provider=provider.name,
        ai_model=payload.model or "",
        prompt_used=user_prompt,
        content_generated=text,
        content_final=final_text,
        discord_channel_id=crew.discord_channel_id,
        status=MissionStatus.DRAFT,
        deadline_at=deadline_at,
        scheduled_send_at=_normalize_naive_utc(payload.scheduled_send_at),
        personnel_brief=personnel,
        personnel_updated_at=datetime.utcnow() if personnel else None,
    )
    session.add(mission)
    await session.commit()
    await session.refresh(mission)
    return mission


@router.post("/suggestions/{crew_id}")
async def mission_suggestions(
    crew_id: int,
    payload: MissionSuggestionsRequest,
    session: AsyncSession = Depends(get_session),
):
    """Liefert 3 KI-Vorschlaege fuer den naechsten Auftrag der Crew. Basis ist
    die letzte Reaktion: '👍 erledigt' -> Eskalation, '👎 fehlgeschlagen' ->
    Tonwechsel, '❌ nicht ausfuehrbar' -> realistischere Alternativen, kein
    vorheriger Auftrag -> frischer Einstieg.

    Speichert KEINE Mission — der User waehlt einen Vorschlag im Frontend
    und sendet ihn dann manuell via /manual oder /rewrite weiter.
    """
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    provider_override = payload.provider
    model_override = payload.model

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = provider_override or await settings_get(
        session, "default_provider", settings.default_ai_provider
    )
    provider = await get_provider(provider_name, keys=keys, models=models)

    ctx = await _load_context(session, crew, "")
    system_prompt, user_prompt = build_mission_suggestions_prompt(ctx)

    try:
        text = await provider.generate(user_prompt, model=model_override, system_prompt=system_prompt)
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    # KI-Antwort als JSON parsen. Wenn die KI Markdown-Fences oder Erklaerungen
    # mitschickt, versuchen wir die JSON-Liste innerhalb des Strings zu finden.
    raw = (text or "").strip()
    suggestions: list[dict] = []
    try:
        suggestions = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: suche das erste '[' ... ']' Substring
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1 and end > start:
            snippet = raw[start : end + 1]
            try:
                suggestions = json.loads(snippet)
            except json.JSONDecodeError:
                suggestions = []

    # Validieren + auf 3 Eintraege normalisieren
    cleaned: list[dict] = []
    if isinstance(suggestions, list):
        for s in suggestions[:3]:
            if not isinstance(s, dict):
                continue
            title = str(s.get("title", "")).strip()
            content = str(s.get("content", "")).strip()
            if title or content:
                cleaned.append({"title": title or "Vorschlag", "content": content})

    last_status = ""
    if ctx.history:
        last_status = ctx.history[0].get("status", "")

    return {
        "ok": True,
        "ai_provider": provider.name,
        "ai_model": model_override or "",
        "last_status": last_status,
        "suggestions": cleaned,
        "raw": raw if not cleaned else "",  # Debug-Hilfe falls Parsing fehlschlaegt
    }


@router.post("/manual", response_model=MissionOut)
async def create_manual_mission(
    payload: MissionManualRequest, session: AsyncSession = Depends(get_session)
):
    """Erstellt eine Mission ohne KI-Generierung. Inhalt wird 1:1 als content_final
    übernommen — gedacht für Klartext-Aufträge mit Adressen, GPS, etc."""
    if not payload.content.strip():
        raise HTTPException(400, "content darf nicht leer sein")

    crew = await session.get(Crew, payload.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    deadline_at = None
    if payload.deadline_minutes and payload.deadline_minutes > 0:
        deadline_at = datetime.utcnow() + timedelta(minutes=payload.deadline_minutes)

    text = payload.content.strip()
    # KEIN automatischer Personal-Brief fuer manuelle Missions:
    # der User sendet einen klaren Klartext-Auftrag (z.B. nur Zusatzinfos
    # wie Adresse/GPS), bekommt sonst aber ungewollt einen KI-Personal-
    # Embed im Admin-Channel. Wer Personal will, generiert es im Widget
    # ueber den 'KI-Vorschlag'-Button nachtraeglich.
    # Ziel-Channel: wenn crew.info_channel_id gesetzt ist -> Zusatzinfo-Channel
    # (Boss-Feedback), sonst der Haupt-Auftrag-Channel. So landen Adressen /
    # GPS nicht als vermeintlich neuer Auftrag im quests-Kanal.
    target_channel = crew.info_channel_id or crew.discord_channel_id
    mission = Mission(
        crew_id=crew.id,
        ai_provider="manual",
        ai_model="",
        prompt_used="",
        content_generated=text,
        content_final=text,
        discord_channel_id=target_channel,
        status=MissionStatus.DRAFT,
        deadline_at=deadline_at,
        scheduled_send_at=_normalize_naive_utc(payload.scheduled_send_at),
        personnel_brief="",
        personnel_updated_at=None,
    )
    session.add(mission)
    await session.commit()
    await session.refresh(mission)
    return mission


@router.post("/bulk_send")
async def bulk_send(
    payload: BulkSendRequest, session: AsyncSession = Depends(get_session)
):
    """Bulk-Variante: erstellt für jede Crew eine manuelle Mission und sendet
    sie parallel via Bot (5 gleichzeitig). Returns Liste mit Status pro Crew."""
    text = payload.content.strip()
    if not text:
        raise HTTPException(400, "content darf nicht leer sein")
    if not payload.crew_ids:
        return []

    deadline_at = None
    if payload.deadline_minutes and payload.deadline_minutes > 0:
        deadline_at = datetime.utcnow() + timedelta(minutes=payload.deadline_minutes)
    schedule_at = _normalize_naive_utc(payload.scheduled_send_at)

    # KI-Vorschlag fürs Personal-Briefing — einmal generieren mit erster
    # Crew als Kontext, dann allen Missions zuweisen (sonst 21 KI-Calls).
    # Der User kann pro Crew im Dashboard-Widget nachschärfen.
    personnel = ""
    first_crew = None
    for cid in payload.crew_ids:
        first_crew = await session.get(Crew, cid)
        if first_crew:
            break
    if first_crew:
        personnel = await _generate_personnel_safe(
            session, text, first_crew.name, first_crew.district or ""
        )
    personnel_stamp = datetime.utcnow() if personnel else None

    # Phase 1: Missions sequentiell anlegen + Names sammeln
    creations: list[dict] = []
    for cid in payload.crew_ids:
        crew = await session.get(Crew, cid)
        if not crew:
            creations.append({"crew_id": cid, "name": f"#{cid}", "mission": None,
                              "error": "Crew nicht gefunden"})
            continue
        mission = Mission(
            crew_id=crew.id,
            ai_provider="manual",
            ai_model="",
            prompt_used="",
            content_generated=text,
            content_final=text,
            discord_channel_id=crew.discord_channel_id,
            status=MissionStatus.DRAFT,
            deadline_at=deadline_at,
            scheduled_send_at=schedule_at,
            personnel_brief=personnel,
            personnel_updated_at=personnel_stamp,
        )
        session.add(mission)
        creations.append({"crew_id": cid, "name": crew.name, "mission": mission, "error": None})
    await session.commit()
    for entry in creations:
        if entry["mission"]:
            await session.refresh(entry["mission"])

    # Wenn Schedule: nicht jetzt senden, Bot picks up
    if schedule_at:
        return [
            {
                "crew_id": e["crew_id"], "name": e["name"],
                "ok": e["error"] is None,
                "mission_id": e["mission"].id if e["mission"] else None,
                "scheduled": True,
                "error": e["error"],
            }
            for e in creations
        ]

    # Phase 2: parallele Bot-Sends, max 5 gleichzeitig
    sem = asyncio.Semaphore(5)

    async def _send_one(entry: dict) -> dict:
        if entry["error"] is not None or entry["mission"] is None:
            return {
                "crew_id": entry["crew_id"], "name": entry["name"], "ok": False,
                "mission_id": None, "error": entry["error"] or "create failed",
            }
        m = entry["mission"]
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=60.0) as cli:
                    r = await cli.post(
                        f"{settings.bot_api_url}/send", json={"mission_id": m.id}
                    )
                if r.status_code >= 400:
                    return {
                        "crew_id": entry["crew_id"], "name": entry["name"], "ok": False,
                        "mission_id": m.id, "error": f"Bot {r.status_code}: {r.text[:200]}",
                    }
                return {
                    "crew_id": entry["crew_id"], "name": entry["name"], "ok": True,
                    "mission_id": m.id, "error": None,
                }
            except Exception as exc:
                return {
                    "crew_id": entry["crew_id"], "name": entry["name"], "ok": False,
                    "mission_id": m.id, "error": str(exc),
                }

    return await asyncio.gather(*[_send_one(e) for e in creations])


@router.get("", response_model=list[MissionOut])
async def list_missions(
    crew_id: int | None = None,
    archived: bool = False,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    q = select(Mission).order_by(desc(Mission.created_at)).limit(limit)
    if crew_id is not None:
        q = q.where(Mission.crew_id == crew_id)
    if archived:
        q = q.where(Mission.archived_at.is_not(None))
    else:
        q = q.where(Mission.archived_at.is_(None))
    result = await session.execute(q)
    return result.scalars().all()


RANKING_POINTS = {
    MissionStatus.APPROVED: 2,
    MissionStatus.REJECTED: -1,
    MissionStatus.CANCELLED: 0,
    MissionStatus.PENDING: 0,
    MissionStatus.DRAFT: 0,
}


@router.get("/ranking")
async def mission_ranking(
    since: datetime | None = None,
    crime_only: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """Performance-Ranking pro Crew + Stadtteil-Aggregat.

    Punkte: approved=+2, rejected=-1, cancelled/pending/draft=0.
    Bei crime_only=true werden Crews aus FIRMS_TO_CREATE ausgeschlossen
    (13 Zivil-Firmen werden nicht gerankt)."""
    # Lokaler Import um circular-import zu vermeiden (FIRMS_TO_CREATE liegt im
    # seed-Skript). Sicher, da seed_event_lore.py keine Bot/Backend-Routen importiert.
    from .seed_event_lore import FIRMS_TO_CREATE
    firm_names = {name for name, _district in FIRMS_TO_CREATE}

    # Wenn since=None (= „Gesamt"): Reset-Stichtag aus Settings beachten,
    # damit das Ranking nach einem Reset bei 0 startet.
    if since is None:
        reset_iso = (await settings_get(session, "ranking_reset_at", "")).strip()
        if reset_iso:
            try:
                since = datetime.fromisoformat(reset_iso)
            except (ValueError, TypeError):
                pass

    # Alle Crews laden (fuer Metadata wie name/district/color_hex)
    crews_result = await session.execute(select(Crew).order_by(Crew.id))
    crews: list[Crew] = list(crews_result.scalars().all())

    if crime_only:
        crews = [c for c in crews if c.name not in firm_names]

    crew_ids = [c.id for c in crews]
    if not crew_ids:
        return {
            "crews": [],
            "districts": [],
            "since": since.isoformat() if since else None,
            "crime_only": crime_only,
        }

    # Counts pro (crew_id, status) aggregieren
    q = (
        select(Mission.crew_id, Mission.status, func.count(Mission.id))
        .where(Mission.crew_id.in_(crew_ids))
        .group_by(Mission.crew_id, Mission.status)
    )
    if since is not None:
        q = q.where(Mission.created_at >= since)
    rows = (await session.execute(q)).all()

    # In dict[crew_id] = {status: count, ...}
    by_crew: dict[int, dict[str, int]] = {
        cid: {s.value: 0 for s in MissionStatus} for cid in crew_ids
    }
    for crew_id, status, count in rows:
        key = status.value if hasattr(status, "value") else str(status)
        by_crew[crew_id][key] = count

    crew_entries: list[dict] = []
    for c in crews:
        counts = by_crew[c.id]
        approved = counts.get(MissionStatus.APPROVED.value, 0)
        rejected = counts.get(MissionStatus.REJECTED.value, 0)
        cancelled = counts.get(MissionStatus.CANCELLED.value, 0)
        pending = counts.get(MissionStatus.PENDING.value, 0)
        draft = counts.get(MissionStatus.DRAFT.value, 0)
        bonus = int(c.bonus_points or 0)
        mission_points = approved * 2 + rejected * -1
        points = mission_points + bonus
        total = approved + rejected + cancelled + pending + draft
        crew_entries.append({
            "crew_id": c.id,
            "name": c.name,
            "district": c.district or "",
            "color_hex": c.color_hex,
            "approved": approved,
            "rejected": rejected,
            "cancelled": cancelled,
            "pending": pending,
            "total": total,
            "points": points,
            "bonus_points": bonus,
            "mission_points": mission_points,
        })
    crew_entries.sort(key=lambda e: (-e["points"], -e["approved"], e["name"]))

    # Stadtteil-Aggregat
    district_acc: dict[str, dict[str, int]] = {}
    for e in crew_entries:
        d = e["district"] or "(ohne)"
        bucket = district_acc.setdefault(d, {
            "name": d, "points": 0, "approved": 0, "rejected": 0,
            "cancelled": 0, "pending": 0, "crew_count": 0,
        })
        bucket["points"] += e["points"]
        bucket["approved"] += e["approved"]
        bucket["rejected"] += e["rejected"]
        bucket["cancelled"] += e["cancelled"]
        bucket["pending"] += e["pending"]
        bucket["crew_count"] += 1
    district_entries = list(district_acc.values())
    district_entries.sort(key=lambda e: (-e["points"], -e["approved"], e["name"]))

    return {
        "crews": crew_entries,
        "districts": district_entries,
        "since": since.isoformat() if since else None,
        "crime_only": crime_only,
    }


EVENT_START_DATE = date(2026, 8, 7)
EVENT_END_DATE = date(2026, 8, 16)


def _event_day_label(now: datetime | None = None) -> str:
    """Liefert z.B. 'Tag 3 - 09.08.2026' für das aktuelle Event-Datum.
    Vor Event-Start: 'Pre-Event (noch X Tage) - DD.MM.YYYY'.
    Nach Event-Ende: 'Post-Event - DD.MM.YYYY'."""
    today = (now or datetime.now()).date()
    date_str = today.strftime("%d.%m.%Y")
    if today < EVENT_START_DATE:
        days_until = (EVENT_START_DATE - today).days
        suffix = "morgen geht es los" if days_until == 1 else f"noch {days_until} Tage"
        return f"Pre-Event ({suffix}) - {date_str}"
    if today > EVENT_END_DATE:
        return f"Post-Event - {date_str}"
    day_num = (today - EVENT_START_DATE).days + 1
    return f"Tag {day_num} - {date_str}"


def _range_label_for(since: datetime | None) -> str:
    if since is None:
        return "Gesamt"
    delta = datetime.utcnow() - since
    if delta.total_seconds() < 26 * 3600:  # 26h Toleranz für "heute"
        return "Heute"
    if delta.days <= 7:
        return "Letzte 7 Tage"
    if delta.days <= 30:
        return "Letzte 30 Tage"
    return f"Seit {since.strftime('%d.%m.%Y')}"


def _build_ranking_embed(
    ranking: dict,
    *,
    since: datetime | None,
    crime_only: bool,
    title: str,
    mode: str = "full",
    top_n: int = 21,
    show_district_aggregate: bool = True,
) -> dict:
    """Baut das Discord-Embed im Podest-Style (Design A) mit „Niemand behält
    lange die Krone"-Footer (Design D).

    mode='full' → Top 3 als 3 inline-Fields + „Plätze 4–N" als Field
    mode='top3' → Nur die 3 inline-Fields (kompakt für täglichen Hype-Post)
    """
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    range_label = _range_label_for(since)
    scope_label = "Crime" if crime_only else "Alle Crews"

    crews_data = ranking.get("crews", []) or []
    districts_data = ranking.get("districts", []) or []

    # Description: knapper Header-Block
    if mode == "top3":
        day_label = _event_day_label()
        header_lines = [
            f"💀 **Stand: {day_label} · {scope_label}**",
            "_Die drei Spitzenreiter — aktualisiert um diese Uhrzeit täglich._",
        ]
    else:
        header_lines = [f"💀 **Stand:** {range_label} · {scope_label}"]
    description = "\n".join(header_lines)

    fields: list[dict] = []

    # Top 3 als 3 inline-Fields (Podest-Style)
    top3 = crews_data[:3]
    for i, c in enumerate(top3):
        medal = medals.get(i, f"#{i + 1}")
        name = c.get("name", "?")
        district = c.get("district", "") or "—"
        points = c.get("points", 0)
        value = (
            f"_{district}_\n"
            f"**`{points:+d} Pkt`**"
        )
        fields.append({
            "name": f"{medal} {name}",
            "value": value,
            "inline": True,
        })

    # Wenn weniger als 3 Crews: leere Inline-Fields auffüllen (Layout-Stabilität)
    while len(fields) < 3 and len(crews_data) > 0:
        fields.append({"name": "​", "value": "​", "inline": True})

    # Wenn mode='full': Plätze 4–N als kompakte Liste
    if mode == "full":
        rest_limit = min(max(1, top_n), 21)
        rest = crews_data[3:rest_limit]
        if rest:
            rest_lines = []
            for idx, c in enumerate(rest, start=4):
                name = c.get("name", "?")
                district = c.get("district", "") or "—"
                points = c.get("points", 0)
                rest_lines.append(
                    f"`#{idx:>2}` **{name}** · _{district}_ · `{points:+d} Pkt`"
                )
            rest_value = "\n".join(rest_lines)
            # Field-Value-Limit 1024 → ggf. aufteilen
            if len(rest_value) <= 1020:
                fields.append({
                    "name": f"📋 Plätze 4–{len(rest) + 3}",
                    "value": rest_value,
                    "inline": False,
                })
            else:
                # In zwei Hälften aufteilen
                mid = len(rest_lines) // 2
                fields.append({
                    "name": f"📋 Plätze 4–{mid + 3}",
                    "value": "\n".join(rest_lines[:mid]),
                    "inline": False,
                })
                fields.append({
                    "name": f"📋 Plätze {mid + 4}–{len(rest) + 3}",
                    "value": "\n".join(rest_lines[mid:]),
                    "inline": False,
                })

    # Stadtteil-Aggregat (nur im 'full'-Modus, kompakt)
    if mode == "full" and show_district_aggregate and districts_data:
        district_order = ["Algonquin", "Bohan", "Broker", "Colony Island", "Dukes"]
        sorted_districts = sorted(
            districts_data,
            key=lambda d: (district_order.index(d["name"]) if d["name"] in district_order else 99),
        )
        district_lines = []
        for d in sorted_districts:
            name = d.get("name", "?")
            pts = d.get("points", 0)
            crew_count = d.get("crew_count", 0)
            district_lines.append(
                f"**{name}** · `{pts:+d} Pkt` · {crew_count} Crews"
            )
        fields.append({
            "name": "🗺️ Stadtteil-Aggregat",
            "value": "  ·  ".join(district_lines),
            "inline": False,
        })

    embed = {
        "title": title,
        "description": description,
        "color": 0xB91C1C,
        "footer": {"text": "Liberty City RP · Niemand behält lange die Krone"},
        "timestamp": datetime.utcnow().isoformat(),
        "fields": fields,
    }
    return embed


@router.post("/ranking/reset")
async def reset_ranking(session: AsyncSession = Depends(get_session)):
    """Setzt das Ranking zurück:
    - Reset-Stichtag wird auf jetzt gesetzt (Missions davor zählen nicht mehr im 'Gesamt')
    - bonus_points aller Crews werden auf 0 gesetzt
    Daten in der DB bleiben erhalten — nur die Bewertung startet neu."""
    from .settings_store import set_value as _set_setting

    now_utc = datetime.utcnow()
    await _set_setting(session, "ranking_reset_at", now_utc.isoformat())

    # Alle Bonus-Punkte auf 0
    res = await session.execute(select(Crew))
    crews = list(res.scalars().all())
    affected = 0
    for crew in crews:
        if crew.bonus_points != 0:
            crew.bonus_points = 0
            affected += 1
    await session.commit()

    return {
        "ok": True,
        "reset_at": now_utc.isoformat(),
        "crews_total": len(crews),
        "bonus_resets": affected,
    }


@router.post("/ranking/post-to-discord")
async def post_ranking_to_discord(
    payload: RankingPostRequest, session: AsyncSession = Depends(get_session)
):
    """Holt das aktuelle Ranking und postet ein hübsches Embed in einen Discord-Channel.

    Modes:
    - 'full' (default) = Podest + Plätze 4–N + Stadtteil-Aggregat
    - 'top3' = nur Top 3 als kompakter Daily-Hype-Post
    """
    # 1) Ranking holen
    ranking = await mission_ranking(
        since=payload.since, crime_only=payload.crime_only, session=session
    )

    # 2) Embed bauen
    mode = (payload.mode or "full").lower()
    if mode not in ("full", "top3"):
        mode = "full"

    # Bei top3: zufälligen Titel aus Pool wählen (Fallback = payload.title)
    effective_title = payload.title
    if mode == "top3":
        pool_res = await session.execute(select(Top3TitlePoolMessage))
        pool_items = list(pool_res.scalars().all())
        if pool_items:
            effective_title = random.choice(pool_items).text

    embed = _build_ranking_embed(
        ranking,
        since=payload.since,
        crime_only=payload.crime_only,
        title=effective_title,
        mode=mode,
        top_n=payload.top_n,
        show_district_aggregate=payload.show_district_aggregate,
    )

    # 5) Vorheriges Embed im selben Modus löschen (falls vorhanden + replace_previous=True)
    last_msg_key = f"ranking_{mode}_last_message_id" if mode in ("full", "top3") else None
    if last_msg_key is None and mode == "full":
        last_msg_key = "ranking_daily_last_message_id"
    elif mode == "full":
        last_msg_key = "ranking_daily_last_message_id"
    elif mode == "top3":
        last_msg_key = "ranking_top3_last_message_id"

    if payload.replace_previous and last_msg_key:
        prev_msg_id = (await settings_get(session, last_msg_key, "")).strip()
        if prev_msg_id:
            try:
                async with httpx.AsyncClient(timeout=10.0) as cli:
                    await cli.post(
                        f"{settings.bot_api_url}/delete_message",
                        json={"channel_id": payload.channel_id, "message_id": prev_msg_id},
                    )
            except Exception:
                pass  # Alte Message evtl. schon weg oder Channel gewechselt — ignorieren

    # 6) Neuen Embed posten
    body = {"channel_id": payload.channel_id, "embed": embed}
    if payload.intro and payload.intro.strip():
        body["content"] = payload.intro.strip()

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(f"{settings.bot_api_url}/send_embed", json=body)
    except Exception as exc:
        raise HTTPException(503, f"Bot nicht erreichbar: {exc}") from exc

    if r.status_code >= 400:
        raise HTTPException(502, f"Bot Fehler: {r.text}")

    result = r.json()
    new_msg_id = result.get("message_id") or ""

    # 7) Neue Message-ID merken für nächstes Ersetzen
    if last_msg_key and new_msg_id:
        try:
            from .settings_store import set_value as _set_setting
            await _set_setting(session, last_msg_key, str(new_msg_id))
        except Exception:
            pass

    crews_in_embed = 3 if mode == "top3" else min(len(ranking.get("crews", []) or []), payload.top_n)
    return {
        "ok": True,
        "message_id": new_msg_id,
        "crews_posted": crews_in_embed,
        "scope": "Crime" if payload.crime_only else "Alle Crews",
        "range": _range_label_for(payload.since),
        "mode": mode,
        "replaced_previous": payload.replace_previous,
    }


@router.get("/stats")
async def mission_stats(
    crew_id: int | None = None,
    district: str | None = None,
    since: datetime | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Reaktions-Aggregat: Anzahl Missions je Status, optional gefiltert nach
    Crew, Stadtteil und Zeitfenster (created_at >= since). Archivierte werden mitgezählt.

    Zusaetzlich wird ein per Soft-Reset gesetzter Cutoff angewendet
    (Setting: stats_reset_at, ISO-Timestamp). Daten vor dem Cutoff werden
    ausgeblendet, Datenbank bleibt unangetastet."""
    reset_at_str = (await settings_get(session, "stats_reset_at", "")).strip()
    reset_at: datetime | None = None
    if reset_at_str:
        try:
            reset_at = datetime.fromisoformat(reset_at_str.replace("Z", ""))
        except ValueError:
            reset_at = None

    effective_since = since
    if reset_at and (effective_since is None or reset_at > effective_since):
        effective_since = reset_at

    q = select(Mission.status, func.count(Mission.id)).group_by(Mission.status)
    if crew_id is not None:
        q = q.where(Mission.crew_id == crew_id)
    if district:
        q = q.join(Crew, Crew.id == Mission.crew_id).where(Crew.district == district)
    if effective_since is not None:
        q = q.where(Mission.created_at >= effective_since)
    res = await session.execute(q)
    counts = {s.value: 0 for s in MissionStatus}
    for status, count in res.all():
        key = status.value if hasattr(status, "value") else str(status)
        counts[key] = count
    counts["total"] = sum(counts.values())
    counts["reset_at"] = reset_at.isoformat() if reset_at else None
    return counts


@router.post("/stats/reset")
async def reset_mission_stats(session: AsyncSession = Depends(get_session)):
    """Setzt die Reaktions-Statistik auf 0 zurueck. Implementiert als Soft-Reset:
    speichert einen Cutoff-Timestamp (stats_reset_at). Alle Missions die VOR
    dem Reset erstellt wurden, werden in der Zaehlung uebersprungen. Datenbank
    bleibt unveraendert — Missions bleiben weiter aufrufbar (Archiv, Crew-Detail)."""
    from .settings_store import set_value as _set_setting
    now = datetime.utcnow()
    await _set_setting(session, "stats_reset_at", now.isoformat())
    return {"ok": True, "reset_at": now.isoformat()}


@router.get("/{mission_id}", response_model=MissionOut)
async def get_mission(mission_id: int, session: AsyncSession = Depends(get_session)):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    return m


@router.patch("/{mission_id}", response_model=MissionOut)
async def update_mission(
    mission_id: int, payload: MissionUpdate, session: AsyncSession = Depends(get_session)
):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.status != MissionStatus.DRAFT:
        raise HTTPException(409, "Mission ist nicht mehr im Draft-Status")
    data = payload.model_dump(exclude_unset=True)
    clear_schedule = data.pop("clear_scheduled_send_at", False)
    if clear_schedule:
        m.scheduled_send_at = None
    if "scheduled_send_at" in data:
        m.scheduled_send_at = _normalize_naive_utc(data.pop("scheduled_send_at"))
    for k, v in data.items():
        setattr(m, k, v)
    await session.commit()
    await session.refresh(m)
    return m


@router.post("/{mission_id}/rewrite", response_model=MissionOut)
async def rewrite_existing_mission(
    mission_id: int, session: AsyncSession = Depends(get_session)
):
    """Schreibt den aktuellen Draft-Text durch einen neuen KI-Wurf. Nutzt
    content_final als Roh-Input + Crew-Story als Kontext."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.status != MissionStatus.DRAFT:
        raise HTTPException(409, "Nur DRAFT-Missions können umformuliert werden")

    crew = await session.get(Crew, m.crew_id)
    if not crew:
        raise HTTPException(404, "Crew nicht gefunden")

    current_text = (m.content_final or m.content_generated or "").strip()
    if not current_text:
        raise HTTPException(400, "Kein Text zum Umformulieren vorhanden")

    keys = {
        "anthropic": await settings_get(session, "anthropic_api_key", settings.anthropic_api_key),
        "openai": await settings_get(session, "openai_api_key", settings.openai_api_key),
    }
    models = {
        "claude": await settings_get(session, "default_claude_model", settings.default_claude_model),
        "openai": await settings_get(session, "default_openai_model", settings.default_openai_model),
    }
    provider_name = m.ai_provider if m.ai_provider in ("anthropic", "openai") else (
        await settings_get(session, "default_provider", settings.default_ai_provider)
    )
    provider = await get_provider(provider_name, keys=keys, models=models)

    ctx = await _load_context(session, crew, "")
    user_prompt = build_rewrite_prompt(ctx, current_text)
    system_prompt_val = await _resolve_active_system_prompt(session)

    try:
        new_text = await provider.generate(
            user_prompt, model=m.ai_model or None, system_prompt=system_prompt_val
        )
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc
    new_text = _clean_ai_output(new_text)

    m.content_generated = new_text
    m.content_final = new_text
    m.prompt_used = user_prompt
    m.ai_provider = provider.name
    await session.commit()
    await session.refresh(m)
    return m


@router.post("/{mission_id}/image", response_model=MissionOut)
async def upload_image(
    mission_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.status != MissionStatus.DRAFT:
        raise HTTPException(409, "Bilder nur im Draft-Status setzbar")

    ext = Path(file.filename or "img.png").suffix.lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        raise HTTPException(400, "Format nicht unterstützt")

    target_dir = Path(settings.image_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"mission_{mission_id}_{uuid4().hex}{ext}"

    async with aiofiles.open(target, "wb") as f:
        await f.write(await file.read())

    m.image_path = str(target)
    await session.commit()
    await session.refresh(m)
    return m


@router.delete("/{mission_id}/image", response_model=MissionOut)
async def delete_image(mission_id: int, session: AsyncSession = Depends(get_session)):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.image_path:
        try:
            Path(m.image_path).unlink(missing_ok=True)
        except Exception:
            pass
    m.image_path = ""
    await session.commit()
    await session.refresh(m)
    return m


@router.post("/{mission_id}/send", response_model=MissionOut)
async def send_to_discord(mission_id: int, session: AsyncSession = Depends(get_session)):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.status != MissionStatus.DRAFT:
        raise HTTPException(409, "Mission ist nicht im Draft-Status")
    if not m.discord_channel_id:
        crew = await session.get(Crew, m.crew_id)
        if crew and crew.discord_channel_id:
            m.discord_channel_id = crew.discord_channel_id
            await session.commit()
        else:
            raise HTTPException(400, "Crew hat keinen Discord-Channel hinterlegt")

    async with httpx.AsyncClient(timeout=60.0) as cli:
        try:
            r = await cli.post(f"{settings.bot_api_url}/send", json={"mission_id": mission_id})
        except Exception as exc:
            raise HTTPException(503, f"Discord-Bot nicht erreichbar: {exc}") from exc
    if r.status_code >= 400:
        raise HTTPException(502, f"Bot Fehler: {r.text}")

    await session.refresh(m)
    return m


@router.post("/{mission_id}/override", response_model=MissionOut)
async def override_status(
    mission_id: int,
    payload: StatusOverrideRequest,
    session: AsyncSession = Depends(get_session),
):
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if payload.status not in {
        MissionStatus.APPROVED,
        MissionStatus.REJECTED,
        MissionStatus.CANCELLED,
    }:
        raise HTTPException(400, "Override nur auf approved/rejected/cancelled")
    m.status = payload.status
    m.reacted_at = datetime.utcnow()
    await session.commit()
    await session.refresh(m)
    return m


@router.get("/{mission_id}/pdf")
async def mission_pdf(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Erzeugt ein PDF mit Auftragstext, Bild und archiviertem Boss-Feedback."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, HRFlowable,
    )

    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    crew = await session.get(Crew, m.crew_id)
    crew_name = crew.name if crew else "Unbekannt"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"Auftrag {mission_id} — {crew_name}",
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("body", parent=styles["Normal"], fontSize=11, leading=15)
    boss_meta = ParagraphStyle(
        "bossMeta", parent=styles["Normal"], fontSize=9,
        textColor=colors.grey, leading=12,
    )

    story = []
    story.append(Paragraph(f"<b>{crew_name}</b>", styles["Title"]))
    status_label = {
        "approved": "👍 Erledigt", "rejected": "👎 Fehlgeschlagen",
        "cancelled": "❌ Nicht durchführbar", "pending": "⏳ Wartet",
        "draft": "Entwurf",
    }.get(m.status.value, m.status.value)
    meta_parts = [f"<b>Status:</b> {status_label}"]
    if m.created_at:
        meta_parts.append(f"<b>Erstellt:</b> {m.created_at.strftime('%d.%m.%Y %H:%M')}")
    if m.sent_at:
        meta_parts.append(f"<b>Gesendet:</b> {m.sent_at.strftime('%d.%m.%Y %H:%M')}")
    if m.deadline_at:
        meta_parts.append(f"<b>Deadline:</b> {m.deadline_at.strftime('%d.%m.%Y %H:%M')}")
    story.append(Paragraph(" &nbsp; · &nbsp; ".join(meta_parts), boss_meta))
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 10))

    content = (m.content_final or m.content_generated or "").strip()
    if content:
        for para in content.split("\n\n"):
            story.append(Paragraph(para.replace("\n", "<br/>"), body_style))
            story.append(Spacer(1, 8))

    if m.image_path:
        img_path = Path(m.image_path)
        if img_path.exists():
            try:
                img = RLImage(str(img_path))
                ratio = img.imageHeight / img.imageWidth if img.imageWidth else 0.6
                target_w = 12 * cm
                img.drawWidth = target_w
                img.drawHeight = target_w * ratio
                story.append(Spacer(1, 8))
                story.append(img)
                story.append(Spacer(1, 8))
            except Exception:
                pass

    if m.archived_boss_info:
        try:
            boss_msgs = json.loads(m.archived_boss_info)
        except (json.JSONDecodeError, TypeError):
            boss_msgs = []
        if boss_msgs:
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
            story.append(Spacer(1, 8))
            story.append(Paragraph("<b>Boss-Feedback aus Zusatzinfo-Channel</b>", styles["Heading3"]))
            story.append(Spacer(1, 6))
            for bm in boss_msgs:
                author = (bm.get("author") or "").replace("<", "&lt;").replace(">", "&gt;")
                posted = bm.get("posted_at") or ""
                try:
                    posted_fmt = datetime.fromisoformat(posted).strftime("%d.%m.%Y %H:%M")
                except (ValueError, TypeError):
                    posted_fmt = posted
                story.append(Paragraph(f"<b>{author}</b> &nbsp; <font size=9 color='#888'>{posted_fmt}</font>", body_style))
                content_text = (bm.get("content") or "").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
                story.append(Paragraph(content_text, body_style))
                story.append(Spacer(1, 8))

    doc.build(story)
    buf.seek(0)

    safe_crew = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in crew_name)
    filename = f"auftrag_{mission_id}_{safe_crew}.pdf"
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{mission_id}", response_model=MissionOut)
async def archive_mission(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Soft-Delete: Mission ins Archiv verschieben + Discord-Message loeschen +
    Boss-Texte aus Zusatzinfo-Channel im Mission-Zeitfenster loeschen."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    if m.archived_at is not None:
        return m  # bereits archiviert

    crew = await session.get(Crew, m.crew_id)

    # Boss-Texte aus Zusatzinfo-Channel + Versager-Reply zusammen archivieren:
    # erst snapshotten (in m.archived_boss_info), dann aus Discord löschen.
    kept: list[dict] = []
    before_iso: str | None = None

    if crew and crew.info_channel_id and m.sent_at:
        next_q = await session.execute(
            select(Mission)
            .where(
                Mission.crew_id == crew.id,
                Mission.id != m.id,
                Mission.archived_at.is_(None),
                Mission.sent_at.is_not(None),
                Mission.sent_at > m.sent_at,
            )
            .order_by(Mission.sent_at)
            .limit(1)
        )
        next_m = next_q.scalar_one_or_none()
        before_iso = next_m.sent_at.isoformat() if next_m else None

        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                r = await cli.post(
                    f"{settings.bot_api_url}/read_channel",
                    json={
                        "channel_id": crew.info_channel_id,
                        "after_iso": m.sent_at.isoformat(),
                        "limit": 100,
                    },
                )
            if r.status_code < 400:
                all_msgs = r.json()
                end_dt = datetime.fromisoformat(before_iso) if before_iso else None
                for bm in all_msgs:
                    try:
                        ts = datetime.fromisoformat(bm["posted_at"])
                    except (KeyError, ValueError):
                        continue
                    if end_dt and ts >= end_dt:
                        continue
                    kept.append(bm)
        except Exception:
            pass  # Bot offline -> nichts archiviert, weiter

    # Versager-Reply mit ins Archiv aufnehmen (auch ohne info_channel_id)
    if m.expiry_text:
        kept.append({
            "author": "⏳ Deadline",
            "content": m.expiry_text,
            "posted_at": (m.reacted_at or datetime.utcnow()).isoformat(),
            "message_id": m.expiry_message_id or "",
        })

    # Reaktions-Antwort mit ins Archiv aufnehmen
    if m.reaction_reply_text:
        kept.append({
            "author": "💬 Reaktions-Antwort",
            "content": m.reaction_reply_text,
            "posted_at": (m.reacted_at or datetime.utcnow()).isoformat(),
            "message_id": m.reaction_reply_message_id or "",
        })

    if kept:
        m.archived_boss_info = json.dumps(kept, ensure_ascii=False)

    # Boss-Texte aus Info-Channel löschen
    if crew and crew.info_channel_id and m.sent_at:
        try:
            async with httpx.AsyncClient(timeout=30.0) as cli:
                await cli.post(
                    f"{settings.bot_api_url}/delete_in_range",
                    json={
                        "channel_id": crew.info_channel_id,
                        "after_iso": m.sent_at.isoformat(),
                        "before_iso": before_iso,
                    },
                )
        except Exception:
            pass  # Bot offline -> weiter

    # Original-Auftrags-Message + Versager-Reply + Reaktions-Antwort löschen
    if m.discord_channel_id:
        for msg_id in filter(None, [m.discord_message_id, m.expiry_message_id, m.reaction_reply_message_id]):
            try:
                async with httpx.AsyncClient(timeout=15.0) as cli:
                    await cli.post(
                        f"{settings.bot_api_url}/delete_message",
                        json={
                            "channel_id": m.discord_channel_id,
                            "message_id": msg_id,
                        },
                    )
            except Exception:
                pass  # Bot offline -> nur DB-Archiv

    # Personal-Bedarf-Embed im Admin-Channel ebenfalls löschen
    if m.personnel_discord_message_id:
        personnel_channel = (
            await settings_get(session, "personnel_admin_channel_id", "")
        ).strip()
        if personnel_channel:
            try:
                async with httpx.AsyncClient(timeout=15.0) as cli:
                    await cli.post(
                        f"{settings.bot_api_url}/delete_message",
                        json={
                            "channel_id": personnel_channel,
                            "message_id": m.personnel_discord_message_id,
                        },
                    )
            except Exception:
                pass  # Bot offline -> Message bleibt orphan im Channel
        m.personnel_discord_message_id = ""

    # Ankündigung der Personal-Börse im Jobs-Announce-Channel löschen —
    # ein archivierter Auftrag soll dort keine offenen Plätze mehr bewerben
    if m.jobs_announce_message_id:
        jobs_channel = (
            await settings_get(session, "jobs_announce_channel_id", "")
        ).strip()
        if jobs_channel:
            try:
                async with httpx.AsyncClient(timeout=15.0) as cli:
                    await cli.post(
                        f"{settings.bot_api_url}/delete_message",
                        json={
                            "channel_id": jobs_channel,
                            "message_id": m.jobs_announce_message_id,
                        },
                    )
            except Exception:
                pass  # Bot offline -> Message bleibt orphan im Channel
        m.jobs_announce_message_id = ""

    m.archived_at = datetime.utcnow()
    await session.commit()
    await session.refresh(m)
    return m


@router.post("/{mission_id}/restore", response_model=MissionOut)
async def restore_mission(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Mission aus Archiv zurueckholen (Discord-Message bleibt geloescht)."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    m.archived_at = None
    m.discord_message_id = ""  # alte Message-Referenz entfernen, sie wurde geloescht
    await session.commit()
    await session.refresh(m)
    return m


@router.delete("/{mission_id}/purge", status_code=204)
async def purge_mission(mission_id: int, session: AsyncSession = Depends(get_session)):
    """Hard-Delete: endgueltig loeschen (auch aus Archiv)."""
    m = await session.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "Mission nicht gefunden")
    # Falls noch Personal-Bedarf-Embed im Admin-Channel liegt (z.B. wenn
    # direkt vom Draft gepurged wird ohne vorher zu archivieren), aufräumen.
    if m.personnel_discord_message_id:
        personnel_channel = (
            await settings_get(session, "personnel_admin_channel_id", "")
        ).strip()
        if personnel_channel:
            try:
                async with httpx.AsyncClient(timeout=10.0) as cli:
                    await cli.post(
                        f"{settings.bot_api_url}/delete_message",
                        json={
                            "channel_id": personnel_channel,
                            "message_id": m.personnel_discord_message_id,
                        },
                    )
            except Exception:
                pass
    if m.image_path:
        try:
            Path(m.image_path).unlink(missing_ok=True)
        except Exception:
            pass
    await session.delete(m)
    await session.commit()

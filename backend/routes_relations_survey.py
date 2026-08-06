"""Beziehungs-Erhebung: Dropdown-Umfrage im Discord + Auswertung.

Ablauf:
  1. /send  postet je Gruppierung eine Nachricht mit Auswahlmenues in ihren
     Auftrags-Channel. Jede aktive Gruppierung bewertet alle anderen.
  2. Der Bot schreibt jede Auswahl als RelationProposal (gerichtet) in die DB.
  3. /status zeigt, wer wie weit ist.
  4. /matrix stellt beide Richtungen gegenueber und markiert Widersprueche.

Der Abgleich zur finalen, symmetrischen CrewRelation passiert bewusst NICHT
automatisch — die Widersprueche sind das Interessante und sollen gesehen
werden, bevor daraus ein gemeinsamer Nenner wird.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import get_provider
from .auth import require_admin
from .config import settings
from .db import get_session
from .models import Crew, CrewRelation, RelationProposal, RelationType, SurveyMessage
from .prompts import (
    GANG_ANALYSIS_SYSTEM_PROMPT,
    RELATION_ARBITRATION_SYSTEM_PROMPT,
    build_gang_analysis_prompt,
    build_relation_arbitration_prompt,
)
from .settings_store import get as settings_get_value

router = APIRouter(
    prefix="/api/relations/survey",
    tags=["relations-survey"],
    dependencies=[Depends(require_admin)],
)

#: Deutsche Labels — identisch zu den Dropdown-Eintraegen im Bot.
LABEL_BY_TYPE = {
    "ALLIED": "verbündet",
    "BUSINESS": "geschäftlich",
    "NEUTRAL": "neutral",
    "RIVAL": "rivalisierend",
    "HOSTILE": "feindlich",
}

#: Wie weit zwei Einschaetzungen auseinanderliegen. Grundlage fuer die
#: Konflikt-Einstufung: 0 = einig, 1 = benachbart (unkritisch),
#: >=2 = echter Widerspruch, der eine Entscheidung braucht.
SCALE = {"ALLIED": 0, "BUSINESS": 1, "NEUTRAL": 2, "RIVAL": 3, "HOSTILE": 4}

#: Emoji + Reihenfolge fuer die veroeffentlichte Zusammenfassung — Konflikte
#: zuerst (dramaturgisch), neutral als Sammelposten am Ende.
SUMMARY_ORDER = [
    ("HOSTILE", "🔥", "feindlich"),
    ("RIVAL", "⚔️", "rivalisierend"),
    ("BUSINESS", "💼", "geschäftlich"),
    ("ALLIED", "🤝", "verbündet"),
]
_LINE = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def _build_summary_text(crew, relations_of, all_active_names, intro: str) -> str:
    """Discord-Text 'EUER STAND' fuer eine Gruppierung, mit Begruendungen.

    relations_of: dict {other_name: (relation_type, notes)} — die geltenden
    Beziehungen (crew_relations) dieser Gruppierung.
    all_active_names: alle aktiven Gruppierungs-Namen (fuer 'alle uebrigen').
    """
    parts: list[str] = []
    if intro.strip():
        parts.append(intro.strip())
    parts.append(f"{_LINE}\n## EUER STAND — {crew.name.upper()}\n{_LINE}")

    for rtype, emoji, label in SUMMARY_ORDER:
        block = [(o, n) for o, (t, n) in relations_of.items() if t == rtype]
        if not block:
            continue
        parts.append(f"{emoji} **{label}**")
        for other, notes in sorted(block, key=lambda x: x[0].lower()):
            if notes.strip():
                parts.append(f"**{other}**\n{notes.strip()}")
            else:
                parts.append(f"**{other}**")

    # neutral = alle aktiven ausser der eigenen und den oben genannten
    genannt = set(relations_of.keys()) | {crew.name}
    uebrig = [n for n in all_active_names if n not in genannt]
    parts.append(f"➖ **neutral**\nalle übrigen ({len(uebrig)})")

    return "\n\n".join(parts)


def _split_for_discord(text: str, limit: int = 1990) -> list[str]:
    """Zu lange Zusammenfassung an Absatzgrenzen (\\n\\n) auf mehrere
    Nachrichten aufteilen — Begruendungen koennen 2000 Zeichen sprengen."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        add = (cur + "\n\n" + block) if cur else block
        if len(add) > limit and cur:
            chunks.append(cur)
            cur = block
        else:
            cur = add
    if cur:
        chunks.append(cur)
    return chunks


class SurveySendRequest(BaseModel):
    #: Leer = alle aktiven Gruppierungen mit Channel. Sonst nur diese IDs —
    #: damit sich die Erhebung erst an einer Gruppe testen laesst.
    crew_ids: list[int] | None = None
    intro: str = ""
    #: Fester Fristzeitpunkt als lokale ISO-Zeit ("2026-07-25T21:21").
    deadline_at: str | None = None
    #: Alternativ: Dauer ab Versand in Minuten. Wird nur ausgewertet, wenn
    #: kein deadline_at gesetzt ist. Bewusst serverseitig gerechnet — sonst
    #: haengt die Frist an der womoeglich falsch gestellten Browser-Uhr.
    deadline_minutes: int | None = None
    #: Nachtrag: nur Menues fuer Gruppierungen posten, zu denen noch keine
    #: Bewertung vorliegt. Fuer Neuzugaenge (alle anderen bekommen genau ein
    #: Menue) und als Erinnerung an unvollstaendige Gruppierungen.
    only_missing: bool = False


def _deadline_line(ts: int) -> str:
    """Frist als abgesetzter Block mit Discord-Zeitstempel.

    <t:UNIX:F> schreibt Wochentag, Datum und Uhrzeit in der Zeitzone des
    jeweiligen Lesers, <t:UNIX:R> laeuft als Countdown live mit ("in 2 Tagen").
    Damit steht in jedem Client die richtige Zeit, ohne dass wir uns auf eine
    Zeitzone festlegen — und niemand rechnet sich die Frist schoen.

    Die Trennlinien sind Zeichen, keine Markdown-Regel: Discord rendert
    weder --- noch ***  als horizontale Linie. Die Ueberschrift (##) macht
    den Countdown gross genug, dass er beim Scrollen nicht untergeht.

    WICHTIG: Der Zeitstempel darf NICHT in Code-Formatierung stehen — in
    Code-Bloecken und Backticks bleibt <t:...> als roher Text stehen,
    statt zu Datum und Countdown zu werden.
    """
    linie = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return (
        f"\n\n{linie}"
        f"\n## ⏳ FRIST — <t:{ts}:R>"
        f"\n### <t:{ts}:F>"
        f"\n{linie}"
    )


def _deadline_ts(payload: SurveySendRequest) -> int | None:
    """Fristzeitpunkt als Unix-Sekunde — aus festem Datum oder aus Dauer."""
    fest = (payload.deadline_at or "").strip()
    if fest:
        # Die Eingabe kommt ohne Zeitzone aus dem Browser-Feld und wird als
        # lokale Zeit des Servers gelesen (Container laeuft auf Europe/Berlin).
        try:
            dt = datetime.fromisoformat(fest)
        except ValueError as exc:
            raise HTTPException(400, f"Frist nicht lesbar: {fest!r}") from exc
        if dt.tzinfo is None:
            dt = dt.astimezone()
        if dt <= datetime.now(timezone.utc):
            raise HTTPException(400, "Die Frist liegt in der Vergangenheit")
        return int(dt.timestamp())

    minuten = payload.deadline_minutes or 0
    if minuten > 0:
        return int((datetime.now(timezone.utc) + timedelta(minutes=minuten)).timestamp())
    return None


def _type_name(value) -> str:
    return value.name if hasattr(value, "name") else str(value)


#: Umgekehrte Skala — von der Zahl zum Typ, fuer den Uebernahme-Vorschlag.
_TYPE_BY_SCALE = {v: k for k, v in SCALE.items()}


def _finalize_suggestion(ab_t: str | None, ba_t: str | None, current: str | None) -> str | None:
    """Vorschlag fuer den finalen, symmetrischen Wert eines Paares.

    - Beide einig  -> dieser Wert.
    - Uneinig      -> der haertere (hoehere Skalenwert). Im RP eskaliert ein
                      Konflikt eher, als dass er sich in Wohlwollen aufloest;
                      ausserdem soll der Vorschlag auffallen, nicht glaetten.
    - Nur eine Seite / keine -> die vorhandene Angabe, sonst der bereits
                      gepflegte Wert, sonst nichts.
    Nur ein VORSCHLAG — entschieden wird per Hand in der UI.
    """
    have = [t for t in (ab_t, ba_t) if t]
    if len(have) == 2:
        return _TYPE_BY_SCALE[max(SCALE[ab_t], SCALE[ba_t])]
    if len(have) == 1:
        return have[0]
    return current


async def _survey_crews(session: AsyncSession) -> list[Crew]:
    """Alle aktiven Gruppierungen — sie bilden die Liste der Bewertbaren."""
    res = await session.execute(
        select(Crew).where(Crew.is_active.is_(True)).order_by(Crew.name)
    )
    return list(res.scalars().all())


@router.post("/send")
async def send_survey(
    payload: SurveySendRequest, session: AsyncSession = Depends(get_session)
):
    """Postet die Erhebung. Jede Gruppierung bewertet alle anderen aktiven —
    sich selbst nie."""
    crews = await _survey_crews(session)
    if not crews:
        raise HTTPException(400, "Keine aktiven Gruppierungen")

    if payload.crew_ids:
        recipients = [c for c in crews if c.id in set(payload.crew_ids)]
    else:
        recipients = crews

    intro = payload.intro or ""
    # Einmal vor der Sendeschleife bilden, damit alle Gruppierungen exakt
    # dieselbe Frist bekommen und nicht je nach Sendereihenfolge auseinanderliegen.
    ts = _deadline_ts(payload)
    if ts:
        intro = (intro + _deadline_line(ts)).strip()

    if len(intro) > 1990:
        raise HTTPException(400, f"Einleitungstext zu lang ({len(intro)} > 1990 Zeichen)")

    # Vorhandene Antworten einmal laden — bei only_missing brauchen wir sie
    # fuer jeden Empfaenger, eine Abfrage je Gruppierung waere Verschwendung.
    bereits: set[tuple[int, int]] = set()
    if payload.only_missing:
        bereits = {
            (p.from_crew_id, p.to_crew_id)
            for p in (await session.execute(select(RelationProposal))).scalars().all()
        }

    sent: list[dict] = []
    skipped: list[dict] = []

    for crew in recipients:
        if not (crew.discord_channel_id or "").strip():
            skipped.append({"crew": crew.name, "grund": "keine Channel-ID"})
            continue

        targets = [{"id": t.id, "name": t.name} for t in crews if t.id != crew.id]
        if payload.only_missing:
            targets = [t for t in targets if (crew.id, t["id"]) not in bereits]
            if not targets:
                skipped.append({"crew": crew.name, "grund": "bereits vollständig"})
                continue
        if not targets:
            skipped.append({"crew": crew.name, "grund": "keine anderen Gruppierungen"})
            continue

        body = {
            "channel_id": crew.discord_channel_id,
            "from_crew_id": crew.id,
            "intro": intro,
            "targets": targets,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as cli:
                r = await cli.post(f"{settings.bot_api_url}/post_relation_survey", json=body)
            if r.status_code >= 400:
                skipped.append({"crew": crew.name, "grund": f"Bot: {r.text[:160]}"})
                continue
            # Message-IDs merken, damit die Umfrage spaeter per Knopfdruck
            # aus dem Channel verschwinden kann.
            for mid in (r.json().get("message_ids") or []):
                session.add(SurveyMessage(
                    crew_id=crew.id,
                    channel_id=crew.discord_channel_id,
                    message_id=str(mid),
                ))
            sent.append({"crew": crew.name, "targets": len(targets)})
        except Exception as exc:
            skipped.append({"crew": crew.name, "grund": f"Bot nicht erreichbar: {exc}"})

    await session.commit()
    return {"ok": True, "gesendet": sent, "uebersprungen": skipped}


async def _purge_messages(session: AsyncSession, rows: list[SurveyMessage]) -> dict:
    """Nachrichten im Discord loeschen und die Merkzettel entfernen.

    Der Bot meldet bereits geloeschte Nachrichten als Erfolg zurueck — ein
    von Hand geleerter Channel fuehrt hier also nicht zu Fehlern, die
    Merkzettel verschwinden trotzdem.
    """
    geloescht, fehler = 0, []
    async with httpx.AsyncClient(timeout=20.0) as cli:
        for row in rows:
            try:
                r = await cli.post(
                    f"{settings.bot_api_url}/delete_message",
                    json={"channel_id": row.channel_id, "message_id": row.message_id},
                )
                if r.status_code >= 400:
                    fehler.append(f"{row.message_id}: {r.text[:80]}")
                    continue
            except Exception as exc:
                fehler.append(f"{row.message_id}: {exc}")
                continue
            await session.delete(row)
            geloescht += 1
    await session.commit()
    return {"ok": True, "geloescht": geloescht, "fehler": fehler}


class ProposalSetRequest(BaseModel):
    from_crew_id: int
    to_crew_id: int
    #: Einer der RelationType-Namen: ALLIED, BUSINESS, NEUTRAL, RIVAL, HOSTILE
    relation_type: str


@router.put("/proposal")
async def set_proposal(
    payload: ProposalSetRequest, session: AsyncSession = Depends(get_session)
):
    """Eine einzelne Einschaetzung setzen — Admin-Korrektur.

    Upsert: existiert die Richtung schon, wird der Wert geaendert; sonst neu
    angelegt (so lassen sich auch 'offene' Richtungen von Hand fuellen, wenn
    eine Gruppierung nicht geantwortet hat). Gerichtet — betrifft nur diese
    eine Richtung, die Gegenrichtung bleibt unangetastet.
    """
    try:
        rel = RelationType[payload.relation_type]
    except KeyError:
        raise HTTPException(400, f"Unbekannter Beziehungstyp: {payload.relation_type!r}")
    if payload.from_crew_id == payload.to_crew_id:
        raise HTTPException(400, "Eine Gruppierung kann sich nicht selbst bewerten")

    # Beide Gruppierungen muessen existieren — sonst sind es Karteileichen
    for cid in (payload.from_crew_id, payload.to_crew_id):
        if not await session.get(Crew, cid):
            raise HTTPException(404, f"Gruppierung {cid} nicht gefunden")

    row = (await session.execute(
        select(RelationProposal).where(
            RelationProposal.from_crew_id == payload.from_crew_id,
            RelationProposal.to_crew_id == payload.to_crew_id,
        )
    )).scalar_one_or_none()

    if row:
        row.relation_type = rel
        # Als Hand-Korrektur markieren, damit spaeter nachvollziehbar bleibt,
        # dass hier nicht die Gruppierung selbst geklickt hat.
        row.discord_user_name = "Hand-Korrektur"
        row.discord_user_id = ""
        row.updated_at = datetime.utcnow()
        neu = False
    else:
        session.add(RelationProposal(
            from_crew_id=payload.from_crew_id,
            to_crew_id=payload.to_crew_id,
            relation_type=rel,
            discord_user_name="Hand-Korrektur",
        ))
        neu = True
    await session.commit()
    return {"ok": True, "angelegt": neu, "relation_type": rel.name}


@router.delete("/messages/{crew_id}")
async def delete_survey_messages(crew_id: int, session: AsyncSession = Depends(get_session)):
    """Umfrage-Nachrichten EINER Gruppierung aus ihrem Channel entfernen.
    Die abgegebenen Antworten bleiben — die liegen in der Datenbank."""
    rows = list((await session.execute(
        select(SurveyMessage).where(SurveyMessage.crew_id == crew_id)
    )).scalars().all())
    if not rows:
        raise HTTPException(404, "Keine gemerkten Nachrichten für diese Gruppierung")
    return await _purge_messages(session, rows)


@router.delete("/messages")
async def delete_all_survey_messages(session: AsyncSession = Depends(get_session)):
    """Umfrage-Nachrichten aller Gruppierungen entfernen."""
    rows = list((await session.execute(select(SurveyMessage))).scalars().all())
    return await _purge_messages(session, rows)


@router.get("/status")
async def survey_status(session: AsyncSession = Depends(get_session)):
    """Fortschritt je Gruppierung: wie viele der geforderten Bewertungen da sind."""
    crews = await _survey_crews(session)
    by_id = {c.id: c for c in crews}
    soll = max(len(crews) - 1, 0)

    rows = (await session.execute(select(RelationProposal))).scalars().all()
    counts: dict[int, int] = {}
    for p in rows:
        counts[p.from_crew_id] = counts.get(p.from_crew_id, 0) + 1

    msgs = (await session.execute(select(SurveyMessage))).scalars().all()
    msg_counts: dict[int, int] = {}
    for m in msgs:
        msg_counts[m.crew_id] = msg_counts.get(m.crew_id, 0) + 1

    items = [
        {
            "crew_id": c.id,
            "name": c.name,
            "district": c.district or "",
            "hat_channel": bool((c.discord_channel_id or "").strip()),
            "abgegeben": counts.get(c.id, 0),
            "soll": soll,
            "nachrichten": msg_counts.get(c.id, 0),
        }
        for c in crews
    ]
    items.sort(key=lambda i: (i["abgegeben"] >= i["soll"], i["name"]))

    return {
        "soll_pro_gruppe": soll,
        "gruppen": len(crews),
        "vollstaendig": sum(1 for i in items if soll and i["abgegeben"] >= soll),
        "eintraege_gesamt": len(rows),
        "nachrichten_gesamt": len(msgs),
        "items": items,
        "unbekannte_crews": [p.from_crew_id for p in rows if p.from_crew_id not in by_id],
    }


@router.get("/matrix")
async def survey_matrix(session: AsyncSession = Depends(get_session)):
    """Beide Richtungen je Paar gegenuebergestellt.

    status:
      offen        — mindestens eine Seite hat noch nicht geantwortet
      einig        — beide sagen dasselbe
      abweichend   — benachbart auf der Skala (z.B. verbündet/geschäftlich)
      widerspruch  — zwei oder mehr Stufen auseinander
    """
    crews = await _survey_crews(session)
    by_id = {c.id: c for c in crews}

    rows = (await session.execute(select(RelationProposal))).scalars().all()
    prop: dict[tuple[int, int], RelationProposal] = {
        (p.from_crew_id, p.to_crew_id): p for p in rows
    }

    # Aktuell gepflegte Beziehungen (crew_relations) — kanonisch a_id < b_id.
    # Das ist der Stand, mit dem heute gespielt wird; die Uebernahme schreibt
    # genau hierhin.
    crel_rows = (await session.execute(select(CrewRelation))).scalars().all()
    crel: dict[tuple[int, int], str] = {
        (r.crew_a_id, r.crew_b_id): _type_name(r.relation_type) for r in crel_rows
    }
    crel_notes: dict[tuple[int, int], str] = {
        (r.crew_a_id, r.crew_b_id): (r.notes or "") for r in crel_rows
    }

    pairs: list[dict] = []
    for i, a in enumerate(crews):
        for b in crews[i + 1:]:
            ab = prop.get((a.id, b.id))
            ba = prop.get((b.id, a.id))
            ab_t = _type_name(ab.relation_type) if ab else None
            ba_t = _type_name(ba.relation_type) if ba else None

            if ab_t is None or ba_t is None:
                status, abstand = "offen", None
            else:
                abstand = abs(SCALE[ab_t] - SCALE[ba_t])
                status = "einig" if abstand == 0 else ("abweichend" if abstand == 1 else "widerspruch")

            lo, hi = (a.id, b.id) if a.id < b.id else (b.id, a.id)
            current = crel.get((lo, hi))

            pairs.append({
                "a_id": a.id, "a_name": a.name,
                "b_id": b.id, "b_name": b.name,
                "a_zu_b": ab_t, "a_zu_b_label": LABEL_BY_TYPE.get(ab_t or "", ""),
                "b_zu_a": ba_t, "b_zu_a_label": LABEL_BY_TYPE.get(ba_t or "", ""),
                "status": status,
                "abstand": abstand,
                # Aktueller Stand in der echten Matrix + ein Vorschlag fuer die
                # Uebernahme: bei Einigkeit der gemeinsame Wert, sonst der
                # "haertere" (hoehere Skala) — Konflikte eskalieren im RP eher.
                "current": current,
                "current_label": LABEL_BY_TYPE.get(current or "", ""),
                "current_notes": crel_notes.get((lo, hi), ""),
                "vorschlag": _finalize_suggestion(ab_t, ba_t, current),
            })

    rang = {"widerspruch": 0, "abweichend": 1, "einig": 2, "offen": 3}
    pairs.sort(key=lambda p: (rang[p["status"]], -(p["abstand"] or 0), p["a_name"]))

    zusammenfassung = {s: sum(1 for p in pairs if p["status"] == s) for s in rang}
    return {
        "paare": len(pairs),
        "zusammenfassung": zusammenfassung,
        "items": pairs,
        "gruppen": [{"id": c.id, "name": c.name} for c in by_id.values()],
    }


async def _summaries(session: AsyncSession, intro: str) -> list[dict]:
    """Baut fuer jede aktive Gruppierung ihren 'EUER STAND'-Text aus der
    geltenden Matrix (crew_relations, mit Begruendungen).

    Wichtig: Angezeigt werden ALLE geltenden Beziehungen — auch zu inaktiven
    Gruppierungen (Institutionen wie LCPD/DoJ). Eine Feindschaft zur Polizei
    gehoert in den Stand, egal ob sie eine spielbare Crew ist. Nur der
    'neutral = alle uebrigen'-Sammelposten bezieht sich auf die aktiven, die
    ueberhaupt bewertet werden konnten.
    """
    active = await _survey_crews(session)
    active_names = [c.name for c in active]

    all_crews = (await session.execute(select(Crew))).scalars().all()
    name_by_id = {c.id: c.name for c in all_crews}

    crel = (await session.execute(select(CrewRelation))).scalars().all()
    # pro AKTIVE Crew: {other_name: (typ, notes)} — other darf inaktiv sein
    rel_of: dict[int, dict] = {c.id: {} for c in active}
    for r in crel:
        t = _type_name(r.relation_type)
        if r.crew_a_id in rel_of and r.crew_b_id in name_by_id:
            rel_of[r.crew_a_id][name_by_id[r.crew_b_id]] = (t, r.notes or "")
        if r.crew_b_id in rel_of and r.crew_a_id in name_by_id:
            rel_of[r.crew_b_id][name_by_id[r.crew_a_id]] = (t, r.notes or "")

    out = []
    for c in active:
        text = _build_summary_text(c, rel_of[c.id], active_names, intro)
        out.append({
            "crew_id": c.id,
            "name": c.name,
            "hat_channel": bool((c.discord_channel_id or "").strip()),
            "beziehungen": len(rel_of[c.id]),
            "text": text,
            "teile": len(_split_for_discord(text)),
        })
    return out


@router.get("/summary")
async def summary_preview(intro: str = "", session: AsyncSession = Depends(get_session)):
    """Vorschau der 'EUER STAND'-Nachrichten fuer alle aktiven Gruppierungen —
    sendet nichts."""
    return {"items": await _summaries(session, intro)}


class SummarySendRequest(BaseModel):
    #: Leer/None = alle aktiven Gruppierungen mit Channel. Sonst nur diese.
    crew_ids: list[int] | None = None
    intro: str = ""


@router.post("/summary/send")
async def summary_send(
    payload: SummarySendRequest, session: AsyncSession = Depends(get_session)
):
    """Postet jeder gewaehlten Gruppierung ihren geltenden Beziehungs-Stand in
    ihren Auftrags-Channel. Lange Zusammenfassungen werden auf mehrere
    Nachrichten aufgeteilt."""
    items = await _summaries(session, payload.intro or "")
    if payload.crew_ids:
        wanted = set(payload.crew_ids)
        items = [i for i in items if i["crew_id"] in wanted]

    crews = {c.id: c for c in await _survey_crews(session)}
    sent, skipped = [], []
    for i in items:
        crew = crews.get(i["crew_id"])
        channel = (crew.discord_channel_id or "").strip() if crew else ""
        if not channel:
            skipped.append({"crew": i["name"], "grund": "keine Channel-ID"})
            continue
        try:
            async with httpx.AsyncClient(timeout=30.0) as cli:
                for teil in _split_for_discord(i["text"]):
                    r = await cli.post(
                        f"{settings.bot_api_url}/post_text",
                        json={"channel_id": channel, "content": teil},
                    )
                    if r.status_code >= 400:
                        raise RuntimeError(r.text[:120])
            sent.append({"crew": i["name"], "teile": i["teile"]})
        except Exception as exc:
            skipped.append({"crew": i["name"], "grund": str(exc)})

    return {"ok": True, "gesendet": sent, "uebersprungen": skipped}


class BossAnsageSendRequest(BaseModel):
    wortlaut: str
    titel: str | None = None


@router.post("/boss-ansage/{crew_id}/send")
async def boss_ansage_send(
    crew_id: int, payload: BossAnsageSendRequest,
    session: AsyncSession = Depends(get_session),
):
    """Postet die Miguel-Boss-Ansage einer Gruppierung als Discord-Embed
    (crimson Farb-Leiste) in ihren CRIME-BUSINESS-Channel — der wird beim
    Archivieren NICHT geleert, die Ansage bleibt also dauerhaft erhalten."""
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Gruppierung nicht gefunden")
    channel = (crew.crime_business_channel_id or "").strip()
    if not channel:
        raise HTTPException(400, "Keine Crime-Business-Channel-ID für diese Gruppierung")
    text = (payload.wortlaut or "").strip()
    if not text:
        raise HTTPException(400, "Kein Wortlaut übergeben")

    embed = {
        "title": "🗣 Miguel — im Auftrag des Bosses",
        "description": text[:4000],
        "color": 0xE62958,  # CYQORE Crimson
        "footer": {"text": "L'Occhio del Padrino"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as cli:
            r = await cli.post(
                f"{settings.bot_api_url}/send_embed",
                json={"channel_id": channel, "embed": embed},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Bot-Fehler: {exc.response.text[:150]}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Bot nicht erreichbar: {exc}") from exc

    return {"ok": True, "crew": crew.name, "channel_id": channel,
            "message_id": data.get("message_id")}


def _gang_profile(crew_id: int, prop: dict) -> dict:
    """Volles Beziehungsprofil einer Gruppierung fuer die Bewertung:
    - sieht_andere: {label: anzahl} — wie sie die anderen einschaetzt
    - wird_gesehen: {label: anzahl} — wie die anderen sie einschaetzen
    - reibungen: [{mine, theirs}] — Paare mit abweichender Sicht (Abstand>=1),
      anonym; nach Abstand absteigend (die staerksten zuerst)
    - anzahl: Anzahl Reibungspunkte
    """
    sieht: dict[str, int] = {}
    gesehen: dict[str, int] = {}
    reib: list[tuple[int, dict]] = []
    for (frm, to), p in prop.items():
        if frm == crew_id:
            lbl = LABEL_BY_TYPE.get(_type_name(p.relation_type), "")
            sieht[lbl] = sieht.get(lbl, 0) + 1
        if to == crew_id:
            lbl = LABEL_BY_TYPE.get(_type_name(p.relation_type), "")
            gesehen[lbl] = gesehen.get(lbl, 0) + 1
        if frm == crew_id:
            back = prop.get((to, frm))
            if back:
                mine, theirs = _type_name(p.relation_type), _type_name(back.relation_type)
                dist = abs(SCALE[mine] - SCALE[theirs])
                if dist >= 1:
                    reib.append((dist, {
                        "mine": LABEL_BY_TYPE.get(mine, mine),
                        "theirs": LABEL_BY_TYPE.get(theirs, theirs),
                    }))
    reib.sort(key=lambda x: -x[0])
    return {
        "sieht_andere": sieht,
        "wird_gesehen": gesehen,
        "reibungen": [r for _, r in reib],
        "anzahl": len(reib),
    }


class GangAnalysisRequest(BaseModel):
    provider: str | None = None
    model: str | None = None


@router.post("/analysis/{crew_id}")
async def gang_analysis(
    crew_id: int, payload: GangAnalysisRequest,
    session: AsyncSession = Depends(get_session),
):
    """KI-Einordnung EINER Gruppierung: liest ihre Widersprueche als Muster
    und leitet einen Charakterzug ab (Titel + Begruendung). Schreibt nichts."""
    crew = await session.get(Crew, crew_id)
    if not crew:
        raise HTTPException(404, "Gruppierung nicht gefunden")

    rows = (await session.execute(select(RelationProposal))).scalars().all()
    prop = {(p.from_crew_id, p.to_crew_id): p for p in rows}

    profile = _gang_profile(crew_id, prop)
    if not profile["sieht_andere"] and not profile["wird_gesehen"]:
        return {"ok": True, "titel": "Noch keine Daten", "bewertung": "—",
                "zusammenfassung": "Zu dieser Gruppierung liegen noch keine "
                "Bewertungen vor — weder hat sie abgestimmt, noch wurde sie "
                "bewertet.", "anzahl": 0}

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

    # Etablierte (finale) Beziehungen dieser Gruppierung — Kanon aus der Matrix.
    # Diese DÜRFEN im Miguel-Wortlaut namentlich genannt werden (anders als die
    # anonymen Umfrage-Stimmen).
    _REL_LABELS = {
        "ALLIED": "verbündet", "BUSINESS": "geschäftlich", "NEUTRAL": "neutral",
        "RIVAL": "rivalisierend", "HOSTILE": "feindlich",
    }
    crel_rows = (await session.execute(
        select(CrewRelation).where(
            (CrewRelation.crew_a_id == crew_id) | (CrewRelation.crew_b_id == crew_id)
        )
    )).scalars().all()
    name_map = {c.id: c.name for c in (await session.execute(select(Crew))).scalars().all()}
    beziehungen_final: list[dict] = []
    for r in crel_rows:
        other_id = r.crew_b_id if r.crew_a_id == crew_id else r.crew_a_id
        raw_type = getattr(r.relation_type, "value", r.relation_type)
        beziehungen_final.append({
            "other": name_map.get(other_id, f"#{other_id}"),
            "type": _REL_LABELS.get(str(raw_type), str(raw_type or "neutral")),
        })

    user_prompt = build_gang_analysis_prompt(
        crew.name, crew.story_background or "",
        profile["sieht_andere"], profile["wird_gesehen"], profile["reibungen"],
        beziehungen_final,
    )
    try:
        text = await provider.generate(
            user_prompt, model=payload.model, system_prompt=GANG_ANALYSIS_SYSTEM_PROMPT
        )
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    raw = (text or "").strip()
    parsed = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e > s:
            try:
                parsed = json.loads(raw[s:e + 1])
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict) or not parsed.get("titel"):
        raise HTTPException(502, f"KI-Antwort unbrauchbar: {raw[:200]}")

    return {
        "ok": True,
        "titel": str(parsed["titel"]).strip(),
        "bewertung": str(parsed.get("bewertung", "")).strip(),
        "zusammenfassung": str(parsed.get("zusammenfassung", "")).strip(),
        "wortlaut": str(parsed.get("wortlaut", "")).strip(),
        "anzahl": profile["anzahl"],
        "provider": provider.name,
    }


class AiSuggestRequest(BaseModel):
    a_id: int
    b_id: int
    provider: str | None = None
    model: str | None = None


@router.post("/ai-suggest")
async def ai_suggest_pair(
    payload: AiSuggestRequest, session: AsyncSession = Depends(get_session)
):
    """KI-Schiedsspruch fuer EIN Paar: liest die Storys beider Gruppierungen
    und die abgegebenen Sichten, empfiehlt einen finalen Beziehungstyp mit
    Begruendung. Schreibt NICHTS — reiner Vorschlag fuer die UI."""
    a = await session.get(Crew, payload.a_id)
    b = await session.get(Crew, payload.b_id)
    if not a or not b:
        raise HTTPException(404, "Gruppierung nicht gefunden")

    ab = (await session.execute(select(RelationProposal).where(
        RelationProposal.from_crew_id == a.id, RelationProposal.to_crew_id == b.id
    ))).scalar_one_or_none()
    ba = (await session.execute(select(RelationProposal).where(
        RelationProposal.from_crew_id == b.id, RelationProposal.to_crew_id == a.id
    ))).scalar_one_or_none()

    lo, hi = sorted((a.id, b.id))
    crel = (await session.execute(select(CrewRelation).where(
        CrewRelation.crew_a_id == lo, CrewRelation.crew_b_id == hi
    ))).scalar_one_or_none()

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

    user_prompt = build_relation_arbitration_prompt(
        a_name=a.name, a_story=a.story_background or "", a_business=a.crime_business or "",
        b_name=b.name, b_story=b.story_background or "", b_business=b.crime_business or "",
        a_zu_b=LABEL_BY_TYPE.get(_type_name(ab.relation_type), "") if ab else "",
        b_zu_a=LABEL_BY_TYPE.get(_type_name(ba.relation_type), "") if ba else "",
        current=LABEL_BY_TYPE.get(_type_name(crel.relation_type), "") if crel else "",
    )
    try:
        text = await provider.generate(
            user_prompt, model=payload.model, system_prompt=RELATION_ARBITRATION_SYSTEM_PROMPT
        )
    except Exception as exc:
        raise HTTPException(502, f"AI-Provider Fehler: {exc}") from exc

    raw = (text or "").strip()
    parsed: dict | None = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e > s:
            try:
                parsed = json.loads(raw[s:e + 1])
            except json.JSONDecodeError:
                parsed = None

    if not isinstance(parsed, dict) or parsed.get("relation_type") not in RelationType.__members__:
        raise HTTPException(502, f"KI-Antwort unbrauchbar: {raw[:200]}")

    return {
        "ok": True,
        "relation_type": parsed["relation_type"],
        "relation_label": LABEL_BY_TYPE.get(parsed["relation_type"], parsed["relation_type"]),
        "begruendung": str(parsed.get("begruendung", "")).strip(),
        "provider": provider.name,
    }


class FinalizeRequest(BaseModel):
    a_id: int
    b_id: int
    #: RelationType-Name. Leer/None => Beziehung fuer das Paar loeschen.
    relation_type: str | None = None
    #: Notiz zur Beziehung (z.B. die KI-Begruendung). Sie landet in
    #: crew_relations.notes und fliesst in die Auftragsgenerierung ein — die
    #: KI erfaehrt dadurch das WARUM. None => bestehende Notiz unveraendert
    #: lassen; "" => Notiz leeren.
    notes: str | None = None


@router.post("/finalize")
async def finalize_pair(
    payload: FinalizeRequest, session: AsyncSession = Depends(get_session)
):
    """Finalen, symmetrischen Wert eines Paares in die echte Matrix schreiben.

    Schreibt nach crew_relations (kanonisch crew_a_id < crew_b_id) — das ist
    der Stand, den Auftragsgenerierung und Story tatsaechlich lesen. Bewusst
    ein einzelner, per Hand ausgeloester Schritt: die Erhebung sammelt
    Wuensche, HIER wird entschieden, was gilt.
    """
    if payload.a_id == payload.b_id:
        raise HTTPException(400, "Ein Paar braucht zwei verschiedene Gruppierungen")
    for cid in (payload.a_id, payload.b_id):
        if not await session.get(Crew, cid):
            raise HTTPException(404, f"Gruppierung {cid} nicht gefunden")

    lo, hi = sorted((payload.a_id, payload.b_id))
    row = (await session.execute(
        select(CrewRelation).where(
            CrewRelation.crew_a_id == lo, CrewRelation.crew_b_id == hi
        )
    )).scalar_one_or_none()

    # Leerer Typ = Beziehung entfernen (zurueck auf implizit neutral).
    if not (payload.relation_type or "").strip():
        if row:
            await session.delete(row)
            await session.commit()
            return {"ok": True, "aktion": "geloescht"}
        return {"ok": True, "aktion": "war schon leer"}

    try:
        rel = RelationType[payload.relation_type]
    except KeyError:
        raise HTTPException(400, f"Unbekannter Beziehungstyp: {payload.relation_type!r}")

    if row:
        row.relation_type = rel
        if payload.notes is not None:
            row.notes = payload.notes.strip()
        aktion = "aktualisiert"
    else:
        session.add(CrewRelation(
            crew_a_id=lo, crew_b_id=hi, relation_type=rel,
            notes=(payload.notes or "").strip(),
        ))
        aktion = "angelegt"
    await session.commit()
    return {"ok": True, "aktion": aktion, "relation_type": rel.name}


@router.delete("/proposal")
async def delete_proposal(
    from_crew_id: int,
    to_crew_id: int,
    session: AsyncSession = Depends(get_session),
):
    """EINE Richtung loeschen — was Gruppierung A ueber B gesagt hat.

    Die Gegenrichtung bleibt stehen. Nuetzlich, wenn eine einzelne Angabe
    erkennbar daneben liegt und neu abgefragt werden soll.
    """
    row = (await session.execute(
        select(RelationProposal).where(
            RelationProposal.from_crew_id == from_crew_id,
            RelationProposal.to_crew_id == to_crew_id,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Keine Einschätzung für diese Richtung")
    await session.delete(row)
    await session.commit()
    return {"ok": True, "geloescht": 1}


@router.delete("/pair")
async def delete_pair(
    a_id: int,
    b_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Beide Richtungen eines Paares loeschen."""
    rows = (await session.execute(
        select(RelationProposal).where(
            RelationProposal.from_crew_id.in_([a_id, b_id]),
            RelationProposal.to_crew_id.in_([a_id, b_id]),
        )
    )).scalars().all()
    for r in rows:
        await session.delete(r)
    await session.commit()
    return {"ok": True, "geloescht": len(rows)}


@router.delete("/crew/{crew_id}")
async def delete_crew_proposals(crew_id: int, session: AsyncSession = Depends(get_session)):
    """Alles verwerfen, was EINE Gruppierung abgegeben hat — damit sie neu
    bewerten kann, ohne dass alle anderen von vorn anfangen muessen."""
    rows = (await session.execute(
        select(RelationProposal).where(RelationProposal.from_crew_id == crew_id)
    )).scalars().all()
    for r in rows:
        await session.delete(r)
    await session.commit()
    return {"ok": True, "geloescht": len(rows)}


@router.delete("/reset")
async def reset_survey(session: AsyncSession = Depends(get_session)):
    """Alle Roh-Einschaetzungen verwerfen. CrewRelation bleibt unangetastet."""
    rows = (await session.execute(select(RelationProposal))).scalars().all()
    for r in rows:
        await session.delete(r)
    await session.commit()
    return {"ok": True, "geloescht": len(rows)}

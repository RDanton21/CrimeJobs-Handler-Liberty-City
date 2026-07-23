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

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import require_admin
from .config import settings
from .db import get_session
from .models import Crew, RelationProposal, RelationType, SurveyMessage

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

            pairs.append({
                "a_id": a.id, "a_name": a.name,
                "b_id": b.id, "b_name": b.name,
                "a_zu_b": ab_t, "a_zu_b_label": LABEL_BY_TYPE.get(ab_t or "", ""),
                "b_zu_a": ba_t, "b_zu_a_label": LABEL_BY_TYPE.get(ba_t or "", ""),
                "status": status,
                "abstand": abstand,
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

"""Helfer fuer die Chronik-Karten (Reihenfolge + Pfade).

Die Reihenfolge kommt aus docs/CITY_CHRONIK.md (Tages-Eintraege), die Bilder
liegen als docs/chronik_cards/chronik_TT-MM.png vor (via scripts/chronik_render.py).
"""
import datetime
import os
import re

YEAR = 2026  # Kanon-Jahr der Chronik (siehe CITY_CHRONIK.md)

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /app
DOCS = os.path.join(_APP, "docs")
CHRON_MD = os.path.join(DOCS, "CITY_CHRONIK.md")
# Karten liegen im geteilten data-Volume, damit Backend (rendern/anzeigen)
# und Bot (posten) exakt dieselben Dateien sehen.
CARDS_DIR = os.path.join(_APP, "data", "chronik_cards")


def card_date(date_label: str) -> datetime.date | None:
    """'29.07' -> date(2026, 7, 29); None wenn unparsbar."""
    try:
        d, mth = date_label.split(".")[:2]
        return datetime.date(YEAR, int(mth), int(d))
    except (ValueError, TypeError):
        return None


def ordered_dates() -> list[str]:
    """['05.07', '07.07', ...] in Chronik-Reihenfolge."""
    if not os.path.exists(CHRON_MD):
        return []
    head = open(CHRON_MD, encoding="utf-8").read().split("## Gruppen-Lagebild")[0]
    out = []
    for line in head.splitlines():
        m = re.match(r"^\*\*(\d{2}\.\d{2})\.\*\*", line)
        if m:
            out.append(m.group(1))
    return out


def card_filename(date_label: str) -> str:
    return f"chronik_{date_label.replace('.', '-')}.png"


def ordered_cards() -> list[dict]:
    out = []
    for d in ordered_dates():
        fn = card_filename(d)
        p = os.path.join(CARDS_DIR, fn)
        out.append({"date": d, "filename": fn, "path": p, "exists": os.path.exists(p)})
    return out


def card_path(filename: str) -> str | None:
    """Nur Dateien aus der Reihenfolge zulassen (Path-Traversal-Schutz)."""
    valid = {card_filename(d) for d in ordered_dates()}
    if filename not in valid:
        return None
    p = os.path.join(CARDS_DIR, filename)
    return p if os.path.exists(p) else None


def date_from_filename(filename: str) -> str | None:
    """'chronik_29-07.png' -> '29.07' (nur gueltige Reihenfolge-Dateien, ohne exists-Pruefung)."""
    for d in ordered_dates():
        if card_filename(d) == filename:
            return d
    return None

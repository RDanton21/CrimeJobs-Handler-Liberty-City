"""
Konfigurierbare Bot-Nachrichten (Embed-Texte, Modal-Titel, etc.).
Gespeichert in data/messages.json, editierbar im Admin-Panel.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MESSAGES_FILE = ROOT / "data" / "messages.json"

DEFAULTS = {
    # Ticket-Eroeffnungs-Embed
    "ticket_title":       "🎫 Ticket geöffnet",
    "ticket_description": "Hi {mention}! Beschreib dein Anliegen.\n\nIch beantworte Fragen automatisch aus der Wissensbasis. Bei Unklarheiten meldet sich ein Mod.",
    # Support-Panel Embed (/panel)
    "panel_title":        "🎫 Support",
    "panel_description":  "**Ticket eröffnen** — Privater Channel, KI antwortet auf Fragen.\n**Direkte Frage** — Schnelle Antwort ohne Ticket (nur du siehst sie).",
    # Button "Direkte Frage"
    "ask_btn_label":      "Direkte Antwort auf deine Frage, nur du siehst die Antwort !",
    # Modal "Direkte Frage"
    "modal_title":        "Frage an die Wissensbasis",
    "modal_label":        "Deine Frage",
    "modal_placeholder":  "z.B. Wie bewerbe ich mich?",
    # --- Crime ---
    "crime_btn_anmelden":   "Crime anmelden",
    "crime_btn_abmelden":   "Crime abmelden",
    "crime_modal_anmelden": "Crime Anmelden",
    "crime_modal_abmelden": "Crime Abmelden",
    "crime_embed_title":    "🔫 Crime {typ} — Ticket",
    # --- Gewerbe ---
    "gewerbe_modal_title":  "Gewerbe Bewerbung",
    "gewerbe_embed_title":  "🏪 Gewerbe Bewerbung — Ticket",
    # --- Staatlich ---
    "staatlich_modal_title": "Staatliche Fraktion Bewerbung",
    "staatlich_embed_title": "🏛 Staatliche Fraktion Bewerbung — Ticket",
    # --- Team Bewerbung ---
    "team_modal_title":  "Team Bewerbung",
    "team_embed_title":  "👥 Team Bewerbung — Ticket",
    # --- Questgeber Bewerbung ---
    "questgeber_modal_title": "Questgeber Bewerbung",
    "questgeber_embed_title": "🎯 Questgeber Bewerbung — Ticket",
}


def _load() -> dict:
    try:
        data = json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))
        # Fehlende Keys mit Defaults auffuellen
        return {**DEFAULTS, **data}
    except Exception:
        return dict(DEFAULTS)


def get(key: str) -> str:
    """Gibt einen konfigurierten Text zurueck (Fallback: Default)."""
    return _load().get(key, DEFAULTS.get(key, ""))


def get_all() -> dict:
    """Gibt alle Nachrichten zurueck."""
    return _load()


def save(updates: dict) -> bool:
    """Speichert geaenderte Felder. Unbekannte Keys werden ignoriert."""
    try:
        current = _load()
        for k, v in updates.items():
            if k in DEFAULTS:
                current[k] = v.strip()
        MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = MESSAGES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, MESSAGES_FILE)
        return True
    except Exception:
        return False

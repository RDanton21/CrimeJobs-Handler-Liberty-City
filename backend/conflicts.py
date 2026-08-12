"""Selbst gemeldete Konflikte/Beef der Gruppierungen.

Speicherung als JSON im geteilten data-Volume (persistent, wie crime.db):
    { "<Gang-Name>": ["<Feind-Name>", ...], ... }

Wird (a) auf der Seite /konflikte angezeigt und (b) in die Auftrags-Generierung
eingespeist (siehe _load_context in routes_missions.py).
"""
import json
import os
from pathlib import Path

CONFLICTS_FILE = Path(os.environ.get("CONFLICTS_FILE", "/app/data/crew_conflicts.json"))


def load_conflicts() -> dict[str, list[str]]:
    """Liest die Konflikt-Map. Bei Fehler/leer -> {}."""
    try:
        if CONFLICTS_FILE.exists():
            data = json.loads(CONFLICTS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # nur saubere {str: [str,...]}-Eintraege zurueckgeben
                out: dict[str, list[str]] = {}
                for k, v in data.items():
                    if isinstance(k, str) and isinstance(v, list):
                        out[k] = [str(x) for x in v if isinstance(x, str)]
                return out
    except Exception:
        pass
    return {}


def save_conflicts(data: dict) -> None:
    """Schreibt die Konflikt-Map (atomar genug fuer unseren Zweck)."""
    clean: dict[str, list[str]] = {}
    for k, v in (data or {}).items():
        if isinstance(k, str) and k.strip():
            enemies = [str(x).strip() for x in v if isinstance(v, list) and str(x).strip()] if isinstance(v, list) else []
            clean[k.strip()] = enemies
    CONFLICTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFLICTS_FILE.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def conflicts_for(crew_name: str) -> list[str]:
    """Feinde einer bestimmten Gang (case-insensitiv, tolerant ggü. 'The ')."""
    if not crew_name:
        return []
    data = load_conflicts()
    if crew_name in data:
        return data[crew_name]
    norm = crew_name.strip().lower().removeprefix("the ").strip()
    for k, v in data.items():
        if k.strip().lower().removeprefix("the ").strip() == norm:
            return v
    return []

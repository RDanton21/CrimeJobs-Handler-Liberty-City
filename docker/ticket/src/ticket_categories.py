"""
Ticket-Kategorien: Konfigurierbare Buttons im Support-Panel.
JSON-persistiert unter data/ticket_categories.json.

Jede Kategorie hat: id (Slug), label, emoji, enabled, order, description.
Beim ersten Start werden Standard-Kategorien angelegt.
"""
import json
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES_FILE = ROOT / "data" / "ticket_categories.json"

_SLUG_RE = re.compile(r"[^a-z0-9-]")

DEFAULTS: List[Dict[str, Any]] = [
    {"id": "crime",      "label": "Crime",               "emoji": "🔫", "description": "",  "enabled": True,  "ai_enabled": False, "order": 0},
    {"id": "gewerbe",    "label": "Gewerbe",              "emoji": "🏪", "description": "",  "enabled": True,  "ai_enabled": False, "order": 1},
    {"id": "staatlich",  "label": "Staatliche Fraktion",  "emoji": "🏛", "description": "",  "enabled": True,  "ai_enabled": False, "order": 2},
    {"id": "sonstiges",  "label": "Sonstiges",            "emoji": "❓", "description": "",  "enabled": True,  "ai_enabled": True,  "order": 3},
]


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("", text.lower().replace(" ", "-").replace("ä", "ae")
                        .replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))[:32]


def _load() -> List[Dict[str, Any]]:
    if not CATEGORIES_FILE.exists():
        return [dict(d) for d in DEFAULTS]
    try:
        data = json.loads(CATEGORIES_FILE.read_text(encoding="utf-8"))
        return data if data else [dict(d) for d in DEFAULTS]
    except Exception:
        return [dict(d) for d in DEFAULTS]


def _save(items: List[Dict[str, Any]]):
    CATEGORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CATEGORIES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CATEGORIES_FILE)


def list_all() -> List[Dict[str, Any]]:
    """Alle Kategorien, sortiert nach order."""
    return sorted(_load(), key=lambda c: c.get("order", 99))


def list_enabled() -> List[Dict[str, Any]]:
    """Nur aktivierte Kategorien, sortiert nach order."""
    return [c for c in list_all() if c.get("enabled", True)]


def get(cat_id: str) -> Optional[Dict[str, Any]]:
    for c in _load():
        if c.get("id") == cat_id:
            return c
    return None


def create(label: str, emoji: str = "🎫", description: str = "") -> Dict[str, Any]:
    items = _load()
    slug = _slugify(label) or "kategorie"
    existing_ids = {c["id"] for c in items}
    base, counter = slug, 2
    while slug in existing_ids:
        slug = f"{base}-{counter}"
        counter += 1
    cat: Dict[str, Any] = {
        "id": slug,
        "label": label.strip(),
        "emoji": emoji.strip() or "🎫",
        "description": description.strip(),
        "enabled": True,
        "ai_enabled": False,
        "order": len(items),
    }
    items.append(cat)
    _save(items)
    return cat


def update(cat_id: str, label: str, emoji: str, description: str = "") -> bool:
    items = _load()
    for c in items:
        if c["id"] == cat_id:
            c["label"] = label.strip()
            c["emoji"] = emoji.strip() or "🎫"
            c["description"] = description.strip()
            _save(items)
            return True
    return False


def delete(cat_id: str) -> bool:
    items = _load()
    new = [c for c in items if c["id"] != cat_id]
    if len(new) == len(items):
        return False
    _save(new)
    return True


def set_ai_enabled(cat_id: str, value: bool) -> bool:
    """Setzt ai_enabled für eine Kategorie."""
    items = _load()
    for c in items:
        if c["id"] == cat_id:
            c["ai_enabled"] = bool(value)
            _save(items)
            return True
    return False


def toggle(cat_id: str) -> Optional[bool]:
    """Aktiviert/deaktiviert eine Kategorie. Gibt neuen Zustand zurück."""
    items = _load()
    for c in items:
        if c["id"] == cat_id:
            c["enabled"] = not c.get("enabled", True)
            _save(items)
            return c["enabled"]
    return None


def move(cat_id: str, direction: int):
    """Verschiebt eine Kategorie um ±1 in der Reihenfolge."""
    items = list_all()
    idx = next((i for i, c in enumerate(items) if c["id"] == cat_id), None)
    if idx is None:
        return
    new_idx = max(0, min(len(items) - 1, idx + direction))
    if new_idx != idx:
        items.insert(new_idx, items.pop(idx))
        for i, c in enumerate(items):
            c["order"] = i
        _save(items)


def init_defaults():
    """Legt Standard-Kategorien an, falls die Datei noch nicht existiert."""
    if not CATEGORIES_FILE.exists():
        _save([dict(d) for d in DEFAULTS])

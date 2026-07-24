"""
Verwaltung der wählbaren Bereiche für Team-Bewerbungen.
JSON-persistiert unter data/team_areas.json.
"""
import json
import os
from pathlib import Path
from typing import List, Dict, Any

ROOT = Path(__file__).resolve().parent.parent
AREAS_FILE = ROOT / "data" / "team_areas.json"

DEFAULTS: List[Dict[str, Any]] = [
    {"id": "fivem-developer",    "label": "FiveM Developer",         "emoji": "💻", "order": 0},
    {"id": "frontend-developer", "label": "Frontend/NUI-Entwickler", "emoji": "🖥️", "order": 1},
    {"id": "clothing",           "label": "Clothing",                "emoji": "👕", "order": 2},
    {"id": "designer",           "label": "Designer",                "emoji": "🎨", "order": 3},
    {"id": "video",              "label": "Video",                   "emoji": "🎬", "order": 4},
    {"id": "sonstiges",          "label": "Sonstiges",               "emoji": "❓", "order": 5},
]


def _load() -> List[Dict[str, Any]]:
    if not AREAS_FILE.exists():
        return [dict(d) for d in DEFAULTS]
    try:
        data = json.loads(AREAS_FILE.read_text(encoding="utf-8"))
        return data if data else [dict(d) for d in DEFAULTS]
    except Exception:
        return [dict(d) for d in DEFAULTS]


def _save(items: List[Dict[str, Any]]) -> None:
    AREAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AREAS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, AREAS_FILE)


def list_all() -> List[Dict[str, Any]]:
    return sorted(_load(), key=lambda a: a.get("order", 99))


def create(label: str, emoji: str = "🎯") -> Dict[str, Any]:
    items = _load()
    slug = label.lower().replace(" ", "-").replace("/", "-")[:32]
    existing = {a["id"] for a in items}
    base, n = slug, 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    area: Dict[str, Any] = {
        "id": slug,
        "label": label.strip(),
        "emoji": emoji.strip() or "🎯",
        "order": len(items),
    }
    items.append(area)
    _save(items)
    return area


def delete(area_id: str) -> bool:
    items = _load()
    new = [a for a in items if a["id"] != area_id]
    if len(new) == len(items):
        return False
    _save(new)
    return True


def move(area_id: str, direction: int) -> None:
    items = list_all()
    idx = next((i for i, a in enumerate(items) if a["id"] == area_id), None)
    if idx is None:
        return
    new_idx = max(0, min(len(items) - 1, idx + direction))
    if new_idx != idx:
        items.insert(new_idx, items.pop(idx))
        for i, a in enumerate(items):
            a["order"] = i
        _save(items)


def init_defaults() -> None:
    if not AREAS_FILE.exists():
        _save([dict(d) for d in DEFAULTS])

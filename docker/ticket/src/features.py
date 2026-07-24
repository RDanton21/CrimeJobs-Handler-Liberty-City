"""
Feature-Flags: Snippets und Wissensbasis (RAG) ein-/ausschalten.
Gespeichert in data/features.json, editierbar im Admin-Panel.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEATURES_FILE = ROOT / "data" / "features.json"

DEFAULTS = {
    "snippets_enabled":    True,
    "rag_enabled":         True,
    "ticket_open_enabled": True,
    "ask_btn_enabled":     True,
}

# mtime-Cache: Datei nur bei Änderung neu lesen
_cache: dict = {}
_cache_mtime: float = -1.0


def get() -> dict:
    """Gibt aktuelle Feature-Flags zurück (mit Defaults für fehlende Keys)."""
    global _cache, _cache_mtime
    try:
        mtime = FEATURES_FILE.stat().st_mtime
        if mtime != _cache_mtime:
            data = json.loads(FEATURES_FILE.read_text(encoding="utf-8"))
            _cache = {**DEFAULTS, **data}
            _cache_mtime = mtime
        return dict(_cache)
    except Exception:
        return dict(DEFAULTS)


def set_feature(key: str, value: bool) -> bool:
    """Setzt einen Feature-Flag. Gibt True bei Erfolg zurück."""
    if key not in DEFAULTS:
        return False
    try:
        current = get()
        current[key] = bool(value)
        FEATURES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FEATURES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, FEATURES_FILE)
        # Cache invalidieren
        global _cache_mtime
        _cache_mtime = -1.0
        return True
    except Exception:
        return False

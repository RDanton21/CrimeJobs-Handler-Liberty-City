"""Top-donator leaderboard over case_files.jsonl.

Two scopes:
- "all"     -> entire history
- "current" -> events with created_at >= current_stream_start.json["started_at"]

Handles both jsonl record shapes:
- sanitized:  {case_id, source, category, username, amount, created_at, ...}
- raw kofi:   {ts, type:"kofi", data:{from_name, amount_brutto_eur, amount_netto_eur}}

Anonymous donors ("Unbekannt"/"Anonymous"/empty) are bucketed as "Anonym".

Results are cached in-process for LEADERBOARD_CACHE_TTL seconds to keep
the OBS overlay's polling cheap.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

CASE_FILE_DEFAULT = "case_files.jsonl"
STREAM_START_DEFAULT = "current_stream_start.json"
ANON_BUCKET = "Anonym"
ANON_KEYS = {"", "unbekannt", "anonymous", "anonym", "none", "null"}

_CACHE_TTL = float(os.getenv("LEADERBOARD_CACHE_TTL", "60"))
_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize_name(raw: Optional[str]) -> str:
    name = (raw or "").strip()
    if name.lower() in ANON_KEYS:
        return ANON_BUCKET
    return name


def _extract_event(rec: Dict[str, Any]) -> Optional[Tuple[str, float, datetime]]:
    """Return (donor_name, amount_eur, created_at) or None if record is unusable."""
    # raw kofi shape
    if rec.get("type") == "kofi" and isinstance(rec.get("data"), dict):
        data = rec["data"]
        name = _normalize_name(data.get("from_name") or data.get("username"))
        amount = data.get("amount_netto_eur")
        if amount is None:
            amount = data.get("amount_brutto_eur") or data.get("amount") or 0
        try:
            amount_f = float(amount)
        except (TypeError, ValueError):
            return None
        ts = _parse_iso(str(rec.get("ts", "")))
        if ts is None:
            return None
        return name, amount_f, ts

    # sanitized / live shape
    source = (rec.get("source") or "").upper()
    if source not in {"TWITCH", "KOFI", "TEBEX"}:
        return None
    name = _normalize_name(rec.get("username"))
    amount = rec.get("amount")
    try:
        amount_f = float(amount) if amount is not None else 0.0
    except (TypeError, ValueError):
        amount_f = 0.0
    ts = _parse_iso(str(rec.get("created_at", "")))
    if ts is None:
        return None
    return name, amount_f, ts


def _read_cases(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logging.warning("leaderboard: read %s failed: %s", path, e)
    return out


def _stream_start(path: str) -> Optional[datetime]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        return _parse_iso(str(data.get("started_at", "")))
    except Exception:
        return None


def _aggregate(records: List[Dict[str, Any]], cutoff: Optional[datetime]) -> List[Dict[str, Any]]:
    totals: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        ev = _extract_event(rec)
        if not ev:
            continue
        name, amount, ts = ev
        if cutoff is not None and ts < cutoff:
            continue
        if amount <= 0:
            # still count for "events", but only count name once
            entry = totals.setdefault(name, {"name": name, "total_eur": 0.0, "events": 0})
            entry["events"] += 1
            continue
        entry = totals.setdefault(name, {"name": name, "total_eur": 0.0, "events": 0})
        entry["total_eur"] = round(entry["total_eur"] + amount, 2)
        entry["events"] += 1
    return sorted(
        totals.values(),
        key=lambda e: (-e["total_eur"], -e["events"], e["name"].lower()),
    )


def top_donors(
    scope: str = "all",
    *,
    limit: int = 10,
    case_file: str = CASE_FILE_DEFAULT,
    stream_start_file: str = STREAM_START_DEFAULT,
) -> List[Dict[str, Any]]:
    scope = (scope or "all").lower()
    cache_key = f"{scope}:{case_file}:{stream_start_file}"

    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1][:limit]

    records = _read_cases(case_file)
    cutoff = _stream_start(stream_start_file) if scope == "current" else None
    ranked = _aggregate(records, cutoff)

    with _cache_lock:
        _cache[cache_key] = (time.time(), ranked)

    return ranked[:limit]


def invalidate_cache() -> None:
    with _cache_lock:
        _cache.clear()


def reset_current_stream(stream_start_file: str = STREAM_START_DEFAULT) -> str:
    """Mark "now" as the start of the current stream. Returns the ISO timestamp."""
    now_iso = datetime.now(timezone.utc).isoformat()
    tmp = f"{stream_start_file}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"started_at": now_iso}, f)
        os.replace(tmp, stream_start_file)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    invalidate_cache()
    return now_iso

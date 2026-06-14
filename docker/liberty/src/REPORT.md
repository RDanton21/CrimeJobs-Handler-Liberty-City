# Liberty City Relay — Code Audit

## Status

CRITICAL + HIGH findings fixed on branch `fix/critical-high-audit` (this PR).
MEDIUM + LOW findings are tracked below for follow-up.

---

## Resolved (CRITICAL + HIGH)

| ID | Finding | Fix |
|----|---------|-----|
| C1 | Ko-fi token: plaintext `==` (timing-attack surface) | `hmac.compare_digest` in `liberty_city_relay.py` + `stream_relay.py` |
| C2 | Flask bound to `0.0.0.0` by default (LAN/Internet exposure) | Default `127.0.0.1` for all three servers; `0.0.0.0` only when explicitly set |
| C3 | `stats.json` / dedupe / status / goal JSON written non-atomically (corruption on mid-write crash) | `_save_json` writes to `*.tmp.<pid>` + fsync + `os.replace` |
| C4 | CORS `Access-Control-Allow-Origin: *` on `/api/stats` | Echo only matching `OBS_OVERLAY_ORIGIN` (default loopback) |
| H1 | `is_duplicate` read-check-write race | Wrapped in dedicated `DEDUPE_LOCK` |
| H2 | Goal embed re-fires on every restart once reached | `ensure_goal_embed_on_startup` skips if `posted_at` < 1 h ago |
| H3 | Float compounding on EUR (`0.1 + 0.2 != 0.3`) | `money_add` / `money_mul` helpers (Decimal → 2-decimal `HALF_UP` → float) |
| H4 | `time.sleep` for 429 retry blocks Flask request thread | Sync first attempt; 429 retry scheduled on `threading.Timer`; `on_message_id` callback persists Discord msg-id from either path |
| H5 | `service.log` grew unbounded (already 2 MB) | `RotatingFileHandler` 10 MB × 5 backups, configurable via env |
| H6 | `stream_hub.py` truncated / non-functional | File removed |
| H7 | "EventSub signature not verified" (audit flag) | False alarm for the **websocket** transport used here: twitchAPI verifies session ownership per-message internally. HMAC header check exists only for the **HTTP webhook** transport variant, which this project does not use. Comment added at `liberty_city_relay.py` setup site. |
| H8 | `requirements.txt` unpinned | Pinned `flask==3.0.3`, `requests==2.32.3`, `python-dotenv==1.0.1`, `twitchAPI==4.3.0` |

---

## Open (MEDIUM)

| ID | Finding | File / Line | Suggested Fix |
|----|---------|-------------|---------------|
| M1 | `stream_relay.py:15` logged first 6 chars of `KOFI_VERIFICATION_TOKEN` (resolved as part of C1 commit by switching to length-only log) | `stream_relay.py:15` | Already mitigated |
| M2 | `requests.post` does not enforce that `DISCORD_WEBHOOK_URL` is a discord.com host. Currently only an env value, but should be validated to harden against an attacker who can write `.env` | `liberty_city_relay.py:354, 384` | `urlparse(DISCORD_WEBHOOK_URL).netloc.endswith("discord.com")` check on startup |
| M3 | Dedupe JSON: corrupted file silently returns default `{}`; no warning logged | `liberty_city_relay.py:_dedupe_load` | Log WARNING when file exists but `json.load` fails |
| M4 | `goal_reached_state.json` can be deleted manually; service forgets the goal was reached | `liberty_city_relay.py:_goal_state` | Persist `goal_amount` + checksum, validate on load |
| M5 | Goal-state schema does not record which `GOAL_NETTO_EUR` value the embed was posted against; raising the goal mid-event resets `posted` semantics incorrectly | `liberty_city_relay.py:_goal_state` | Store `goal_amount` in state; on load, reset `posted=False` if env goal differs |

## Open (LOW)

| ID | Finding | File / Line | Suggested Fix |
|----|---------|-------------|---------------|
| L1 | `start_relays.bat` uses `cmd /k` with quoted python path; safe today but quoting is brittle if `%PY%` contains spaces | `start_relays.bat:17` | Wrap full command in additional quotes: `start "" "%PY%" "liberty_city_relay.py"` |
| L2 | `discord_delete` does not branch on HTTP 404 ("message already deleted") — falls into the generic logger | `liberty_city_relay.py:380-388` | Treat 404 as success and clear stored msg-id |
| L3 | Dedupe timestamps use `time.time()` (local epoch); other timestamps use `datetime.now(timezone.utc).isoformat()` (UTC). The two never compare so it is not a bug, just inconsistent | `liberty_city_relay.py:325` | Either standardise to UTC-isoformat or document the intentional split |
| L4 | EventSub websocket has no SIGTERM hook; on Windows service-stop the asyncio loop can leave a stale connection for the connection-close timeout | `liberty_city_relay.py:946-964` | Register `signal.SIGTERM` → `asyncio.run_coroutine_threadsafe(relay.eventsub.stop(), loop)` |

---

## Notes

- The case-files log (`case_files.jsonl`) is written by an earlier version of the script (the version on disk in this repo no longer references it). The dashboard reads it. If you re-introduce JSONL writing, route it through the same atomic helper.
- `_dedupe_load` uses `FILE_LOCK` internally; the new `DEDUPE_LOCK` is held *around* that call, not inside it. Lock order is consistent (DEDUPE_LOCK → FILE_LOCK).

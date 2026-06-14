"""SEKTOR Countdown — Admin-Panel (Flask).

Verwaltet countdowns.json: Countdowns anlegen / bearbeiten / loeschen.
Der Bot (bot.py) liest die Datei per Hot-Reload — Aenderungen greifen ohne
Bot-Neustart. Laeuft lokal auf 127.0.0.1, ohne Login.
"""
import html
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, request, redirect

ROOT = Path(__file__).parent
COUNTDOWNS_PATH = ROOT / "countdowns.json"
BERLIN = ZoneInfo("Europe/Berlin")
HOST, PORT = "127.0.0.1", 5601

app = Flask(__name__)


# ── Persistenz ───────────────────────────────────────────
def load_data() -> dict:
    try:
        d = json.loads(COUNTDOWNS_PATH.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError
    except Exception:
        d = {}
    d.setdefault("update_seconds", 60)
    d.setdefault("countdowns", [])
    return d


def save_data(d: dict) -> None:
    tmp = COUNTDOWNS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(COUNTDOWNS_PATH)


def find(d: dict, cid: str):
    for c in d["countdowns"]:
        if c.get("id") == cid:
            return c
    return None


def parse_channel(s: str):
    """Channel-/Thread-ID aus rohem ID-String ODER Discord-Link extrahieren.

    Akzeptiert:  123456789012345678
                 https://discord.com/channels/<server>/<channel-oder-thread>[/<msg>]
    Gibt int zurueck oder None bei ungueltiger Eingabe.
    """
    s = (s or "").strip()
    m = re.search(r"channels/\d+/(\d+)", s)
    if m:
        return int(m.group(1))
    if s.isdigit():
        return int(s)
    return None


# ── Datums-Helfer ────────────────────────────────────────
def iso_to_input(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return ""


def input_to_iso(s: str) -> str:
    """datetime-local (deutsche Wandzeit) -> ISO mit korrektem DST-Offset."""
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=BERLIN).isoformat()


def status_label(c: dict) -> tuple[str, str]:
    """(Text, css-Klasse) fuer den Status-Badge."""
    if not c.get("enabled", True):
        return "Deaktiviert", "off"
    try:
        target = datetime.fromisoformat(c["target_iso"])
    except Exception:
        return "Ungueltig", "off"
    if datetime.now(timezone.utc) >= target:
        return "Abgelaufen / Live", "live"
    return "Laeuft", "run"


# ── HTML ─────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0a0612;--surface:#0f0f1c;--surface2:#17172a;--border:#2c2c4a;
--primary:#e64560;--cyan:#02eaff;--purple:#7040c0;--text:#f5f3ff;--muted:#9aa0b4}
body{font-family:'Inter','Segoe UI',system-ui,sans-serif;color:var(--text);min-height:100vh;
background:radial-gradient(ellipse 55% 50% at 25% 60%,rgba(230,69,96,.20)0%,transparent 70%),
radial-gradient(ellipse 45% 45% at 80% 8%,rgba(2,234,255,.16)0%,transparent 65%),var(--bg);
background-attachment:fixed;padding-bottom:50px}
a{color:var(--cyan);text-decoration:none}
.top{display:flex;align-items:center;gap:14px;padding:18px 28px;background:rgba(15,15,28,.9);
position:relative;border-bottom:1px solid transparent}
.top::after{content:'';position:absolute;left:0;right:0;bottom:0;height:2px;
background:linear-gradient(90deg,#7040c0,#d42070 50%,#0fb8c9)}
.brand{font-size:1.5rem;font-weight:900;letter-spacing:3px;
background:linear-gradient(90deg,#43305c,#853f61 50%,#e64560);-webkit-background-clip:text;
background-clip:text;-webkit-text-fill-color:transparent}
.brand span{background:linear-gradient(90deg,#e64560,#02eaff);-webkit-background-clip:text;
background-clip:text;-webkit-text-fill-color:transparent}
.sub{font-size:.7rem;font-weight:600;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}
main{max-width:780px;margin:28px auto;padding:0 20px}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.16em;color:var(--muted);margin:22px 0 12px}
.card{background:linear-gradient(180deg,rgba(23,23,42,.72),rgba(15,15,28,.72));
border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin-bottom:12px}
.cd-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.cd-badge{font-size:.66rem;font-weight:700;letter-spacing:.12em;color:var(--primary);
border:1px solid var(--primary);border-radius:999px;padding:3px 10px}
.cd-title{font-size:1.1rem;font-weight:700}
.cd-meta{font-size:.82rem;color:var(--muted);line-height:1.7;font-family:ui-monospace,monospace}
.pill{font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
padding:3px 10px;border-radius:999px}
.pill.run{background:rgba(2,234,255,.14);color:var(--cyan);border:1px solid rgba(2,234,255,.4)}
.pill.live{background:rgba(78,204,163,.14);color:#4ecca3;border:1px solid rgba(78,204,163,.4)}
.pill.off{background:rgba(154,160,180,.12);color:var(--muted);border:1px solid var(--border)}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.btn{display:inline-flex;align-items:center;gap:6px;border:none;border-radius:8px;
padding:8px 16px;font:600 .85rem/1 'Inter',sans-serif;cursor:pointer;text-decoration:none}
.btn-primary{background:linear-gradient(90deg,#43305c,#e64560);color:#fff}
.btn-cyan{background:var(--cyan);color:#03161c}
.btn-ghost{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
.btn-danger{background:#3a1622;color:#ff8095;border:1px solid #5c2336}
.btn:hover{filter:brightness(1.12)}
label{display:block;font-size:.74rem;font-weight:600;color:var(--muted);
text-transform:uppercase;letter-spacing:.06em;margin:14px 0 5px}
input[type=text],input[type=number],input[type=datetime-local]{width:100%;
background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);
padding:10px 12px;font:.92rem 'Inter',sans-serif}
input:focus{outline:none;border-color:var(--primary)}
.check{display:flex;align-items:center;gap:8px;margin-top:14px}
.check input{width:18px;height:18px;accent-color:var(--primary)}
.check label{margin:0;text-transform:none;letter-spacing:0;font-size:.9rem;color:var(--text)}
.hint{font-size:.74rem;color:var(--muted);margin-top:4px}
.flash{background:rgba(78,204,163,.14);border:1px solid rgba(78,204,163,.45);
color:#bef0d2;padding:9px 13px;border-radius:8px;margin-bottom:14px;font-size:.88rem}
.empty{color:var(--muted);font-size:.9rem;padding:8px 0}
"""


def page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<header class="top"><div class="brand">SEKT<span>6</span>R</div>
<div class="sub">Countdown-Verwaltung</div></header>
<main>{body}</main></body></html>"""


def field(label: str, name: str, value: str = "", typ: str = "text",
          hint: str = "") -> str:
    h = f'<div class="hint">{html.escape(hint)}</div>' if hint else ""
    return (f'<label for="{name}">{html.escape(label)}</label>'
            f'<input type="{typ}" id="{name}" name="{name}" '
            f'value="{html.escape(str(value))}">{h}')


def form_page(c: dict, action: str, heading: str) -> str:
    body = f"""<h2>{html.escape(heading)}</h2><div class="card"><form method="post" action="{action}">
{field("Badge (z.B. NR. 03)", "badge", c.get("badge",""))}
{field("Ueberschrift / Titel", "title", c.get("title",""), hint="Die grosse Ueberschrift auf der Karte")}
{field("Subtitle", "subtitle", c.get("subtitle",""))}
{field("Zieldatum & Uhrzeit", "target", iso_to_input(c.get("target_iso","")), "datetime-local", "Deutsche Zeit (Sommer-/Winterzeit automatisch)")}
{field("Channel / Thread", "channel_id", c.get("channel_id",""), "text", "Channel-/Thread-ID ODER ein discord.com/channels/...-Link (auch Thread-Link)")}
{field("YouTube-Link", "youtube_url", c.get("youtube_url",""), "text", "Wird bei Ablauf mit @everyone gepostet")}
<div class="check"><input type="checkbox" id="enabled" name="enabled" {"checked" if c.get("enabled",True) else ""}>
<label for="enabled">Aktiv</label></div>
<div class="row"><button type="submit" class="btn btn-primary">Speichern</button>
<a href="/" class="btn btn-ghost">Abbrechen</a></div></form></div>"""
    return page("Countdown bearbeiten", body)


# ── Routen ───────────────────────────────────────────────
@app.route("/")
def index():
    d = load_data()
    flash = request.args.get("flash", "")
    flash_html = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    cards = []
    for c in d["countdowns"]:
        txt, cls = status_label(c)
        cid = c.get("id", "")
        try:
            tgt = datetime.fromisoformat(c["target_iso"]).strftime("%d.%m.%Y · %H:%M")
        except Exception:
            tgt = "—"
        cards.append(f"""<div class="card">
<div class="cd-head"><span class="cd-badge">{html.escape(c.get('badge','—'))}</span>
<span class="cd-title">{html.escape(c.get('title','—'))}</span>
<span class="pill {cls}">{txt}</span></div>
<div class="cd-meta">{html.escape(c.get('subtitle',''))}<br>
Ziel: {tgt} &nbsp;|&nbsp; Channel: {html.escape(str(c.get('channel_id','—')))}</div>
<div class="row">
<a class="btn btn-ghost" href="/edit/{cid}">Bearbeiten</a>
<form method="post" action="/toggle/{cid}" style="display:inline">
<button class="btn btn-ghost" type="submit">{'Deaktivieren' if c.get('enabled',True) else 'Aktivieren'}</button></form>
<form method="post" action="/delete/{cid}" style="display:inline"
onsubmit="return confirm('Countdown wirklich loeschen? Die Discord-Nachricht wird entfernt.')">
<button class="btn btn-danger" type="submit">Loeschen</button></form>
</div></div>""")
    body = (flash_html
            + '<h2>Countdowns</h2>'
            + ("".join(cards) if cards else '<div class="empty">Noch keine Countdowns angelegt.</div>')
            + '<div class="row"><a class="btn btn-primary" href="/new">+ Neuer Countdown</a></div>')
    return page("Countdown-Verwaltung", body)


@app.route("/new")
def new():
    return form_page({}, "/new", "Neuer Countdown")


@app.route("/edit/<cid>")
def edit(cid):
    c = find(load_data(), cid)
    if not c:
        return redirect("/?flash=Countdown nicht gefunden.")
    return form_page(c, f"/edit/{cid}", "Countdown bearbeiten")


def _from_form() -> dict | str:
    """Formular auslesen. Gibt dict zurueck oder einen Fehlertext (str)."""
    target = (request.form.get("target") or "").strip()
    channel = (request.form.get("channel_id") or "").strip()
    if not target:
        return "Zieldatum fehlt."
    try:
        target_iso = input_to_iso(target)
    except ValueError:
        return "Zieldatum ungueltig."
    cid = parse_channel(channel)
    if cid is None:
        return "Channel/Thread ungueltig — ID oder discord.com/channels/...-Link angeben."
    return {
        "badge": (request.form.get("badge") or "").strip(),
        "title": (request.form.get("title") or "").strip(),
        "subtitle": (request.form.get("subtitle") or "").strip(),
        "target_iso": target_iso,
        "channel_id": cid,
        "youtube_url": (request.form.get("youtube_url") or "").strip(),
        "enabled": request.form.get("enabled") == "on",
    }


@app.route("/new", methods=["POST"])
def new_post():
    parsed = _from_form()
    if isinstance(parsed, str):
        return page("Fehler", f'<div class="flash">{html.escape(parsed)}</div>'
                    '<div class="row"><a class="btn btn-ghost" href="/new">Zurueck</a></div>')
    d = load_data()
    parsed["id"] = "cd_" + uuid.uuid4().hex[:8]
    d["countdowns"].append(parsed)
    save_data(d)
    return redirect("/?flash=Countdown angelegt.")


@app.route("/edit/<cid>", methods=["POST"])
def edit_post(cid):
    parsed = _from_form()
    if isinstance(parsed, str):
        return page("Fehler", f'<div class="flash">{html.escape(parsed)}</div>'
                    f'<div class="row"><a class="btn btn-ghost" href="/edit/{cid}">Zurueck</a></div>')
    d = load_data()
    c = find(d, cid)
    if not c:
        return redirect("/?flash=Countdown nicht gefunden.")
    c.update(parsed)
    save_data(d)
    return redirect("/?flash=Countdown gespeichert.")


@app.route("/toggle/<cid>", methods=["POST"])
def toggle(cid):
    d = load_data()
    c = find(d, cid)
    if c:
        c["enabled"] = not c.get("enabled", True)
        save_data(d)
    return redirect("/")


@app.route("/delete/<cid>", methods=["POST"])
def delete(cid):
    d = load_data()
    d["countdowns"] = [c for c in d["countdowns"] if c.get("id") != cid]
    save_data(d)
    return redirect("/?flash=Countdown geloescht. Der Bot entfernt die Nachricht.")


if __name__ == "__main__":
    print(f"[countdown-admin] http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)

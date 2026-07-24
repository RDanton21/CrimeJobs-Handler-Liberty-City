"""
Admin-Backend fuer Ticket-Tool im SEKTOR-Design.
Flask-App auf localhost + Basic-Auth.

Features:
- Login (Basic-Auth)
- Dashboard (Bot-Status, KB-Stats, Snippet-Hits)
- Discord-Konfiguration (Token, Guild-ID, Mod-Role)
- KB-Manager (Upload/List/Delete)
- Snippets (Q&A-Textbausteine, CRUD, Hit-Counter)
- Reindex-Trigger
- Log-Viewer
- Bot Start/Stop/Restart
"""
import html
import json
import os
import secrets
import sys
import subprocess
import signal
from pathlib import Path
from datetime import datetime

from flask import Flask, request, redirect, url_for, render_template_string, flash, jsonify, send_from_directory, send_file, abort, session
from markupsafe import Markup
from dotenv import load_dotenv, dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "kb"
LOG_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
ENV_FILE = ROOT / ".env"
BOT_PID_FILE = DATA_DIR / "bot.pid"
TICKET_COUNTER_FILE = DATA_DIR / "ticket_counter.json"
PANEL_RESEND_FLAG = DATA_DIR / "panel_resend.flag"


def _get_ticket_count() -> int:
    try:
        return int(json.loads(TICKET_COUNTER_FILE.read_text(encoding="utf-8")).get("count", 0))
    except Exception:
        return 0


def _set_ticket_count(n: int):
    TICKET_COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TICKET_COUNTER_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"count": n}), encoding="utf-8")
    os.replace(tmp, TICKET_COUNTER_FILE)

load_dotenv(ENV_FILE)

ADMIN_USER = os.getenv("ADMIN_USER", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change_me_please").strip()
ADMIN_PORT = int(os.getenv("ADMIN_PORT", "5555").strip())

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", os.urandom(32).hex())


class _NoAuth:
    """Auth deaktiviert — Panel ist nur lokal (127.0.0.1) erreichbar.

    Ersetzt HTTPBasicAuth: alle Decorator-Aufrufe sind No-Ops, es wird
    kein Login mehr verlangt.
    """
    def login_required(self, f):
        return f

    def verify_password(self, f):
        return f

    def current_user(self):
        return ADMIN_USER


auth = _NoAuth()

ALLOWED_EXT = {".md", ".txt", ".pdf", ".docx", ".html", ".htm"}
# Im Browser editierbare Textdateien (PDF/DOCX gehen nicht sinnvoll)
EDITABLE_EXT = {".md", ".txt", ".html", ".htm"}
# Obergrenze fuer den Inhalt einer einzelnen Datei im Editor
MAX_EDIT_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_UPLOAD_MB = 50
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
LOGO_DIR = DATA_DIR / "branding"
SNIPPET_IMG_DIR = DATA_DIR / "snippet_images"
SNIPPET_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _kb_resolve(filename: str):
    """Loest einen relativen Pfad sicher innerhalb von KB_DIR auf.
    Returns Path oder None bei Traversal-Versuch / leerer Eingabe."""
    parts = [p for p in (filename or "").replace("\\", "/").split("/")
             if p and p not in (".", "..")]
    if not parts:
        return None
    target = KB_DIR.joinpath(*parts).resolve()
    try:
        target.relative_to(KB_DIR.resolve())
    except ValueError:
        return None
    return target


def current_logo_path():
    if not LOGO_DIR.exists():
        return None
    for p in LOGO_DIR.glob("logo.*"):
        if p.suffix.lower() in LOGO_EXT:
            return p
    return None


# ---------- Helpers ----------

def reload_env():
    load_dotenv(ENV_FILE, override=True)


def csrf_field() -> Markup:
    """Generiert CSRF-Token (Session) und gibt Hidden-Input zurück."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return Markup(
        f'<input type="hidden" name="_csrf_token" value="{session["_csrf_token"]}">'
    )


def check_csrf() -> bool:
    """Prüft CSRF-Token aus POST-Formulardaten."""
    token = session.get("_csrf_token", "")
    form_token = request.form.get("_csrf_token", "")
    return bool(token and form_token and secrets.compare_digest(token, form_token))


def kb_stats():
    try:
        from ingest import get_client
        _, col = get_client()
        return col.count()
    except Exception as e:
        return 0


_BOT_LOCK_FILE = DATA_DIR / "bot.lock"


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                               capture_output=True, text=True)
            return str(pid) in r.stdout
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def bot_running():
    # Prefer bot.lock (set by bot.py itself) over bot.pid (set by admin panel Popen).
    for f in (_BOT_LOCK_FILE, BOT_PID_FILE):
        if f.exists():
            try:
                candidate = int(f.read_text().strip())
                if _pid_alive(candidate):
                    return True, candidate
            except Exception:
                pass
    return False, None


def list_kb_files():
    if not KB_DIR.exists():
        return []
    out = []
    for p in sorted(KB_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() in ALLOWED_EXT:
            rel = str(p.relative_to(KB_DIR)).replace("\\", "/")
            ext = p.suffix.lower()
            out.append({
                "name": rel,
                "size": f"{p.stat().st_size / 1024:.1f} KB",
                "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "ext": ext.lstrip("."),
                "editable": ext in EDITABLE_EXT,
            })
    return out


def read_env():
    if not ENV_FILE.exists():
        return {}
    return dotenv_values(ENV_FILE)


def write_env(values: dict):
    lines = []
    if ENV_FILE.exists():
        existing = ENV_FILE.read_text(encoding="utf-8").splitlines()
        seen = set()
        for ln in existing:
            stripped = ln.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(ln)
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in values:
                    lines.append(f"{key}={values[key]}")
                    seen.add(key)
                else:
                    lines.append(ln)
        for k, v in values.items():
            if k not in seen:
                lines.append(f"{k}={v}")
    else:
        for k, v in values.items():
            lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reload_env()


# ---------- Sektor-Theme CSS ----------

CSS = """
:root {
  --bg-primary: #09090f;
  --bg-secondary: #0f0f1c;
  --bg-card: #17172a;
  --bg-card-hover: #1e1e35;
  --accent: #d42070;
  --accent-hover: #b8185c;
  --accent-light: #e8409a;
  --accent-cyan: #0fb8c9;
  --accent-purple: #7040c0;
  --discord: #5865f2;
  --twitch: #9146ff;
  --text-primary: #f0f0f8;
  --text-secondary: #8888aa;
  --text-muted: #4a4a6a;
  --border: #2a2a46;
  --success: #4ade80;
  --warn: #f59e0b;
  --danger: #ef4444;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg-primary); color: var(--text-primary);
  min-height: 100vh; font-size: 14px; line-height: 1.5;
}
a { color: var(--accent-cyan); text-decoration: none; }
a:hover { color: var(--accent-light); }
h1, h2, h3, h4 {
  font-family: 'Rajdhani', 'Inter', sans-serif;
  font-weight: 600; letter-spacing: 0.5px;
}
/* Top Bar */
.topbar {
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  padding: 1rem 2rem;
  display: flex; justify-content: space-between; align-items: center;
  box-shadow: 0 2px 10px rgba(0,0,0,0.3);
  position: sticky; top: 0; z-index: 100;
}
.topbar .brand {
  font-family: 'Rajdhani', sans-serif; font-size: 1.5rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 2px; color: var(--accent);
}
.topbar .brand .dot { color: var(--accent-cyan); }
.topbar .brand-logo { height: 42px; width: auto; display: block; object-fit: contain; }
.topbar nav { display: flex; gap: 1.5rem; }
.topbar nav a {
  color: var(--text-secondary); font-weight: 500; font-size: 0.9rem;
  text-transform: uppercase; letter-spacing: 1px; padding: 0.5rem 0;
  border-bottom: 2px solid transparent; transition: all 0.15s;
}
.topbar nav a:hover, .topbar nav a.active {
  color: var(--accent); border-bottom-color: var(--accent);
}
/* Container */
.container { max-width: 1300px; margin: 2rem auto; padding: 0 2rem; }
h1.page-title {
  font-size: 1.8rem; margin-bottom: 1.5rem; text-transform: uppercase;
  letter-spacing: 2px;
}
h1.page-title::before {
  content: ""; display: inline-block; width: 4px; height: 24px;
  background: var(--accent); margin-right: 12px; vertical-align: middle;
}
/* Card */
.card {
  background: var(--bg-card); border-radius: 8px; padding: 1.5rem;
  margin-bottom: 1.5rem; border: 1px solid var(--border);
  transition: border-color 0.15s;
}
.card:hover { border-color: var(--accent-purple); }
.card h2 {
  color: var(--accent); font-size: 1.1rem; margin-bottom: 1rem;
  text-transform: uppercase; letter-spacing: 1.5px;
  padding-bottom: 0.5rem; border-bottom: 1px solid var(--border);
}
/* Grid Stats */
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
.stat {
  background: var(--bg-secondary); padding: 1.25rem; border-radius: 6px;
  text-align: center; border-left: 3px solid var(--accent);
}
.stat .val {
  font-family: 'Rajdhani', sans-serif;
  font-size: 2rem; font-weight: 700; color: var(--accent);
  line-height: 1;
}
.stat .lbl {
  font-size: 0.75rem; color: var(--text-secondary);
  text-transform: uppercase; letter-spacing: 1px; margin-top: 0.5rem;
}
.stat.success { border-left-color: var(--success); }
.stat.success .val { color: var(--success); }
.stat.danger { border-left-color: var(--danger); }
.stat.danger .val { color: var(--danger); }
.stat.cyan { border-left-color: var(--accent-cyan); }
.stat.cyan .val { color: var(--accent-cyan); }
/* Table */
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
th, td {
  padding: 0.7rem 0.8rem; text-align: left;
  border-bottom: 1px solid var(--border);
}
th {
  background: var(--bg-secondary); color: var(--accent-cyan);
  text-transform: uppercase; font-size: 0.75rem; letter-spacing: 1px;
  font-weight: 600;
}
tr:hover td { background: var(--bg-card-hover); }
.badge {
  display: inline-block; padding: 0.15rem 0.5rem; border-radius: 3px;
  font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.5px; background: var(--bg-secondary);
  color: var(--accent-cyan); border: 1px solid var(--border);
}
/* Buttons */
.btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.55rem 1.1rem; border-radius: 4px; border: none;
  background: var(--accent); color: white; cursor: pointer;
  text-decoration: none; font-size: 0.85rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px;
  transition: all 0.15s; font-family: inherit;
}
.btn:hover { background: var(--accent-hover); color: white; }
.btn-secondary { background: var(--bg-secondary); border: 1px solid var(--border); color: var(--text-primary); }
.btn-secondary:hover { border-color: var(--accent-cyan); color: var(--accent-cyan); background: var(--bg-card-hover); }
.btn-cyan { background: var(--accent-cyan); }
.btn-cyan:hover { background: var(--accent-cyan-hover, #0a9aaa); }
.btn-danger { background: var(--danger); }
.btn-danger:hover { background: #b91c1c; }
.btn-success { background: var(--success); color: var(--bg-primary); }
.btn-success:hover { background: #22c55e; color: var(--bg-primary); }
.btn-warn { background: var(--warn); color: var(--bg-primary); }
.btn-warn:hover { background: #d97706; }
.btn-discord { background: var(--discord); }
.btn-discord:hover { background: #4752c4; }
.btn[disabled] { opacity: 0.4; cursor: not-allowed; }
.btn-row { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1rem; }
/* Forms */
input[type=text], input[type=number], input[type=password], input[type=file],
textarea, select {
  width: 100%; padding: 0.6rem 0.8rem;
  background: var(--bg-secondary); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 4px;
  font-family: inherit; font-size: 0.9rem;
  transition: border-color 0.15s;
}
input:focus, textarea:focus, select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(212,32,112,0.15);
}
textarea { min-height: 100px; resize: vertical; font-family: inherit; }
.form-row { margin-bottom: 1rem; }
.form-row label {
  display: block; font-size: 0.8rem; color: var(--text-secondary);
  margin-bottom: 0.35rem; text-transform: uppercase; letter-spacing: 0.5px;
  font-weight: 500;
}
.form-row .hint { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.3rem; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 800px) { .two-col { grid-template-columns: 1fr; } }
/* Flash */
.flash {
  padding: 0.8rem 1rem; margin-bottom: 1rem; border-radius: 4px;
  background: rgba(74,222,128,0.1); border: 1px solid rgba(74,222,128,0.3);
  color: var(--success);
}
.flash.err { background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.3); color: var(--danger); }
/* Pre / Logs */
pre.log {
  background: #020207; padding: 1rem; border-radius: 4px;
  color: #cbd5e1; font-size: 0.75rem;
  max-height: 560px; overflow-y: auto; white-space: pre-wrap;
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  border: 1px solid var(--border);
}
/* Status */
.status-on { color: var(--success); font-weight: 600; }
.status-off { color: var(--danger); font-weight: 600; }
.small { font-size: 0.8rem; color: var(--text-secondary); }
.muted { color: var(--text-muted); }
hr { border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }
"""

LAYOUT = """<!DOCTYPE html>
<html lang=de><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>TICKET-TOOL // {{ title }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet">
<style>{{ css|safe }}</style>
</head><body>
<header class=topbar>
  <div class=brand>
    {% if logo_url %}<img src="{{ logo_url }}" alt="Logo" class=brand-logo>{% else %}TICKET<span class=dot>•</span>TOOL{% endif %}
  </div>
  <nav>
    <a href="{{ url_for('dashboard') }}" class="{{ 'active' if active=='dash' else '' }}">Dashboard</a>
    <a href="{{ url_for('kb_page') }}" class="{{ 'active' if active=='kb' else '' }}">Wissensbasis</a>
    <a href="{{ url_for('snippets_page') }}" class="{{ 'active' if active=='snip' else '' }}">Snippets</a>
    <a href="{{ url_for('messages_page') }}" class="{{ 'active' if active=='msg' else '' }}">Bot-Texte</a>
    <a href="{{ url_for('categories_page') }}" class="{{ 'active' if active=='cats' else '' }}">Kategorien</a>
    <a href="{{ url_for('team_areas_page') }}" class="{{ 'active' if active=='team_areas' else '' }}">Team-Bereiche</a>
    <a href="{{ url_for('discord_page') }}" class="{{ 'active' if active=='discord' else '' }}">Discord</a>
    <a href="{{ url_for('settings_page') }}" class="{{ 'active' if active=='settings' else '' }}">Settings</a>
    <a href="{{ url_for('logs_page') }}" class="{{ 'active' if active=='logs' else '' }}">Logs</a>
    <a href="{{ url_for('bot_page') }}" class="{{ 'active' if active=='bot' else '' }}">Bot-Control</a>
  </nav>
</header>
<main class=container>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="flash {{ 'err' if cat=='err' else '' }}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}
  {{ content|safe }}
</main>
</body></html>"""


DISCORD_EDITOR_CSS = """
.md-editor-wrap { border:1px solid var(--border); border-radius:6px; overflow:hidden; }
.md-toolbar {
  display:flex; flex-wrap:wrap; gap:2px; padding:6px 8px;
  background:var(--bg-secondary); border-bottom:1px solid var(--border);
}
.md-btn {
  background:var(--bg-card); border:1px solid var(--border); color:var(--text-primary);
  border-radius:3px; padding:3px 8px; cursor:pointer; font-size:13px;
  font-family:inherit; line-height:1.4; transition:all 0.1s;
  display:inline-flex; align-items:center; gap:3px;
}
.md-btn:hover { background:var(--bg-card-hover); border-color:var(--accent-cyan); color:var(--accent-cyan); }
.md-btn-sep { width:1px; background:var(--border); margin:2px 4px; align-self:stretch; }
.md-color-wrap { position:relative; display:inline-block; }
.md-color-palette {
  position:absolute; top:calc(100% + 4px); left:0; z-index:200;
  background:var(--bg-card); border:1px solid var(--border); border-radius:6px;
  padding:8px; display:none; grid-template-columns:repeat(8,22px);
  gap:4px; box-shadow:0 6px 24px rgba(0,0,0,0.6);
}
.md-color-palette.open { display:grid; }
.md-color-swatch {
  width:22px; height:22px; border-radius:4px; cursor:pointer;
  border:2px solid rgba(255,255,255,0.08); transition:all 0.12s;
}
.md-color-swatch:hover { transform:scale(1.25); border-color:white; }
.md-tabs { display:flex; border-bottom:1px solid var(--border); background:var(--bg-secondary); }
.md-tab {
  padding:6px 16px; font-size:0.8rem; text-transform:uppercase; letter-spacing:1px;
  cursor:pointer; border-bottom:2px solid transparent; color:var(--text-secondary);
  font-weight:500; transition:all 0.1s;
}
.md-tab.active { color:var(--accent); border-bottom-color:var(--accent); }
.md-tab-content { display:none; }
.md-tab-content.active { display:block; }
.md-textarea {
  width:100%; padding:10px 12px; background:var(--bg-secondary); color:var(--text-primary);
  border:none; font-family:'Cascadia Mono','Consolas',monospace; font-size:13px;
  line-height:1.6; resize:vertical; min-height:160px; outline:none;
}
.md-preview {
  padding:12px 14px; background:var(--bg-secondary); min-height:160px;
  font-size:14px; line-height:1.6; color:var(--text-primary);
}
.md-preview h1 { font-size:1.9em; font-weight:800; margin:6px 0 4px; line-height:1.2; }
.md-preview h2 { font-size:1.45em; font-weight:700; margin:5px 0 3px; line-height:1.2; }
.md-preview h3 { font-size:1.15em; font-weight:700; margin:4px 0 2px; }
.md-preview strong { color:#fff; font-weight:700; }
.md-preview em { font-style:italic; color:#ddd; }
.md-preview u { text-decoration:underline; }
.md-preview s { text-decoration:line-through; opacity:0.7; }
.md-preview code {
  background:rgba(255,255,255,0.08); padding:1px 5px; border-radius:3px;
  font-family:'Cascadia Mono','Consolas',monospace; font-size:0.85em; color:#c9d1d9;
}
.md-preview pre {
  background:rgba(0,0,0,0.4); border:1px solid var(--border); border-radius:4px;
  padding:10px 12px; margin:8px 0; overflow-x:auto;
  font-family:'Cascadia Mono','Consolas',monospace; font-size:0.85em;
}
.md-preview pre code { background:none; padding:0; }
.md-preview blockquote {
  border-left:4px solid var(--accent-cyan); padding:4px 12px; margin:6px 0;
  background:rgba(15,184,201,0.07); color:#aaa;
}
.md-preview ul { margin:6px 0 6px 20px; }
.md-preview ul li { list-style:disc; margin:2px 0; }
.md-preview ol { margin:6px 0 6px 20px; }
.md-preview ol li { list-style:decimal; margin:2px 0; }
.md-preview a { color:var(--accent-cyan); }
.md-preview img { max-width:100%; max-height:280px; border-radius:6px; margin:6px 0; display:block; object-fit:contain; }
.md-img-popup {
  display:none; position:absolute; z-index:300; left:0; top:calc(100% + 4px);
  background:var(--bg-card); border:1px solid var(--border); border-radius:6px;
  padding:10px; box-shadow:0 6px 24px rgba(0,0,0,0.6); min-width:320px;
}
.md-img-popup.open { display:flex; gap:6px; }
.md-img-popup input {
  flex:1; padding:5px 8px; background:var(--bg-secondary); color:var(--text-primary);
  border:1px solid var(--border); border-radius:4px; font-size:13px; font-family:inherit;
}
.md-img-popup input:focus { outline:none; border-color:var(--accent); }
.md-img-popup button {
  padding:5px 12px; background:var(--accent); color:#fff; border:none;
  border-radius:4px; cursor:pointer; font-size:13px; font-family:inherit; font-weight:600;
}
.md-img-tabs { display:flex; gap:0; margin-bottom:6px; }
.md-img-tab {
  flex:1; padding:4px 0; text-align:center; font-size:11px; cursor:pointer;
  background:var(--bg-secondary); border:1px solid var(--border); color:var(--text-secondary);
}
.md-img-tab:first-child { border-radius:3px 0 0 3px; }
.md-img-tab:last-child  { border-radius:0 3px 3px 0; border-left:none; }
.md-img-tab.active { background:var(--accent); color:#fff; border-color:var(--accent); }
.md-upload-area {
  border:2px dashed var(--border); border-radius:4px; padding:14px 10px;
  text-align:center; cursor:pointer; transition:all 0.15s; color:var(--text-secondary);
  font-size:12px;
}
.md-upload-area:hover, .md-upload-area.drag { border-color:var(--accent); color:var(--accent); background:rgba(212,32,112,0.06); }
.md-upload-progress { display:none; font-size:11px; color:var(--accent-cyan); margin-top:4px; }
.md-btn.active-align { background:var(--accent); color:#fff; border-color:var(--accent); }
.md-preview.align-center { text-align:center; }
.md-preview.align-right  { text-align:right; }
"""

DISCORD_EDITOR_JS = """
function setupDiscordEditor(wrap, ta) {
  var ESC = '\\u001b';
  var ANSI_COLORS = [
    {n:'Dunkelblau',  c:'34', h:'#4a6fa5'},
    {n:'Dunkelgruen', c:'32', h:'#27ae60'},
    {n:'Dunkelcyan',  c:'36', h:'#16a085'},
    {n:'Dunkelrot',   c:'31', h:'#c0392b'},
    {n:'Dunkelgrau',  c:'30', h:'#555'},
    {n:'Grau',        c:'90', h:'#888'},
    {n:'Hellblau',    c:'94', h:'#74b9ff'},
    {n:'Hellgruen',   c:'92', h:'#55efc4'},
    {n:'Cyan',        c:'96', h:'#81ecec'},
    {n:'Rot',         c:'91', h:'#ff7675'},
    {n:'Magenta',     c:'95', h:'#fd79a8'},
    {n:'Gelb',        c:'93', h:'#fdcb6e'},
    {n:'Orange',      c:'33', h:'#e17055'},
    {n:'Hellmagenta', c:'35', h:'#a29bfe'},
    {n:'Weiss',       c:'97', h:'#dfe6e9'},
    {n:'Hellgrau',    c:'37', h:'#b2bec3'},
  ];
  var ANSI_MAP = {};
  ANSI_COLORS.forEach(function(c){ ANSI_MAP[c.c] = c.h; });

  function wrapSel(before, after, placeholder) {
    var s = ta.selectionStart, e = ta.selectionEnd;
    var sel = ta.value.substring(s, e) || placeholder;
    ta.value = ta.value.substring(0, s) + before + sel + after + ta.value.substring(e);
    ta.selectionStart = s + before.length;
    ta.selectionEnd   = s + before.length + sel.length;
    ta.focus(); renderPreview();
  }
  function insertLine(prefix) {
    var s = ta.selectionStart;
    var lineStart = ta.value.lastIndexOf('\\n', s - 1) + 1;
    ta.value = ta.value.substring(0, lineStart) + prefix + ta.value.substring(lineStart);
    ta.selectionStart = ta.selectionEnd = s + prefix.length;
    ta.focus(); renderPreview();
  }

  wrap.querySelector('[data-md=bold]').onclick    = function(){ wrapSel('**','**','fetter Text'); };
  wrap.querySelector('[data-md=italic]').onclick  = function(){ wrapSel('*','*','kursiver Text'); };
  wrap.querySelector('[data-md=under]').onclick   = function(){ wrapSel('__','__','unterstrichener Text'); };
  wrap.querySelector('[data-md=strike]').onclick  = function(){ wrapSel('~~','~~','durchgestrichener Text'); };
  wrap.querySelector('[data-md=code]').onclick    = function(){ wrapSel('`','`','code'); };
  wrap.querySelector('[data-md=codeblock]').onclick = function(){
    var s = ta.selectionStart, e = ta.selectionEnd;
    var sel = ta.value.substring(s, e) || 'code block';
    ta.value = ta.value.substring(0, s) + '```\\n' + sel + '\\n```' + ta.value.substring(e);
    ta.focus(); renderPreview();
  };
  wrap.querySelector('[data-md=quote]').onclick = function(){ insertLine('> '); };
  wrap.querySelector('[data-md=ul]').onclick    = function(){ insertLine('- '); };
  wrap.querySelector('[data-md=ol]').onclick    = function(){
    var s = ta.selectionStart;
    var lineStart = ta.value.lastIndexOf('\\n', s - 1) + 1;
    var prevLine  = ta.value.substring(ta.value.lastIndexOf('\\n', lineStart - 2) + 1, lineStart);
    var m = prevLine.match(/^(\\d+)\\. /);
    var prefix = (m ? parseInt(m[1]) + 1 : 1) + '. ';
    ta.value = ta.value.substring(0, lineStart) + prefix + ta.value.substring(lineStart);
    ta.selectionStart = ta.selectionEnd = s + prefix.length;
    ta.focus(); renderPreview();
  };
  // Headings
  wrap.querySelector('[data-md=h1]').onclick = function(){ insertLine('# '); };
  wrap.querySelector('[data-md=h2]').onclick = function(){ insertLine('## '); };
  wrap.querySelector('[data-md=h3]').onclick = function(){ insertLine('### '); };

  // Color palette
  var palette = wrap.querySelector('.md-color-palette');
  ANSI_COLORS.forEach(function(col) {
    var sw = document.createElement('div');
    sw.className = 'md-color-swatch'; sw.title = col.n;
    sw.style.background = col.h;
    sw.onclick = function(e) {
      e.stopPropagation();
      var s = ta.selectionStart, e2 = ta.selectionEnd;
      var sel = ta.value.substring(s, e2) || 'farbiger Text';
      var colored = '```ansi\\n' + ESC + '[' + col.c + 'm' + sel + ESC + '[0m\\n```';
      ta.value = ta.value.substring(0, s) + colored + ta.value.substring(e2);
      ta.focus(); renderPreview(); palette.classList.remove('open');
    };
    palette.appendChild(sw);
  });
  wrap.querySelector('[data-md=color]').onclick = function(e) {
    e.stopPropagation();
    palette.classList.toggle('open');
    imgPopup.classList.remove('open');
  };

  // Image popup (upload + URL)
  var imgPopup  = wrap.querySelector('.md-img-popup');
  var fileInput = wrap.querySelector('.md-file-input');
  var progress  = wrap.querySelector('.md-upload-progress');

  function insertImageMarker(token) {
    var s = ta.selectionStart;
    var before = ta.value.substring(0, s), after = ta.value.substring(s);
    var insert = (before === '' || before.endsWith('\\n') ? '' : '\\n') + token + '\\n';
    ta.value = before + insert + after;
    ta.selectionStart = ta.selectionEnd = s + insert.length;
    ta.focus(); renderPreview(); imgPopup.classList.remove('open');
  }

  // Tab switching inside popup
  imgPopup.querySelectorAll('.md-img-tab').forEach(function(t) {
    t.onclick = function(e) {
      e.stopPropagation();
      imgPopup.querySelectorAll('.md-img-tab').forEach(function(x){ x.classList.remove('active'); });
      imgPopup.querySelectorAll('.md-img-pane').forEach(function(x){ x.style.display='none'; });
      t.classList.add('active');
      imgPopup.querySelector('.md-img-pane[data-pane="'+t.dataset.tab+'"]').style.display='block';
    };
  });

  // URL tab
  var urlInput = imgPopup.querySelector('.md-url-input');
  imgPopup.querySelector('.md-url-btn').onclick = function(e) {
    e.stopPropagation();
    var u = urlInput.value.trim();
    if (u) insertImageMarker(u);
  };
  urlInput.onkeydown = function(e) {
    if (e.key==='Enter'){ imgPopup.querySelector('.md-url-btn').click(); }
    if (e.key==='Escape'){ imgPopup.classList.remove('open'); ta.focus(); }
  };

  // Upload tab - drag & drop area
  var uploadArea = imgPopup.querySelector('.md-upload-area');
  uploadArea.onclick = function(e){ e.stopPropagation(); fileInput.click(); };
  uploadArea.ondragover = function(e){ e.preventDefault(); uploadArea.classList.add('drag'); };
  uploadArea.ondragleave = function(){ uploadArea.classList.remove('drag'); };
  uploadArea.ondrop = function(e){
    e.preventDefault(); uploadArea.classList.remove('drag');
    var f = e.dataTransfer.files[0];
    if (f) doUpload(f);
  };
  fileInput.onchange = function(){ if (this.files[0]) doUpload(this.files[0]); this.value=''; };

  function doUpload(file) {
    progress.style.display = 'block'; progress.textContent = 'Wird hochgeladen...';
    var fd = new FormData(); fd.append('image', file);
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/snippet-image/upload');
    xhr.onload = function() {
      progress.style.display = 'none';
      if (xhr.status === 200) {
        var d = JSON.parse(xhr.responseText);
        insertImageMarker('[[img:' + d.filename + ']]');
      } else {
        try { progress.textContent = JSON.parse(xhr.responseText).error; }
        catch(e){ progress.textContent = 'Upload-Fehler'; }
        progress.style.display = 'block';
      }
    };
    xhr.onerror = function(){ progress.style.display='none'; alert('Upload-Fehler'); };
    xhr.send(fd);
  }

  wrap.querySelector('[data-md=image]').onclick = function(e) {
    e.stopPropagation();
    imgPopup.classList.toggle('open');
    palette.classList.remove('open');
    if (imgPopup.classList.contains('open')) { urlInput.value=''; }
  };
  imgPopup.onclick = function(e){ e.stopPropagation(); };

  // Alignment buttons
  var preview = wrap.querySelector('.md-preview');
  ['left','center','right'].forEach(function(dir) {
    var btn = wrap.querySelector('[data-md=align-'+dir+']');
    if (!btn) return;
    btn.onclick = function() {
      ['left','center','right'].forEach(function(d){
        wrap.querySelector('[data-md=align-'+d+']').classList.remove('active-align');
        preview.classList.remove('align-'+d);
      });
      if (dir !== 'left') {
        btn.classList.add('active-align');
        preview.classList.add('align-'+dir);
      }
    };
  });

  document.addEventListener('click', function(){
    palette.classList.remove('open');
    imgPopup.classList.remove('open');
  });

  // Tabs
  var tabs  = wrap.querySelectorAll('.md-tab');
  var panes = wrap.querySelectorAll('.md-tab-content');
  tabs.forEach(function(t) {
    t.onclick = function() {
      tabs.forEach(function(x){ x.classList.remove('active'); });
      panes.forEach(function(x){ x.classList.remove('active'); });
      t.classList.add('active');
      wrap.querySelector('.md-tab-content[data-pane="'+t.dataset.tab+'"]').classList.add('active');
      if (t.dataset.tab === 'preview') renderPreview();
    };
  });
  ta.oninput = renderPreview;

  function renderPreview() {
    var raw = ta.value;
    // ANSI-colored code blocks (```ansi ... ```)
    var html = raw.replace(/```ansi\\n([\\s\\S]*?)```/g, function(_, body) {
      var rendered = body.replace(new RegExp(ESC + '\\\\[(\\\\d+)m', 'g'), function(_, code) {
        if (code === '0') return '</span>';
        return '<span style="color:' + (ANSI_MAP[code] || '#fff') + '">';
      }).replace(/\\n/g, '<br>');
      return '<pre style="background:rgba(0,0,0,0.5);padding:8px 12px;border-radius:4px;font-size:0.85em">' + rendered + '</pre>';
    });
    // plain code blocks
    html = html.replace(/```([\\s\\S]*?)```/g, function(_,c){ return '<pre><code>'+esc(c.trim())+'</code></pre>'; });
    // inline code
    html = html.replace(/`([^`]+)`/g, function(_,c){ return '<code>'+esc(c)+'</code>'; });
    // headings (must be at line start — check on raw lines via split)
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm,  '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm,   '<h1>$1</h1>');
    // bold+italic
    html = html.replace(/\\*\\*\\*(.+?)\\*\\*\\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<u>$1</u>');
    html = html.replace(/\\*(.+?)\\*/g, '<em>$1</em>');
    html = html.replace(/_([^_\\n]+)_/g, '<em>$1</em>');
    html = html.replace(/~~(.+?)~~/g, '<s>$1</s>');
    // blockquote
    html = html.replace(/^&gt; ?(.*)$/gm, '<blockquote>$1</blockquote>');
    html = html.replace(/^> ?(.*)$/gm, '<blockquote>$1</blockquote>');
    // [[img:filename]] uploaded images
    html = html.replace(/\[\[img:([^\]]+)\]\]/g, function(_, fname){
      return '<img src="/snippet-image/'+fname+'" style="max-width:100%;max-height:280px;border-radius:6px;margin:6px 0;display:block">';
    });
    // bare image URLs (Discord auto-embeds these)
    html = html.replace(/(^|<br>)(https?:\/\/\S+\.(?:png|jpg|jpeg|gif|webp|svg)(?:\?\S*)?)/gim,
      function(_, pre, url){
        return pre + '<img src="'+url+'" style="max-width:100%;max-height:280px;border-radius:6px;margin:6px 0;display:block">';
      });
    // links
    html = html.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2" target=_blank>$1</a>');
    // bullet list
    var inUl = false;
    html = html.split('\\n').map(function(line){
      var m = line.match(/^- (.+)/);
      if (m) { var r = (inUl?'':'<ul>') + '<li>'+m[1]+'</li>'; inUl=true; return r; }
      if (inUl){ inUl=false; return '</ul>'+line; } return line;
    }).join('\\n'); if (inUl) html += '</ul>';
    // numbered list
    var inOl = false;
    html = html.split('\\n').map(function(line){
      var m = line.match(/^\\d+\\. (.+)/);
      if (m) { var r = (inOl?'':'<ol>') + '<li>'+m[1]+'</li>'; inOl=true; return r; }
      if (inOl){ inOl=false; return '</ol>'+line; } return line;
    }).join('\\n'); if (inOl) html += '</ol>';
    // newlines
    html = html.replace(/\\n/g, '<br>');
    html = html.replace(/<pre([^>]*)>(.*?)<\\/pre>/gs, function(_,a,c){
      return '<pre'+a+'>'+c.replace(/<br>/g,'\\n')+'</pre>';
    });
    wrap.querySelector('.md-preview').innerHTML = html;
  }
  function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  renderPreview();
}
"""


def md_editor(field_name: str, value: str = "", required: bool = True) -> str:
    """Gibt den HTML-String fuer den Discord-Markdown-Editor zurueck."""
    req = "required" if required else ""
    safe_val = html.escape(value)
    uid = field_name.replace("[", "_").replace("]", "_")
    return f"""
<div class="md-editor-wrap" id="wrap_{uid}">
  <div class=md-tabs>
    <div class="md-tab active" data-tab="edit">✏️ Bearbeiten</div>
    <div class="md-tab" data-tab="preview">👁 Vorschau</div>
  </div>
  <div class="md-tab-content active" data-pane="edit">
    <div class=md-toolbar>
      <button type=button class=md-btn data-md=bold><b>B</b></button>
      <button type=button class=md-btn data-md=italic><i>I</i></button>
      <button type=button class=md-btn data-md=under><u>U</u></button>
      <button type=button class=md-btn data-md=strike><s>S</s></button>
      <div class=md-btn-sep></div>
      <button type=button class=md-btn data-md=code>&#96;code&#96;</button>
      <button type=button class=md-btn data-md=codeblock>&#96;&#96;&#96;block&#96;&#96;&#96;</button>
      <div class=md-btn-sep></div>
      <button type=button class=md-btn data-md=quote>❝ Zitat</button>
      <button type=button class=md-btn data-md=ul>• Liste</button>
      <button type=button class=md-btn data-md=ol>1. Liste</button>
      <div class=md-btn-sep></div>
      <button type=button class=md-btn data-md=h1 style="font-weight:800;font-size:15px">H1</button>
      <button type=button class=md-btn data-md=h2 style="font-weight:700">H2</button>
      <button type=button class=md-btn data-md=h3>H3</button>
      <div class=md-btn-sep></div>
      <div class=md-color-wrap>
        <button type=button class="md-btn" data-md=color>🎨 Farbe</button>
        <div class=md-color-palette></div>
      </div>
      <div class=md-color-wrap>
        <button type=button class="md-btn" data-md=image>🖼 Bild</button>
        <div class=md-img-popup>
          <div class=md-img-tabs>
            <div class="md-img-tab active" data-tab="upload">⬆ Upload</div>
            <div class="md-img-tab" data-tab="url">🔗 URL</div>
          </div>
          <div class="md-img-pane" data-pane="upload" style="display:block">
            <div class=md-upload-area>Klicken oder Bild hierher ziehen<br><span style="font-size:10px;opacity:.6">PNG, JPG, GIF, WEBP</span></div>
            <div class=md-upload-progress></div>
          </div>
          <div class="md-img-pane" data-pane="url" style="display:none">
            <div style="display:flex;gap:6px;margin-top:2px">
              <input type=text class=md-url-input placeholder="https://i.imgur.com/beispiel.png">
              <button type=button class=md-url-btn>OK</button>
            </div>
          </div>
        </div>
      </div>
      <input type=file class=md-file-input accept="image/*" style="display:none">
      <div class=md-btn-sep></div>
      <button type=button class="md-btn" data-md=align-left title="Linksbündig">⇤</button>
      <button type=button class="md-btn" data-md=align-center title="Zentriert">⇔</button>
      <button type=button class="md-btn" data-md=align-right title="Rechtsbündig">⇥</button>
    </div>
    <textarea class=md-textarea name="{field_name}" id="ta_{uid}" {req}>{safe_val}</textarea>
  </div>
  <div class="md-tab-content" data-pane="preview">
    <div class=md-preview></div>
  </div>
</div>
<script>
(function(){{
  var wrap = document.getElementById('wrap_{uid}');
  var ta   = document.getElementById('ta_{uid}');
  {DISCORD_EDITOR_JS}
  setupDiscordEditor(wrap, ta);
}})();
</script>
"""


def render(title, content, active=""):
    logo = current_logo_path()
    logo_url = url_for("serve_logo", _external=False, v=int(logo.stat().st_mtime)) if logo else None
    combined_css = CSS + DISCORD_EDITOR_CSS
    return render_template_string(LAYOUT, title=title, css=combined_css, content=content, active=active, logo_url=logo_url)


@app.route("/branding/logo")
def serve_logo():
    logo = current_logo_path()
    if not logo:
        return ("", 404)
    return send_from_directory(str(logo.parent), logo.name)


@app.route("/snippet-image/<path:filename>")
def snippet_image_serve(filename):
    safe = Path(filename).name
    p = SNIPPET_IMG_DIR / safe
    if not p.exists() or p.suffix.lower() not in SNIPPET_IMG_EXT:
        abort(404)
    return send_from_directory(str(SNIPPET_IMG_DIR), safe)


@app.route("/snippet-image/upload", methods=["POST"])
@auth.login_required
def snippet_image_upload():
    import uuid as _uuid
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify({"error": "no file"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in SNIPPET_IMG_EXT:
        return jsonify({"error": f"Format {ext} nicht erlaubt"}), 400
    SNIPPET_IMG_DIR.mkdir(parents=True, exist_ok=True)
    fname = _uuid.uuid4().hex[:16] + ext
    f.save(str(SNIPPET_IMG_DIR / fname))
    return jsonify({"url": f"/snippet-image/{fname}", "filename": fname})


@app.route("/branding/upload", methods=["POST"])
@auth.login_required
def logo_upload():
    f = request.files.get("logo")
    if not f or not f.filename:
        flash("Keine Datei ausgewaehlt.", "err")
        return redirect(url_for("settings_page"))
    ext = Path(f.filename).suffix.lower()
    if ext not in LOGO_EXT:
        flash(f"Format {ext} nicht erlaubt. Erlaubt: {', '.join(sorted(LOGO_EXT))}", "err")
        return redirect(url_for("settings_page"))
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    for old in LOGO_DIR.glob("logo.*"):
        try:
            old.unlink()
        except Exception:
            pass
    f.save(str(LOGO_DIR / f"logo{ext}"))
    flash("Logo hochgeladen.")
    return redirect(url_for("settings_page"))


@app.route("/branding/delete", methods=["POST"])
@auth.login_required
def logo_delete():
    logo = current_logo_path()
    if logo:
        logo.unlink()
        flash("Logo entfernt.")
    return redirect(url_for("settings_page"))


# ---------- Routes ----------

@app.route("/")
@auth.login_required
def dashboard():
    running, pid = bot_running()
    n_chunks = kb_stats()
    n_files = len(list_kb_files())
    try:
        import snippets as snp
        all_snips = snp.list_all()
        n_snips = len(all_snips)
        total_hits = sum(s.get("hits", 0) for s in all_snips)
    except Exception:
        n_snips = total_hits = 0
    log_file = LOG_DIR / "bot.log"
    log_size = f"{log_file.stat().st_size / 1024:.1f} KB" if log_file.exists() else "-"

    env = read_env()
    token_set = bool(env.get("DISCORD_TOKEN") and env["DISCORD_TOKEN"] != "your_discord_bot_token_here")
    apikey_set = bool(env.get("ANTHROPIC_API_KEY") and env["ANTHROPIC_API_KEY"].startswith("sk-ant-"))
    guild_set = bool(env.get("DISCORD_GUILD_ID") and env["DISCORD_GUILD_ID"] != "123456789012345678")
    ticket_count = _get_ticket_count()
    import features as feature_flags
    flags = feature_flags.get()
    snip_on       = flags.get("snippets_enabled", True)
    rag_on        = flags.get("rag_enabled", True)
    open_btn_on   = flags.get("ticket_open_enabled", True)
    ask_btn_on    = flags.get("ask_btn_enabled", True)

    def _toggle_btn(key, label, enabled):
        btn_cls = "btn-success" if enabled else "btn-danger"
        icon    = "✅" if enabled else "⛔"
        state   = "AN" if enabled else "AUS"
        return f"""
        <form method=post action="{url_for('features_toggle')}" style="display:inline-block;margin:.25rem">
          {csrf_field()}
          <input type=hidden name="key" value="{key}">
          <button class="btn {btn_cls}" type=submit
            style="min-width:190px;display:flex;align-items:center;gap:.5rem;justify-content:space-between">
            <span>{icon} {label}</span>
            <span style="font-size:.75rem;opacity:.8">{state}</span>
          </button>
        </form>"""

    content = f"""
    <h1 class=page-title>Dashboard</h1>
    <div class=card><h2>System-Status</h2>
      <div class=grid>
        <div class="stat {'success' if running else 'danger'}">
          <div class=val>{'● ONLINE' if running else '○ OFFLINE'}</div>
          <div class=lbl>Bot{' // PID '+str(pid) if pid else ''}</div>
        </div>
        <div class="stat cyan"><div class=val>{n_chunks}</div><div class=lbl>KB-Chunks</div></div>
        <div class="stat cyan"><div class=val>{n_files}</div><div class=lbl>Dokumente</div></div>
        <div class=stat><div class=val>{n_snips}</div><div class=lbl>Snippets</div></div>
        <div class=stat><div class=val>{total_hits}</div><div class=lbl>Snippet-Hits</div></div>
        <div class=stat><div class=val>{log_size}</div><div class=lbl>Log-Size</div></div>
        <div class="stat warn">
          <div class=val>#{ticket_count:04d}</div>
          <div class=lbl>Letztes Ticket
            <form method=post action="{url_for('ticket_counter_reset')}" style="display:inline;margin-left:6px">
              {csrf_field()}
              <button type=submit class="btn btn-danger" style="padding:2px 8px;font-size:.75rem"
                onclick="return confirm('Zähler auf 0 zurücksetzen?')">↺ Reset</button>
            </form>
          </div>
        </div>
      </div>
    </div>

    <div class=card><h2>Setup-Checkliste</h2>
      <table>
        <tr><th>Schritt</th><th>Status</th><th>Aktion</th></tr>
        <tr><td>Discord-Bot-Token</td>
            <td>{'<span class=status-on>✓ gesetzt</span>' if token_set else '<span class=status-off>✗ fehlt</span>'}</td>
            <td><a class="btn btn-secondary" href="{url_for('discord_page')}">Konfigurieren</a></td></tr>
        <tr><td>Anthropic-API-Key</td>
            <td>{'<span class=status-on>✓ gesetzt</span>' if apikey_set else '<span class=status-off>✗ fehlt</span>'}</td>
            <td><a class="btn btn-secondary" href="{url_for('settings_page')}">Konfigurieren</a></td></tr>
        <tr><td>Discord-Guild-ID</td>
            <td>{'<span class=status-on>✓ gesetzt</span>' if guild_set else '<span class=status-off>✗ fehlt</span>'}</td>
            <td><a class="btn btn-secondary" href="{url_for('discord_page')}">Konfigurieren</a></td></tr>
        <tr><td>Wissensbasis</td>
            <td>{'<span class=status-on>✓ '+str(n_chunks)+' Chunks</span>' if n_chunks else '<span class=status-off>✗ leer</span>'}</td>
            <td><a class="btn btn-secondary" href="{url_for('kb_page')}">Dokumente</a></td></tr>
      </table>
    </div>

    <div class=card><h2>Schnellaktionen</h2>
      <div class=btn-row>
        <a class="btn btn-discord" href="{url_for('discord_page')}">🎮 Discord konfigurieren</a>
        <a class="btn btn-cyan" href="{url_for('kb_page')}">📚 Dokument hochladen</a>
        <a class="btn" href="{url_for('snippets_page')}">💬 Snippet erstellen</a>
        <form method=post action="{url_for('reindex_action')}" style="display:inline">
          <button class="btn btn-warn" type=submit onclick="return confirm('Reindex starten?')">♻️ Reindex</button>
        </form>
        <a class="btn btn-secondary" href="{url_for('bot_page')}">⚙ Bot-Control</a>
      </div>
    </div>

    <div class=card>
      <h2>🔧 Antwort-Module</h2>
      <p class=small style="margin-bottom:.75rem">
        Snippets und Wissensbasis lassen sich unabhängig voneinander deaktivieren.<br>
        <span style="color:var(--text-secondary)">Wenn beide AUS: Bot antwortet nicht mehr automatisch.</span>
      </p>
      <div style="display:flex;flex-wrap:wrap;gap:.5rem">
        {_toggle_btn("ask_btn_enabled", "Button &bdquo;Direkte Antwort&ldquo;", ask_btn_on)}
        {_toggle_btn("ticket_open_enabled", "Button &bdquo;Ticket eröffnen&ldquo;", open_btn_on)}
        {_toggle_btn("snippets_enabled", "Snippets (Q&amp;A-Shortcuts)", snip_on)}
        {_toggle_btn("rag_enabled", "Wissensbasis (RAG + KI)", rag_on)}
      </div>
    </div>
    """
    return render("Dashboard", content, "dash")


# ---------- Ticket-Zähler Reset ----------

@app.route("/ticket/counter/reset", methods=["POST"])
@auth.login_required
def ticket_counter_reset():
    if not check_csrf():
        abort(403)
    _set_ticket_count(0)
    flash("Ticket-Zähler zurückgesetzt.", "success")
    return redirect(url_for("dashboard"))


# ---------- Discord-Konfig (separate Page) ----------

@app.route("/discord", methods=["GET", "POST"])
@auth.login_required
def discord_page():
    if request.method == "POST":
        env = read_env()
        for k in ["DISCORD_GUILD_ID", "MOD_ROLE_ID", "TICKET_CHANNEL_ID",
                  "TICKET_ACCESS_ROLE_ID", "TICKET_CATEGORY_ID"]:
            v = request.form.get(k, "").strip()
            env[k] = v
        for k in ["DISCORD_TOKEN"]:
            v = request.form.get(k, "").strip()
            if v:
                env[k] = v
        write_env(env)
        flash("✓ Discord-Konfiguration gespeichert. Bot-Neustart erforderlich.")
        return redirect(url_for("discord_page"))

    env = read_env()
    token_val = env.get("DISCORD_TOKEN", "")
    token_preview = (token_val[:12] + "..." + token_val[-6:]) if token_val and len(token_val) > 25 else ""
    content = f"""
    <h1 class=page-title>Discord // Authentifizierung</h1>

    <div class=card><h2>Bot-Token</h2>
      <p class=small style="margin-bottom:1rem">
        Erstelle einen Bot auf
        <a href="https://discord.com/developers/applications" target=_blank>discord.com/developers</a>
        → Bot → Reset Token → kopieren. Aktiviere <b>MESSAGE CONTENT INTENT</b>.
      </p>
      <form method=post>
        <div class=form-row>
          <label>Discord-Bot-Token</label>
          <input type=password name=DISCORD_TOKEN placeholder="{'aktuell: ' + token_preview if token_preview else 'noch nicht gesetzt'}">
          <div class=hint>Leer lassen = unveraendert. Token wird in .env gespeichert.</div>
        </div>
        <div class=two-col>
          <div class=form-row>
            <label>Server-ID (Guild)</label>
            <input type=text name=DISCORD_GUILD_ID value="{env.get('DISCORD_GUILD_ID','')}" placeholder="z.B. 1234567890">
            <div class=hint>Discord Developer-Mode → Rechtsklick auf Server → ID kopieren</div>
          </div>
          <div class=form-row>
            <label>Mod-Rollen-ID (optional)</label>
            <input type=text name=MOD_ROLE_ID value="{env.get('MOD_ROLE_ID','')}" placeholder="optional">
            <div class=hint>Fuer Mod-Ping bei unklaren Fragen</div>
          </div>
        </div>
        <div class=form-row>
          <label>Ticket-Channel-ID (optional)</label>
          <input type=text name=TICKET_CHANNEL_ID value="{env.get('TICKET_CHANNEL_ID','')}" placeholder="optional">
          <div class=hint>Wo das Ticket-Button-Panel gepostet werden soll</div>
        </div>
        <div class=two-col>
          <div class=form-row>
            <label>Ticket-Zugriff Rollen-ID (TICKET_ACCESS_ROLE_ID)</label>
            <input type=text name=TICKET_ACCESS_ROLE_ID value="{env.get('TICKET_ACCESS_ROLE_ID','')}" placeholder="optional">
            <div class=hint>Diese Rolle sieht alle Ticket-Channels (Support/Mod-Team)</div>
          </div>
          <div class=form-row>
            <label>Ticket-Kategorie-ID (TICKET_CATEGORY_ID)</label>
            <input type=text name=TICKET_CATEGORY_ID value="{env.get('TICKET_CATEGORY_ID','')}" placeholder="optional">
            <div class=hint>Kategorie, unter der Ticket-Channels erstellt werden</div>
          </div>
        </div>
        <button class="btn btn-discord" type=submit>💾 Speichern</button>
      </form>
    </div>

    <div class=card><h2>Bot-Permissions & Invite</h2>
      <p class=small>Erforderliche Bot-Berechtigungen im OAuth2-URL-Generator:</p>
      <ul class=small style="margin:0.8rem 0 0.8rem 1.5rem">
        <li><b>Scopes:</b> bot, applications.commands</li>
        <li><b>Permissions:</b> Send Messages · Embed Links · Create Private Threads · Send Messages in Threads · Manage Threads · Read Message History · Use Slash Commands</li>
        <li><b>Intents im Bot-Tab:</b> MESSAGE CONTENT INTENT (PFLICHT), SERVER MEMBERS INTENT</li>
      </ul>
      <a class="btn btn-discord" href="https://discord.com/developers/applications" target=_blank>→ Developer Portal oeffnen</a>
    </div>

    <div class=card><h2>Nach dem Speichern</h2>
      <p class=small>1. Bot-Neustart ueber <a href="{url_for('bot_page')}">Bot-Control</a><br>
      2. In Discord <code>/panel</code> eingeben (im Support-Channel)<br>
      3. Ticket-Button wird gepostet</p>
    </div>
    """
    return render("Discord", content, "discord")


# ---------- KB ----------

@app.route("/kb")
@auth.login_required
def kb_page():
    files = list_kb_files()
    def _row(f):
        edit_btn = (
            f'<a class="btn btn-secondary" style="margin-right:0.3rem" '
            f'href="{url_for("kb_edit", filename=f["name"])}">Editieren</a>'
            if f["editable"] else
            '<span class="small muted" style="margin-right:0.5rem">nicht editierbar</span>'
        )
        dl_btn = f'<a class="btn btn-secondary" style="margin-right:0.3rem" href="{url_for("kb_download", filename=f["name"])}">⬇ Download</a>'
        return (
            f"""<tr><td>{html.escape(f['name'])}</td><td><span class=badge>{f['ext']}</span></td>
        <td>{f['size']}</td><td class=muted>{f['modified']}</td>
        <td>{dl_btn}{edit_btn}<form method=post action="{url_for('kb_delete', filename=f['name'])}" style="display:inline">
        <button class="btn btn-danger" type=submit onclick="return confirm('{html.escape(f['name'], quote=True)} loeschen?')">Löschen</button></form></td></tr>"""
        )
    rows = "".join(_row(f) for f in files) or "<tr><td colspan=5 class=muted>Keine Dokumente. Upload unten.</td></tr>"

    content = f"""
    <h1 class=page-title>Wissensbasis</h1>

    <div class=card><h2>Dokumente hochladen</h2>
      <form method=post enctype=multipart/form-data action="{url_for('kb_upload')}">
        <div class=form-row>
          <label>Mehrere Dateien</label>
          <input type=file name=file multiple accept="{','.join(ALLOWED_EXT)}">
          <div class=hint>Strg/Shift-Klick fuer Mehrfachauswahl</div>
        </div>
        <div class=form-row>
          <label>Ganzer Ordner</label>
          <input type=file name=folder multiple webkitdirectory directory>
          <div class=hint>Inkl. Unterordner. Nicht erlaubte Dateitypen werden uebersprungen.</div>
        </div>
        <div class=hint>Max {MAX_UPLOAD_MB} MB pro Request · Erlaubt: {', '.join(sorted(ALLOWED_EXT))}</div>
        <button class="btn btn-success" type=submit>📤 Hochladen</button>
        <span class=small style="margin-left:1rem">Nach Upload unbedingt Reindex!</span>
      </form>
    </div>

    <div class=card><h2>Indexierte Dokumente · {len(files)}</h2>
      <div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap">
        <form method=post action="{url_for('reindex_action')}">
          <button class="btn btn-warn" type=submit onclick="return confirm('Reindex starten? Dauert je nach Menge 10-60 Sekunden.')">♻️ Reindex alle</button>
        </form>
        <a class="btn btn-secondary" href="{url_for('kb_export_zip')}">📦 Alle als ZIP exportieren</a>
      </div>
      <table><tr><th>Datei</th><th>Typ</th><th>Groesse</th><th>Geaendert</th><th></th></tr>{rows}</table>
    </div>
    """
    return render("Wissensbasis", content, "kb")


@app.route("/kb/upload", methods=["POST"])
@auth.login_required
def kb_upload():
    files = []
    files.extend(request.files.getlist("file"))
    files.extend(request.files.getlist("folder"))
    files = [f for f in files if f and f.filename]
    if not files:
        flash("Keine Dateien ausgewaehlt.", "err")
        return redirect(url_for("kb_page"))

    KB_DIR.mkdir(exist_ok=True)
    saved, skipped_ext, skipped_other = [], [], []

    for f in files:
        raw = f.filename.replace("\\", "/")
        parts = [p for p in raw.split("/") if p and p not in (".", "..")]
        if not parts:
            skipped_other.append(f.filename)
            continue
        ext = Path(parts[-1]).suffix.lower()
        if ext not in ALLOWED_EXT:
            skipped_ext.append(parts[-1])
            continue
        target = KB_DIR.joinpath(*parts).resolve()
        try:
            target.relative_to(KB_DIR.resolve())
        except ValueError:
            skipped_other.append(parts[-1])
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        f.save(str(target))
        saved.append(str(target.relative_to(KB_DIR)))

    msgs = []
    if saved:
        msgs.append(f"✓ {len(saved)} Datei(en) hochgeladen")
    if skipped_ext:
        msgs.append(f"⚠ {len(skipped_ext)} uebersprungen (Dateityp): {', '.join(skipped_ext[:5])}{'...' if len(skipped_ext) > 5 else ''}")
    if skipped_other:
        msgs.append(f"⚠ {len(skipped_other)} uebersprungen (ungueltig)")
    if saved:
        msgs.append("Reindex nicht vergessen!")
    flash(" · ".join(msgs) if msgs else "Nichts hochgeladen.", "err" if not saved else None)
    return redirect(url_for("kb_page"))


@app.route("/kb/delete/<path:filename>", methods=["POST"])
@auth.login_required
def kb_delete(filename):
    target = _kb_resolve(filename)
    if target is not None and target.exists() and target.is_file():
        rel = str(target.relative_to(KB_DIR.resolve())).replace("\\", "/")
        target.unlink()
        flash(f"✓ {rel} geloescht. Reindex empfohlen.")
    else:
        flash("Datei nicht gefunden.", "err")
    return redirect(url_for("kb_page"))


@app.route("/kb/edit/<path:filename>", methods=["GET"])
@auth.login_required
def kb_edit(filename):
    target = _kb_resolve(filename)
    if target is None or not target.exists() or not target.is_file():
        flash("Datei nicht gefunden.", "err")
        return redirect(url_for("kb_page"))
    if target.suffix.lower() not in EDITABLE_EXT:
        flash(f"Dieser Dateityp kann nicht im Browser bearbeitet werden ({target.suffix}).", "err")
        return redirect(url_for("kb_page"))
    try:
        if target.stat().st_size > MAX_EDIT_BYTES:
            flash(f"Datei zu groß für den Editor (> {MAX_EDIT_BYTES // 1024} KB).", "err")
            return redirect(url_for("kb_page"))
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        flash(f"Lesefehler: {e}", "err")
        return redirect(url_for("kb_page"))

    rel = str(target.relative_to(KB_DIR.resolve())).replace("\\", "/")
    rel_safe = html.escape(rel, quote=True)
    body = f"""
    <h1 class=page-title>Dokument editieren</h1>
    <div class=card>
      <p class=small>Datei: <code>{rel_safe}</code> &middot; Größe: {target.stat().st_size / 1024:.1f} KB
        &middot; <span class=muted>nach dem Speichern bitte Reindex auslösen</span></p>
      <form method=post action="{url_for('kb_edit', filename=rel)}">
        <div class=form-row>
          <textarea name=content style="min-height:520px;font-family:'Cascadia Mono','Consolas',monospace;font-size:13px;line-height:1.5">{html.escape(content)}</textarea>
        </div>
        <div class=btn-row>
          <button class="btn btn-success" type=submit>💾 Speichern</button>
          <a class="btn btn-secondary" href="{url_for('kb_page')}">Abbrechen</a>
          <span class=small style="margin-left:auto;color:var(--text-muted)">Max {MAX_EDIT_BYTES // 1024} KB · UTF-8</span>
        </div>
      </form>
    </div>
    """
    return render(f"Editieren: {rel}", body, "kb")


@app.route("/kb/edit/<path:filename>", methods=["POST"])
@auth.login_required
def kb_edit_save(filename):
    target = _kb_resolve(filename)
    if target is None or not target.exists() or not target.is_file():
        flash("Datei nicht gefunden.", "err")
        return redirect(url_for("kb_page"))
    if target.suffix.lower() not in EDITABLE_EXT:
        flash("Dateityp nicht editierbar.", "err")
        return redirect(url_for("kb_page"))
    content = request.form.get("content", "")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_EDIT_BYTES:
        flash(f"Inhalt zu groß (> {MAX_EDIT_BYTES // 1024} KB).", "err")
        return redirect(url_for("kb_edit", filename=filename))
    # Atomar via .tmp + os.replace, damit bei Crash mid-write nichts kaputtgeht
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        tmp.write_bytes(encoded)
        os.replace(tmp, target)
    except Exception as e:
        flash(f"Speichern fehlgeschlagen: {e}", "err")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return redirect(url_for("kb_edit", filename=filename))
    rel = str(target.relative_to(KB_DIR.resolve())).replace("\\", "/")
    flash(f"✓ {rel} gespeichert ({len(encoded) / 1024:.1f} KB). Reindex empfohlen.")
    return redirect(url_for("kb_page"))


@app.route("/kb/download/<path:filename>")
@auth.login_required
def kb_download(filename):
    target = _kb_resolve(filename)
    if target is None or not target.exists() or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name=target.name)


@app.route("/kb/export/zip")
@auth.login_required
def kb_export_zip():
    import io, zipfile
    buf = io.BytesIO()
    files = list_kb_files()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            p = _kb_resolve(f["name"])
            if p and p.exists():
                zf.write(p, f["name"])
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="wissensbasis_export.zip",
    )


@app.route("/reindex", methods=["POST"])
@auth.login_required
def reindex_action():
    py = str(ROOT / "venv" / "Scripts" / "python.exe")
    if not Path(py).exists():
        py = sys.executable
    try:
        r = subprocess.run(
            [py, str(ROOT / "src" / "ingest.py"), "--reset"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=600,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0:
            last = out.strip().splitlines()[-1] if out.strip() else ""
            flash(f"✓ Reindex fertig. {last}")
        else:
            flash(f"Reindex-Fehler (rc={r.returncode}): {out[-400:]}", "err")
    except Exception as e:
        flash(f"Reindex-Exception: {e}", "err")
    return redirect(request.referrer or url_for("dashboard"))


# ---------- Snippets ----------

@app.route("/snippets")
@auth.login_required
def snippets_page():
    import snippets as snp
    items = snp.list_all()
    threshold = os.getenv("SNIPPET_THRESHOLD", "0.78")
    rows = "".join(
        f"""<tr>
          <td><b>{s['question'][:80]}</b><br><span class=muted style="font-size:0.75rem">{s['answer'][:100]}{'...' if len(s['answer'])>100 else ''}</span></td>
          <td><span class=badge>{s.get('hits',0)} Hits</span></td>
          <td class=muted>{s.get('created_at','')[:10]}</td>
          <td>
            <a class="btn btn-secondary" href="{url_for('snippet_edit', sid=s['id'])}">Editieren</a>
            <form method=post action="{url_for('snippet_delete', sid=s['id'])}" style="display:inline">
              <button class="btn btn-danger" type=submit onclick="return confirm('Snippet loeschen?')">🗑</button>
            </form>
          </td>
        </tr>"""
        for s in items
    ) or "<tr><td colspan=4 class=muted>Noch keine Snippets. Erstelle unten einen.</td></tr>"

    content = f"""
    <h1 class=page-title>Snippets // Textbausteine</h1>

    <div class=card><h2>Wie Snippets funktionieren</h2>
      <p class=small>Snippets sind <b>vordefinierte Q&A-Paare</b>. Bei jeder Nutzer-Frage prueft der Bot
      zuerst, ob die Frage semantisch zu einem Snippet passt (Schwellwert: <b>{threshold}</b>).
      Bei Treffer wird die vorgefertigte Antwort direkt zurueckgegeben &mdash; ohne Claude-API-Call.
      Das spart Kosten und sorgt fuer konsistente Antworten bei haeufigen Fragen.</p>
    </div>

    <div class=card><h2>Neuen Snippet erstellen</h2>
      <form method=post action="{url_for('snippet_create')}">
        <div class=form-row>
          <label>Frage (Beispiel-Formulierung)</label>
          <input type=text name=question required placeholder="z.B. Wie bewerbe ich mich?">
          <div class=hint>Der Bot matcht semantisch &mdash; Umformulierungen funktionieren auch.</div>
        </div>
        <div class=form-row>
          <label>Antwort (Discord-Markdown)</label>
          {md_editor('answer')}
        </div>
        <div class=form-row>
          <label>Keywords (optional)</label>
          <input type=text name=keywords placeholder="bewerbung bewerben whitelist">
          <div class=hint>Zusaetzliche Match-Begriffe (Space-separated), erhoeht Treffergenauigkeit.</div>
        </div>
        <button class="btn btn-success" type=submit>➕ Snippet anlegen</button>
      </form>
    </div>

    <div class=card><h2>Alle Snippets · {len(items)}</h2>
      <div style="margin-bottom:.75rem">
        <a class="btn btn-secondary" href="{url_for('snippets_export_txt')}">📄 Als TXT exportieren</a>
      </div>
      <table><tr><th>Frage / Antwort-Preview</th><th>Hits</th><th>Erstellt</th><th></th></tr>{rows}</table>
    </div>
    """
    return render("Snippets", content, "snip")


@app.route("/snippets/create", methods=["POST"])
@auth.login_required
def snippet_create():
    import snippets as snp
    q = request.form.get("question", "").strip()
    a = request.form.get("answer", "").strip()
    k = request.form.get("keywords", "").strip()
    if not q or not a:
        flash("Frage und Antwort erforderlich.", "err")
        return redirect(url_for("snippets_page"))
    snp.create(q, a, k)
    flash("✓ Snippet erstellt.")
    return redirect(url_for("snippets_page"))


@app.route("/snippets/<sid>/edit", methods=["GET", "POST"])
@auth.login_required
def snippet_edit(sid):
    import snippets as snp
    s = snp.get(sid)
    if not s:
        flash("Snippet nicht gefunden.", "err")
        return redirect(url_for("snippets_page"))
    if request.method == "POST":
        q = request.form.get("question", "").strip()
        a = request.form.get("answer", "").strip()
        k = request.form.get("keywords", "").strip()
        if snp.update(sid, q, a, k):
            flash("✓ Snippet aktualisiert.")
        else:
            flash("Update fehlgeschlagen.", "err")
        return redirect(url_for("snippets_page"))
    content = f"""
    <h1 class=page-title>Snippet editieren</h1>
    <div class=card>
      <p class=small>ID: <code>{s['id']}</code> · Hits: <b>{s.get('hits',0)}</b> · Erstellt: {s.get('created_at','')}</p>
      <form method=post style="margin-top:1rem">
        <div class=form-row>
          <label>Frage</label>
          <input type=text name=question required value="{s['question'].replace('"','&quot;')}">
        </div>
        <div class=form-row>
          <label>Antwort (Discord-Markdown)</label>
          {md_editor('answer', s['answer'])}
        </div>
        <div class=form-row>
          <label>Keywords</label>
          <input type=text name=keywords value="{s.get('keywords','').replace('"','&quot;')}">
        </div>
        <div class=btn-row>
          <button class="btn btn-success" type=submit>💾 Speichern</button>
          <a class="btn btn-secondary" href="{url_for('snippets_page')}">Abbrechen</a>
        </div>
      </form>
    </div>
    """
    return render("Snippet editieren", content, "snip")


@app.route("/snippets/<sid>/delete", methods=["POST"])
@auth.login_required
def snippet_delete(sid):
    import snippets as snp
    if snp.delete(sid):
        flash("✓ Snippet geloescht.")
    else:
        flash("Snippet nicht gefunden.", "err")
    return redirect(url_for("snippets_page"))


@app.route("/snippets/export/txt")
@auth.login_required
def snippets_export_txt():
    import io, snippets as snp
    items = snp.list_all()
    lines = ["SNIPPETS EXPORT\n" + "=" * 60 + "\n"]
    for i, s in enumerate(items, 1):
        lines.append(f"[{i}] FRAGE:\n{s['question']}\n")
        lines.append(f"ANTWORT:\n{s['answer']}\n")
        if s.get("keywords"):
            lines.append(f"KEYWORDS: {s['keywords']}\n")
        lines.append("-" * 60 + "\n")
    buf = io.BytesIO("\n".join(lines).encode("utf-8"))
    return send_file(
        buf,
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name="snippets_export.txt",
    )


# ---------- Feature-Flags ----------

@app.route("/features/toggle", methods=["POST"])
@auth.login_required
def features_toggle():
    if not check_csrf():
        abort(403)
    import features as feature_flags
    key = request.form.get("key", "")
    current = feature_flags.get()
    if key not in current:
        abort(400)
    new_val = not current[key]
    feature_flags.set_feature(key, new_val)
    label = {
        "ask_btn_enabled":     "Button Direkte Antwort",
        "ticket_open_enabled": "Button Ticket eroeffnen",
        "snippets_enabled":    "Snippets",
        "rag_enabled":         "Wissensbasis",
    }.get(key, key)
    state = "aktiviert" if new_val else "deaktiviert"
    flash(f"✓ {label} {state}.", "success")
    return redirect(request.referrer or url_for("dashboard"))


# ---------- Bot-Nachrichten ----------

@app.route("/messages", methods=["GET", "POST"])
@auth.login_required
def messages_page():
    import messages as msg_store
    if request.method == "POST":
        if not check_csrf():
            abort(403)
        keys = [
            "ticket_title", "ticket_description",
            "panel_title", "panel_description",
            "ask_btn_label",
            "modal_title", "modal_label", "modal_placeholder",
            "crime_btn_anmelden", "crime_btn_abmelden",
            "crime_modal_anmelden", "crime_modal_abmelden", "crime_embed_title",
            "gewerbe_modal_title", "gewerbe_embed_title",
            "staatlich_modal_title", "staatlich_embed_title",
            "team_modal_title", "team_embed_title",
        ]
        updates = {k: request.form.get(k, "").strip() for k in keys}
        # Leere Felder ignorieren
        updates = {k: v for k, v in updates.items() if v}
        if msg_store.save(updates):
            flash("✓ Texte gespeichert. Beim nächsten Ticket/Panel-Post aktiv.", "success")
        else:
            flash("Fehler beim Speichern.", "err")
        return redirect(url_for("messages_page"))

    msgs = msg_store.get_all()

    def field(label, name, value, hint="", rows=2):
        safe = html.escape(value)
        return f"""
        <div class=form-row>
          <label>{label}</label>
          <textarea name="{name}" rows="{rows}" style="width:100%;font-family:monospace;font-size:.85rem">{safe}</textarea>
          {f'<div class=hint>{hint}</div>' if hint else ''}
        </div>"""

    channel_id = os.getenv("TICKET_CHANNEL_ID", "").strip()
    resend_hint = (f"sendet in Channel <code>{channel_id}</code>"
                   if channel_id else
                   "⚠ TICKET_CHANNEL_ID nicht gesetzt — erst unter Discord konfigurieren")

    content = f"""
    <h1 class=page-title>Bot-Texte</h1>
    <p class=small style="margin-bottom:1rem">Texte werden beim nächsten Ticket-Erstellen oder <code>/panel</code>-Aufruf aktiv.
    Laufende Tickets behalten ihre alten Texte.</p>

    <form method=post>
      {csrf_field()}

      <div class=card>
        <h2>🎫 Ticket-Eröffnung</h2>
        <p class=small>Erscheint im neu erstellten Ticket-Channel.</p>
        {field("Titel", "ticket_title", msgs["ticket_title"])}
        {field("Beschreibung", "ticket_description", msgs["ticket_description"],
               hint="Platzhalter: <code>{mention}</code> = @Username des Ticket-Erstellers", rows=4)}
      </div>

      <div class=card>
        <h2>📋 Support-Panel</h2>
        <p class=small>Erscheint im Panel das <code>/panel</code> postet.</p>
        {field("Titel", "panel_title", msgs["panel_title"])}
        {field("Beschreibung", "panel_description", msgs["panel_description"],
               hint="Discord-Markdown erlaubt: **fett**, *kursiv*, Zeilenumbruch mit \\n", rows=4)}
      </div>

      <div class=card>
        <h2>🟢 Button „Direkte Frage"</h2>
        {field("Button-Label", "ask_btn_label", msgs["ask_btn_label"],
               hint="Max. 80 Zeichen (Discord-Limit). Änderung nach Bot-Neustart + /panel aktiv.")}
      </div>

      <div class=card>
        <h2>❓ Modal „Direkte Frage"</h2>
        <p class=small>Das Formular das sich beim Klick auf „Direkte Frage" öffnet.</p>
        {field("Modal-Titel", "modal_title", msgs["modal_title"],
               hint="Max. 45 Zeichen (Discord-Limit)")}
        {field("Feld-Label", "modal_label", msgs["modal_label"])}
        {field("Platzhalter-Text", "modal_placeholder", msgs["modal_placeholder"],
               hint="Grau-hinterlegter Beispieltext im leeren Eingabefeld")}
      </div>

      <div class=card>
        <h2>🔫 Crime — Formulartexte</h2>
        <p class=small>Texte für das Crime-Ticket-Formular. <code>{{typ}}</code> wird im Embed-Titel durch „Anmelden" / „Abmelden" ersetzt.</p>
        {field("Button: Anmelden", "crime_btn_anmelden", msgs["crime_btn_anmelden"],
               hint="Text des grünen Buttons in der Typ-Auswahl")}
        {field("Button: Abmelden", "crime_btn_abmelden", msgs["crime_btn_abmelden"],
               hint="Text des roten Buttons in der Typ-Auswahl")}
        {field("Modal-Titel: Anmelden", "crime_modal_anmelden", msgs["crime_modal_anmelden"],
               hint="Titel des Eingabe-Popups (max. 45 Zeichen)")}
        {field("Modal-Titel: Abmelden", "crime_modal_abmelden", msgs["crime_modal_abmelden"],
               hint="Titel des Eingabe-Popups (max. 45 Zeichen)")}
        {field("Embed-Titel im Ticket", "crime_embed_title", msgs["crime_embed_title"],
               hint="Platzhalter: <code>{{typ}}</code> = Anmelden/Abmelden")}
      </div>

      <div class=card>
        <h2>🏪 Gewerbe — Formulartexte</h2>
        {field("Modal-Titel", "gewerbe_modal_title", msgs["gewerbe_modal_title"],
               hint="Titel des Eingabe-Popups (max. 45 Zeichen)")}
        {field("Embed-Titel im Ticket", "gewerbe_embed_title", msgs["gewerbe_embed_title"])}
      </div>

      <div class=card>
        <h2>🏛 Staatlich — Formulartexte</h2>
        {field("Modal-Titel", "staatlich_modal_title", msgs["staatlich_modal_title"],
               hint="Titel des Eingabe-Popups (max. 45 Zeichen)")}
        {field("Embed-Titel im Ticket", "staatlich_embed_title", msgs["staatlich_embed_title"])}
      </div>

      <div class=card>
        <h2>👥 Team Bewerbung — Formulartexte</h2>
        {field("Modal-Titel", "team_modal_title", msgs["team_modal_title"],
               hint="Titel des Eingabe-Popups (max. 45 Zeichen)")}
        {field("Embed-Titel im Ticket", "team_embed_title", msgs["team_embed_title"])}
      </div>

      <div class=btn-row>
        <button class="btn btn-success" type=submit>💾 Speichern</button>
        <a class="btn btn-secondary" href="{url_for('messages_page')}">↩ Zurücksetzen</a>
      </div>
    </form>

    <div class=card style="margin-top:1.5rem">
      <h2>📨 Panel neu senden</h2>
      <p class=small style="margin-bottom:.75rem">
        Sendet das Support-Panel (Embed + Buttons) erneut in den Ticket-Channel —
        nützlich nach Text-Änderungen oder wenn das alte Panel-Embed gelöscht wurde.<br>
        <span style="color:var(--text-secondary)">{resend_hint}</span>
      </p>
      <form method=post action="{url_for('panel_resend')}">
        {csrf_field()}
        <button class="btn btn-primary" type=submit{'  disabled' if not channel_id else ''}>
          📋 Panel neu senden
        </button>
      </form>
    </div>
    """
    return render("Bot-Texte", content, "msg")


@app.route("/panel/resend", methods=["POST"])
@auth.login_required
def panel_resend():
    if not check_csrf():
        abort(403)
    channel_id = os.getenv("TICKET_CHANNEL_ID", "").strip()
    if not channel_id:
        flash("⚠ TICKET_CHANNEL_ID ist nicht konfiguriert. Trage die Channel-ID unter Discord ein.", "err")
        return redirect(url_for("messages_page"))
    try:
        PANEL_RESEND_FLAG.parent.mkdir(parents=True, exist_ok=True)
        tmp = PANEL_RESEND_FLAG.with_suffix(".tmp")
        tmp.write_text(channel_id, encoding="utf-8")
        os.replace(tmp, PANEL_RESEND_FLAG)
        flash("✓ Panel wird in Kürze neu gesendet (Bot prüft alle 10 Sekunden).", "success")
    except Exception as e:
        flash(f"Fehler beim Schreiben der Flag-Datei: {e}", "err")
    return redirect(url_for("messages_page"))


# ---------- Ticket-Kategorien ----------

@app.route("/categories", methods=["GET", "POST"])
@auth.login_required
def categories_page():
    import ticket_categories as tc
    if request.method == "POST":
        if not check_csrf():
            abort(403)
        action = request.form.get("action", "")

        if action == "create":
            label = request.form.get("label", "").strip()
            emoji = request.form.get("emoji", "🎫").strip()
            desc  = request.form.get("description", "").strip()
            if label:
                tc.create(label, emoji, desc)
                flash(f'✓ Kategorie "{label}" erstellt. Panel neu senden um sie zu aktivieren.', "success")
            else:
                flash("Label darf nicht leer sein.", "err")

        elif action == "toggle":
            cat_id = request.form.get("cat_id", "")
            result = tc.toggle(cat_id)
            if result is not None:
                state = "aktiviert" if result else "deaktiviert"
                flash(f"✓ Kategorie {state}. Panel neu senden damit die Änderung im Discord erscheint.", "success")

        elif action == "toggle_ai":
            cat_id = request.form.get("cat_id", "")
            cat_obj = tc.get(cat_id)
            if cat_obj is not None:
                new_ai = not cat_obj.get("ai_enabled", True)
                tc.set_ai_enabled(cat_id, new_ai)
                state = "AN" if new_ai else "AUS"
                flash(f"✓ KI für diese Kategorie: {state}. Gilt für neue Tickets sofort.", "success")

        elif action == "delete":
            cat_id = request.form.get("cat_id", "")
            if tc.delete(cat_id):
                flash("✓ Kategorie gelöscht. Panel neu senden.", "success")
            else:
                flash("Kategorie nicht gefunden.", "err")

        elif action == "update":
            cat_id = request.form.get("cat_id", "")
            label  = request.form.get("label", "").strip()
            emoji  = request.form.get("emoji", "🎫").strip()
            desc   = request.form.get("description", "").strip()
            if label and tc.update(cat_id, label, emoji, desc):
                flash("✓ Kategorie aktualisiert. Panel neu senden.", "success")
            else:
                flash("Fehler beim Aktualisieren.", "err")

        elif action == "move_up":
            tc.move(request.form.get("cat_id", ""), -1)
        elif action == "move_down":
            tc.move(request.form.get("cat_id", ""), +1)

        return redirect(url_for("categories_page"))

    cats    = tc.list_all()
    edit_id = request.args.get("edit", "")
    edit_cat = tc.get(edit_id) if edit_id else None

    rows = ""
    for c in cats:
        enabled  = c.get("enabled", True)
        ai_on    = c.get("ai_enabled", True)
        tog_cls  = "btn-danger" if enabled else "btn-success"
        tog_lbl  = "Deaktivieren" if enabled else "Aktivieren"
        ai_cls   = "btn-success" if ai_on else "btn-secondary"
        ai_lbl   = "🤖 KI AN" if ai_on else "🤖 KI AUS"
        status   = '<span class=status-on>● AN</span>' if enabled else '<span class=status-off>○ AUS</span>'
        edit_url = url_for("categories_page") + f"?edit={c['id']}"
        edit_active = "style=\"background:var(--bg-card-hover)\"" if c["id"] == edit_id else ""
        rows += f"""
        <tr {edit_active}>
          <td style="font-size:1.4rem;text-align:center">{html.escape(c.get("emoji","🎫"))}</td>
          <td><strong>{html.escape(c["label"])}</strong>
              {f'<div class=hint>{html.escape(c.get("description",""))}</div>' if c.get("description") else ''}</td>
          <td><code style="font-size:.8rem;color:var(--text-secondary)">{html.escape(c["id"])}</code></td>
          <td>{status}</td>
          <td>
            <div style="display:flex;gap:.3rem;flex-wrap:wrap">
              <a class="btn btn-cyan" href="{edit_url}" style="padding:3px 10px;font-size:.8rem">✏ Bearbeiten</a>
              <form method=post style="display:inline">
                {csrf_field()}
                <input type=hidden name=action value=toggle>
                <input type=hidden name=cat_id value="{c['id']}">
                <button class="btn {tog_cls}" style="padding:3px 10px;font-size:.8rem">{tog_lbl}</button>
              </form>
              <form method=post style="display:inline">
                {csrf_field()}
                <input type=hidden name=action value=toggle_ai>
                <input type=hidden name=cat_id value="{c['id']}">
                <button class="btn {ai_cls}" style="padding:3px 10px;font-size:.8rem" title="KI-Antwort ein/ausschalten">{ai_lbl}</button>
              </form>
              <form method=post style="display:inline">
                {csrf_field()}
                <input type=hidden name=action value=move_up>
                <input type=hidden name=cat_id value="{c['id']}">
                <button class="btn btn-secondary" style="padding:3px 8px;font-size:.8rem" title="Nach oben">▲</button>
              </form>
              <form method=post style="display:inline">
                {csrf_field()}
                <input type=hidden name=action value=move_down>
                <input type=hidden name=cat_id value="{c['id']}">
                <button class="btn btn-secondary" style="padding:3px 8px;font-size:.8rem" title="Nach unten">▼</button>
              </form>
              <form method=post style="display:inline">
                {csrf_field()}
                <input type=hidden name=action value=delete>
                <input type=hidden name=cat_id value="{c['id']}">
                <button class="btn btn-danger" style="padding:3px 10px;font-size:.8rem"
                  onclick="return confirm('Kategorie löschen?')">✕</button>
              </form>
            </div>
          </td>
        </tr>"""

    # Bearbeiten-Formular (erscheint wenn ?edit=<id> gesetzt)
    edit_form = ""
    if edit_cat:
        edit_form = f"""
    <div class=card style="border:1px solid var(--accent-cyan)">
      <h2>✏ Bearbeiten — {html.escape(edit_cat['label'])}</h2>
      <form method=post>
        {csrf_field()}
        <input type=hidden name=action value=update>
        <input type=hidden name=cat_id value="{edit_cat['id']}">
        <div class=grid style="grid-template-columns:3fr 1fr 3fr;gap:.75rem;align-items:end">
          <div class=form-row style="margin:0">
            <label>Label</label>
            <input type=text name=label value="{html.escape(edit_cat['label'])}" required style="width:100%">
          </div>
          <div class=form-row style="margin:0">
            <label>Emoji</label>
            <input type=text name=emoji value="{html.escape(edit_cat.get('emoji','🎫'))}" maxlength=4
                   style="width:100%;font-size:1.2rem;text-align:center">
          </div>
          <div class=form-row style="margin:0">
            <label>Beschreibung</label>
            <input type=text name=description value="{html.escape(edit_cat.get('description',''))}"
                   placeholder="Kurze Erklärung" style="width:100%">
          </div>
        </div>
        <div class=btn-row style="margin-top:.75rem">
          <button class="btn btn-success" type=submit>💾 Speichern</button>
          <a class="btn btn-secondary" href="{url_for('categories_page')}">✕ Abbrechen</a>
        </div>
      </form>
    </div>"""

    messages_url = url_for("messages_page")
    content = f"""
    <h1 class=page-title>Ticket-Kategorien</h1>
    <p class=small style="margin-bottom:1rem">
      Lege Kategorien fest, die als Buttons im Support-Panel erscheinen.<br>
      Nach jeder Änderung unter <a href="{messages_url}">Bot-Texte → Panel neu senden</a> klicken.
    </p>

    <div class=card>
      <h2>Aktive Kategorien</h2>
      <table>
        <tr><th>Emoji</th><th>Label</th><th>ID</th><th>Status</th><th>Aktionen</th></tr>
        {rows if rows else '<tr><td colspan=5 style="text-align:center;color:var(--text-secondary)">Keine Kategorien angelegt.</td></tr>'}
      </table>
    </div>

    {edit_form}

    <div class=card>
      <h2>➕ Neue Kategorie</h2>
      <form method=post>
        {csrf_field()}
        <input type=hidden name=action value=create>
        <div class=grid style="grid-template-columns:3fr 1fr 3fr;gap:.75rem;align-items:end">
          <div class=form-row style="margin:0">
            <label>Label <span class=hint>(z.B. „Fahrzeuge")</span></label>
            <input type=text name=label placeholder="Label" required style="width:100%">
          </div>
          <div class=form-row style="margin:0">
            <label>Emoji</label>
            <input type=text name=emoji placeholder="🎫" maxlength=4 style="width:100%;font-size:1.2rem;text-align:center">
          </div>
          <div class=form-row style="margin:0">
            <label>Beschreibung <span class=hint>(optional)</span></label>
            <input type=text name=description placeholder="Kurze Erklärung" style="width:100%">
          </div>
        </div>
        <div class=btn-row style="margin-top:.75rem">
          <button class="btn btn-success" type=submit>➕ Erstellen</button>
        </div>
      </form>
    </div>

    <div class=card>
      <h2>📨 Panel neu senden</h2>
      <p class=small style="margin-bottom:.75rem">
        Das Panel wird über <a href="{messages_url}">Bot-Texte</a> gesendet — dort ist die einzige Stelle für Panel-Resend.
      </p>
      <a class="btn btn-primary" href="{messages_url}">→ Zu Bot-Texte (Panel neu senden)</a>
    </div>
    """
    return render("Kategorien", content, "cats")


# ---------- Team-Bereiche ----------

@app.route("/team-areas", methods=["GET", "POST"])
@auth.login_required
def team_areas_page():
    import team_areas as ta
    if request.method == "POST":
        if not check_csrf():
            abort(403)
        action = request.form.get("action", "")
        if action == "create":
            label = request.form.get("label", "").strip()
            emoji = request.form.get("emoji", "🎯").strip()
            if label:
                ta.create(label, emoji)
                flash(f'✓ Bereich „{label}" hinzugefügt.', "success")
            else:
                flash("Label darf nicht leer sein.", "err")
        elif action == "delete":
            ta.delete(request.form.get("area_id", ""))
        elif action == "move_up":
            ta.move(request.form.get("area_id", ""), -1)
        elif action == "move_down":
            ta.move(request.form.get("area_id", ""), +1)
        return redirect(url_for("team_areas_page"))

    areas = ta.list_all()
    rows = ""
    for a in areas:
        rows += f"""
        <tr>
          <td style="font-size:1.3rem;text-align:center">{html.escape(a.get('emoji',''))}</td>
          <td>{html.escape(a['label'])}</td>
          <td>
            <form method=post style="display:inline">
              {csrf_field()}
              <input type=hidden name=action value=move_up>
              <input type=hidden name=area_id value="{a['id']}">
              <button class="btn btn-secondary btn-sm" type=submit title="Nach oben">▲</button>
            </form>
            <form method=post style="display:inline">
              {csrf_field()}
              <input type=hidden name=action value=move_down>
              <input type=hidden name=area_id value="{a['id']}">
              <button class="btn btn-secondary btn-sm" type=submit title="Nach unten">▼</button>
            </form>
            <form method=post style="display:inline" onsubmit="return confirm('Bereich löschen?')">
              {csrf_field()}
              <input type=hidden name=action value=delete>
              <input type=hidden name=area_id value="{a['id']}">
              <button class="btn btn-danger btn-sm" type=submit>🗑</button>
            </form>
          </td>
        </tr>"""

    content = f"""
    <h1 class=page-title>Team-Bereiche</h1>
    <p class=small style="margin-bottom:1rem">
      Verwalte die Auswahloptionen im Team-Bewerbungs-Dropdown.
      Änderungen sind sofort aktiv — kein Bot-Neustart nötig.
    </p>

    <div class=card>
      <h2>Aktuelle Bereiche</h2>
      <table>
        <tr><th>Emoji</th><th>Label</th><th>Aktionen</th></tr>
        {rows if rows else '<tr><td colspan=3 style="color:var(--muted)">Keine Bereiche vorhanden.</td></tr>'}
      </table>
    </div>

    <div class=card>
      <h2>Neuen Bereich hinzufügen</h2>
      <form method=post>
        {csrf_field()}
        <input type=hidden name=action value=create>
        <div class=grid style="grid-template-columns:3fr 1fr;gap:.75rem;align-items:end">
          <div class=form-row style="margin:0">
            <label>Label</label>
            <input type=text name=label placeholder="z.B. Mapping" required style="width:100%">
          </div>
          <div class=form-row style="margin:0">
            <label>Emoji</label>
            <input type=text name=emoji placeholder="🎯" maxlength=4 style="width:100%;font-size:1.2rem;text-align:center">
          </div>
        </div>
        <div class=btn-row style="margin-top:.75rem">
          <button class="btn btn-success" type=submit>➕ Hinzufügen</button>
        </div>
      </form>
    </div>
    """
    return render("Team-Bereiche", content, "team_areas")


# ---------- Settings ----------

@app.route("/settings", methods=["GET", "POST"])
@auth.login_required
def settings_page():
    if request.method == "POST":
        editable_plain = ["CLAUDE_MODEL", "EMBED_MODEL", "CONFIDENCE_THRESHOLD",
                          "MAX_TOKENS", "TOP_K", "SNIPPET_THRESHOLD",
                          "ADMIN_USER", "ADMIN_PORT"]
        env = read_env()
        for k in editable_plain:
            v = request.form.get(k, "").strip()
            if v:
                env[k] = v
        for k in ["ANTHROPIC_API_KEY", "ADMIN_PASSWORD"]:
            v = request.form.get(k, "").strip()
            if v:
                env[k] = v
        write_env(env)
        flash("✓ Einstellungen gespeichert. Bot-Neustart empfohlen.")
        return redirect(url_for("settings_page"))

    env = read_env()
    def field(key, label, typ="text", placeholder=""):
        val = env.get(key, "")
        show = "" if ("TOKEN" in key or "KEY" in key or "PASSWORD" in key) else val
        return f"""<div class=form-row>
          <label>{label}</label>
          <input type={typ} name={key} value="{show}" placeholder="{placeholder or 'Default: '+str(val) if val else ''}">
        </div>"""
    logo = current_logo_path()
    logo_preview = (
        f'<img src="{url_for("serve_logo")}?v={int(logo.stat().st_mtime)}" '
        f'style="max-height:80px;background:var(--bg-secondary);padding:8px;border-radius:4px;border:1px solid var(--border)">'
        if logo else '<span class=muted>kein Logo gesetzt (Default: TICKET•TOOL Text)</span>'
    )
    remove_btn = (
        f'<form method=post action="{url_for("logo_delete")}" style="display:inline;margin-left:0.6rem">'
        f'<button class="btn btn-danger" type=submit onclick="return confirm(\'Logo entfernen?\')">Entfernen</button></form>'
        if logo else ''
    )
    branding_card = f"""
    <div class=card><h2>Branding // Logo (oben links)</h2>
      <div style="margin-bottom:1rem">{logo_preview}</div>
      <form method=post enctype=multipart/form-data action="{url_for('logo_upload')}">
        <div class=form-row>
          <label>Logo-Datei</label>
          <input type=file name=logo required accept=".png,.jpg,.jpeg,.webp,.svg,.gif">
          <div class=hint>Erlaubt: PNG, JPG, WEBP, SVG, GIF. Empfohlen: ca. 200x60px, transparenter Hintergrund.</div>
        </div>
        <button class="btn btn-success" type=submit>Logo hochladen</button>
        {remove_btn}
      </form>
    </div>
    """

    content = f"""
    <h1 class=page-title>Settings</h1>

    {branding_card}

    <form method=post>
      <div class=card><h2>AI-Konfiguration</h2>
        {field('CLAUDE_MODEL','Claude-Modell','text','claude-haiku-4-5')}
        {field('MAX_TOKENS','Max Tokens pro Antwort','number')}
        {field('TOP_K','Top-K Retrieval-Chunks','number')}
        {field('CONFIDENCE_THRESHOLD','RAG Confidence-Threshold (0-1)')}
        {field('SNIPPET_THRESHOLD','Snippet-Match-Threshold (0-1)')}
        {field('EMBED_MODEL','Embedding-Modell','text','all-MiniLM-L6-v2')}
      </div>

      <div class=card><h2>Admin-Panel</h2>
        {field('ADMIN_USER','Admin-Benutzername','text','admin')}
        {field('ADMIN_PORT','Admin-Port','number','5555')}
      </div>

      <div class=card><h2>Secrets (leer = unveraendert)</h2>
        {field('ANTHROPIC_API_KEY','Anthropic-API-Key','password','sk-ant-...')}
        {field('ADMIN_PASSWORD','Admin-Passwort (dieses Panel)','password')}
      </div>

      <button class="btn btn-success" type=submit>💾 Einstellungen speichern</button>
    </form>
    """
    return render("Settings", content, "settings")


# ---------- Logs ----------

@app.route("/logs")
@auth.login_required
def logs_page():
    n = int(request.args.get("lines", 200))
    log_file = LOG_DIR / "bot.log"
    content_log = ""
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            content_log = "\n".join(lines[-n:])
        except Exception as e:
            content_log = f"Lese-Fehler: {e}"
    else:
        content_log = "(noch keine Logs, Bot startet)"
    safe_log = content_log.replace('<','&lt;').replace('>','&gt;')
    content = f"""
    <h1 class=page-title>Logs</h1>
    <div class=card><h2>Bot-Log · letzte {n} Zeilen</h2>
      <p class=small style="margin-bottom:1rem">Datei: <code>{log_file}</code></p>
      <div class=btn-row>
        <a class="btn btn-secondary" href="?lines=50">50</a>
        <a class="btn btn-secondary" href="?lines=200">200</a>
        <a class="btn btn-secondary" href="?lines=500">500</a>
        <a class="btn btn-secondary" href="?lines=2000">2000</a>
        <a class="btn btn-secondary" href="?lines={n}">🔄 Reload</a>
      </div>
      <pre class=log style="margin-top:1rem">{safe_log}</pre>
    </div>
    """
    return render("Logs", content, "logs")


# ---------- Bot-Control ----------

@app.route("/bot")
@auth.login_required
def bot_page():
    running, pid = bot_running()
    status_html = (f'<span class=status-on>● ONLINE (PID {pid})</span>' if running
                   else '<span class=status-off>○ OFFLINE</span>')
    content = f"""
    <h1 class=page-title>Bot-Control</h1>
    <div class=card><h2>Prozess-Status</h2>
      <p style="font-size:1.1rem">Status: {status_html}</p>
      <div class=btn-row>
        <form method=post action="{url_for('bot_start')}" style="display:inline">
          <button class="btn btn-success" type=submit {'disabled' if running else ''}>▶ Start</button>
        </form>
        <form method=post action="{url_for('bot_stop')}" style="display:inline">
          <button class="btn btn-danger" type=submit {'disabled' if not running else ''}>⏹ Stop</button>
        </form>
        <form method=post action="{url_for('bot_restart')}" style="display:inline">
          <button class="btn btn-warn" type=submit>🔄 Restart</button>
        </form>
      </div>
      <p class=small style="margin-top:1rem">Bot laeuft als Subprozess.
        PID-Datei: <code>data/bot.pid</code>. Logs: <code>logs/bot.log</code>.</p>
    </div>
    <div class=card><h2>Voraussetzungen</h2>
      <ul class=small style="margin-left:1.5rem">
        <li>Discord-Token gesetzt (<a href="{url_for('discord_page')}">Discord konfigurieren</a>)</li>
        <li>Anthropic-API-Key gesetzt (<a href="{url_for('settings_page')}">Settings</a>)</li>
        <li>Wissensbasis indexiert (<a href="{url_for('kb_page')}">Wissensbasis</a>)</li>
      </ul>
    </div>
    """
    return render("Bot-Control", content, "bot")


@app.route("/bot/start", methods=["POST"])
@auth.login_required
def bot_start():
    running, _ = bot_running()
    if running:
        flash("Bot laeuft bereits.", "err")
        return redirect(url_for("bot_page"))
    py = str(ROOT / "venv" / "Scripts" / "pythonw.exe")
    if not Path(py).exists():
        py = str(ROOT / "venv" / "Scripts" / "python.exe")
    if not Path(py).exists():
        py = sys.executable
    LOG_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / "bot.log"
    try:
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        proc = subprocess.Popen(
            [py, str(ROOT / "src" / "bot.py")],
            cwd=str(ROOT),
            stdout=open(log_file, "ab"),
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        BOT_PID_FILE.write_text(str(proc.pid))
        flash(f"✓ Bot gestartet (PID {proc.pid}).")
    except Exception as e:
        flash(f"Start-Fehler: {e}", "err")
    return redirect(url_for("bot_page"))


@app.route("/bot/stop", methods=["POST"])
@auth.login_required
def bot_stop():
    running, pid = bot_running()
    if not running or not pid:
        flash("Bot laeuft nicht.", "err")
        return redirect(url_for("bot_page"))
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
        for f in (BOT_PID_FILE, _BOT_LOCK_FILE):
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass
        flash(f"✓ Bot gestoppt (PID {pid}).")
    except Exception as e:
        flash(f"Stop-Fehler: {e}", "err")
    return redirect(url_for("bot_page"))


@app.route("/bot/restart", methods=["POST"])
@auth.login_required
def bot_restart():
    import time
    bot_stop()
    time.sleep(2)
    bot_start()
    return redirect(url_for("bot_page"))


@app.route("/api/stats")
@auth.login_required
def api_stats():
    running, pid = bot_running()
    return jsonify({
        "bot_running": running,
        "bot_pid": pid,
        "kb_chunks": kb_stats(),
        "kb_files": len(list_kb_files()),
        "timestamp": datetime.utcnow().isoformat(),
    })


# ---------- Entry ----------

if __name__ == "__main__":
    print(f"[admin] Panel -> http://localhost:{ADMIN_PORT}")
    print(f"[admin] Login: {ADMIN_USER} / (siehe .env)")
    app.run(host="127.0.0.1", port=ADMIN_PORT, debug=False)

import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any

from flask import Flask, jsonify, Response, request, send_file
from dotenv import load_dotenv

import leaderboard

load_dotenv()   # .env einlesen: GOAL_NETTO_EUR, DASHBOARD_LISTEN_*, ...

# Pfad zur JSONL-Datei – gleicher Ordner wie die anderen Skripte
CASE_FILE_PATH = os.getenv("CASE_FILE", "case_files.jsonl")
STREAM_START_FILE = os.getenv("STREAM_START_FILE", "current_stream_start.json")
DASHBOARD_HTML = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "WhiteHouseDashboard.html"
)

app = Flask(__name__)


def load_cases() -> List[Dict[str, Any]]:
    """Liest alle CaseFiles aus case_files.jsonl."""
    if not os.path.exists(CASE_FILE_PATH):
        return []

    cases: List[Dict[str, Any]] = []
    with open(CASE_FILE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                cases.append(obj)
            except json.JSONDecodeError:
                # kaputte Zeile überspringen
                continue
    return cases


def parse_numeric_amount(case: Dict[str, Any]) -> float:
    """Holt, falls möglich, einen numerischen Betrag aus dem Case."""
    amount = case.get("amount")
    try:
        if amount is None:
            return 0.0
        return float(amount)
    except (TypeError, ValueError):
        return 0.0


STATS_FILE = os.getenv("STATS_FILE", "stats.json")
ADMIN_CONFIG_FILE = os.getenv("ADMIN_CONFIG_FILE", "admin_config.json")


def load_stats() -> Dict[str, Any]:
    """Einnahmen aus stats.json, fehlende Felder mit 0 vorbelegt."""
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f) or {}
    except Exception:
        d = {}
    for k in ("kofi_brutto_eur", "kofi_netto_eur",
              "tebex_brutto_eur", "tebex_netto_eur",
              "subs_brutto_eur", "subs_netto_eur", "bits_value_eur"):
        d.setdefault(k, 0.0)
    for k in ("gifted_subs_total", "bits_total"):
        d.setdefault(k, 0)
    return d


def current_goal() -> float:
    """Effektives Goal: admin_config.json-Override, sonst .env GOAL_NETTO_EUR."""
    try:
        with open(ADMIN_CONFIG_FILE, "r", encoding="utf-8") as f:
            v = float((json.load(f) or {}).get("goal_eur", 0) or 0)
            if v > 0:
                return v
    except Exception:
        pass
    try:
        return float(os.getenv("GOAL_NETTO_EUR", "3000") or 3000)
    except (TypeError, ValueError):
        return 3000.0


@app.route("/stats")
def stats_endpoint() -> Response:
    """Einnahmen-Stats + effektives Goal — vom Dashboard erwartet (<base>/stats)."""
    data = load_stats()
    data["goal"] = current_goal()
    return jsonify(data)


@app.route("/goal", methods=["POST"])
def set_goal() -> Response:
    """Goal zentral setzen: schreibt goal_eur in admin_config.json.

    Dieselbe Datei lesen Relay (Discord-Embed) und Admin-Panel — somit gilt
    das Goal ueberall.
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        val = round(float(data.get("goal")), 2)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "ungueltiger Wert"}), 400
    if val <= 0:
        return jsonify({"ok": False, "error": "Goal muss groesser 0 sein"}), 400
    cfg: Dict[str, Any] = {}
    try:
        with open(ADMIN_CONFIG_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                cfg = loaded
    except Exception:
        cfg = {}
    cfg["goal_eur"] = val
    tmp = f"{ADMIN_CONFIG_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ADMIN_CONFIG_FILE)
    return jsonify({"ok": True, "goal": val})


@app.route("/cases")
def cases_endpoint() -> Response:
    """Cases als reines Array — vom Dashboard erwartet (<base>/cases)."""
    cases = load_cases()
    try:
        limit = int(request.args.get("limit", 0))
    except (TypeError, ValueError):
        limit = 0
    if limit > 0:
        cases = cases[-limit:]
    return jsonify(cases)


@app.route("/api/cases")
def api_cases() -> Response:
    """
    API-Endpoint:
    - gibt alle Cases zurück
    - plus aggregierte Statistiken für Dashboard
    """
    cases = load_cases()

    total_events = len(cases)
    twitch_events = sum(1 for c in cases if c.get("source") == "TWITCH")
    kofi_events = sum(1 for c in cases if c.get("source") == "KOFI")
    tebex_events = sum(1 for c in cases if c.get("source") == "TEBEX")

    # Summe Betrag
    total_volume = 0.0
    for c in cases:
        total_volume += parse_numeric_amount(c)

    # Verteilung nach Clearance
    clearance_counts: Dict[str, int] = {}
    for c in cases:
        cl = c.get("classification") or "UNKNOWN"
        clearance_counts[cl] = clearance_counts.get(cl, 0) + 1

    # Volumen nach Kategorie
    category_volume: Dict[str, float] = {}
    for c in cases:
        cat = c.get("category") or "UNKNOWN"
        category_volume[cat] = category_volume.get(cat, 0.0) + parse_numeric_amount(c)

    # Sortieren nach Zeit absteigend
    def sort_key(case: Dict[str, Any]):
        ts = case.get("created_at") or case.get("timestamp")
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            dt = datetime.min
        # Naive Zeitstempel auf UTC heben — sonst Vergleich aware/naive -> TypeError
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    cases_sorted = sorted(cases, key=sort_key, reverse=True)

    return jsonify({
        "summary": {
            "total_events": total_events,
            "twitch_events": twitch_events,
            "kofi_events": kofi_events,
            "tebex_events": tebex_events,
            "total_volume": total_volume,
            "clearance_counts": clearance_counts,
            "category_volume": category_volume,
        },
        "cases": cases_sorted,
    })


@app.route("/api/leaderboard")
def api_leaderboard() -> Response:
    scope = (request.args.get("scope") or "all").lower()
    if scope not in {"all", "current"}:
        scope = "all"
    try:
        limit = int(request.args.get("limit") or "10")
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 100))
    donors = leaderboard.top_donors(
        scope=scope, limit=limit,
        case_file=CASE_FILE_PATH, stream_start_file=STREAM_START_FILE,
    )
    return jsonify({"scope": scope, "limit": limit, "donors": donors})


@app.route("/")
def index() -> Response:
    """Serves WhiteHouseDashboard.html if present, else falls back to inline."""
    if os.path.exists(DASHBOARD_HTML):
        return send_file(DASHBOARD_HTML, mimetype="text/html")
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Liberty City White House – Live Ops Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #050810;
      color: #f5f5f5;
      margin: 0;
      padding: 0;
    }
    header {
      padding: 16px 24px;
      border-bottom: 1px solid #222;
      background: linear-gradient(90deg, #111827, #1f2937);
    }
    h1 {
      margin: 0;
      font-size: 1.4rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }
    .subtitle {
      font-size: 0.8rem;
      color: #9ca3af;
    }
    main {
      padding: 16px 24px 32px;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }
    .status-text {
      font-size: 0.8rem;
      color: #9ca3af;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }
    .card {
      background: #111827;
      border-radius: 8px;
      padding: 12px 14px;
      border: 1px solid #1f2937;
    }
    .card-title {
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #9ca3af;
      margin-bottom: 4px;
    }
    .card-value {
      font-size: 1.2rem;
      font-weight: 600;
    }
    .card-sub {
      font-size: 0.75rem;
      color: #6b7280;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(0, 2fr);
      gap: 16px;
      margin-bottom: 24px;
    }
    .panel {
      background: #111827;
      border-radius: 8px;
      padding: 12px 14px;
      border: 1px solid #1f2937;
    }
    .panel h2 {
      font-size: 0.9rem;
      margin: 0 0 8px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #9ca3af;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.75rem;
    }
    thead {
      background: #020617;
      position: sticky;
      top: 0;
      z-index: 1;
    }
    th, td {
      padding: 6px 8px;
      border-bottom: 1px solid #1f2937;
      text-align: left;
      white-space: nowrap;
    }
    tbody tr:nth-child(odd) {
      background: #0b1120;
    }
    tbody tr:nth-child(even) {
      background: #020617;
    }
    .badge {
      display: inline-block;
      padding: 2px 6px;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 500;
    }
    .badge-twitch { background: #4b1f7a; color: #e5e7eb; }
    .badge-kofi   { background: #1e3a8a; color: #e5e7eb; }
    .badge-tebex  { background: #7a3a0f; color: #fde68a; }
    .badge-sub    { background: #14532d; color: #bbf7d0; }
    .badge-bits   { background: #7c2d12; color: #fde68a; }
    .badge-don    { background: #064e3b; color: #a7f3d0; }

    .refresh-info {
      font-size: 0.75rem;
      color: #6b7280;
    }

    @media (max-width: 900px) {
      .grid {
        grid-template-columns: minmax(0, 1fr);
      }
    }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
<header>
  <h1>Liberty City White House – Live Ops Dashboard</h1>
  <div class="subtitle">Case Files Monitor • LCWH Intelligence Branch</div>
</header>

<main>
  <div class="topbar">
    <div class="status-text" id="statusText">
      Waiting for first update…
    </div>
    <div class="refresh-info">
      Auto-Refresh every <span id="intervalSec">10</span>s
    </div>
  </div>

  <div class="cards">
    <div class="card">
      <div class="card-title">Total Events</div>
      <div class="card-value" id="totalEvents">–</div>
      <div class="card-sub">All logged case files</div>
    </div>
    <div class="card">
      <div class="card-title">Twitch Events</div>
      <div class="card-value" id="twitchEvents">–</div>
      <div class="card-sub">Subs, Gifts, Bits, Resubs</div>
    </div>
    <div class="card">
      <div class="card-title">Ko-fi Events</div>
      <div class="card-value" id="kofiEvents">–</div>
      <div class="card-sub">Support & Shop Orders</div>
    </div>
    <div class="card">
      <div class="card-title">Tebex Events</div>
      <div class="card-value" id="tebexEvents">–</div>
      <div class="card-sub">FiveM-Shop-Käufe</div>
    </div>
    <div class="card">
      <div class="card-title">Estimated Total Volume</div>
      <div class="card-value" id="totalVolume">–</div>
      <div class="card-sub">Sum of parsed amounts</div>
    </div>
  </div>

  <div class="grid">
    <div class="panel">
      <h2>Events per Clearance Level</h2>
      <canvas id="clearanceChart" height="150"></canvas>
    </div>
    <div class="panel">
      <h2>Volume by Category</h2>
      <canvas id="categoryChart" height="150"></canvas>
    </div>
  </div>

  <div class="panel">
    <h2>Recent Case Files</h2>
    <div style="overflow-x:auto; max-height:400px;">
      <table id="casesTable">
        <thead>
        <tr>
          <th>Time</th>
          <th>Case ID</th>
          <th>Source</th>
          <th>Category</th>
          <th>Clearance</th>
          <th>Amount</th>
          <th>Intel Summary</th>
        </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</main>

<script>
  const REFRESH_INTERVAL_MS = 10000; // 10 Sekunden
  document.getElementById("intervalSec").textContent = REFRESH_INTERVAL_MS / 1000;

  let clearanceChart = null;
  let categoryChart = null;

  async function fetchCases() {
    try {
      const resp = await fetch("/api/cases");
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      updateDashboard(data);
      document.getElementById("statusText").textContent =
        "Last update: " + new Date().toLocaleString();
    } catch (err) {
      console.error("Fehler bei fetch /api/cases:", err);
      document.getElementById("statusText").textContent =
        "Error fetching data. Check server logs.";
    }
  }

  function formatNumberDE(n) {
    if (isNaN(n)) return "–";
    return n.toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }

  function updateDashboard(data) {
    const summary = data.summary || {};
    const cases = data.cases || [];

    document.getElementById("totalEvents").textContent = summary.total_events ?? "0";
    document.getElementById("twitchEvents").textContent = summary.twitch_events ?? "0";
    document.getElementById("kofiEvents").textContent = summary.kofi_events ?? "0";
    document.getElementById("tebexEvents").textContent = summary.tebex_events ?? "0";
    document.getElementById("totalVolume").textContent = formatNumberDE(summary.total_volume || 0);

    buildClearanceChart(summary.clearance_counts || {});
    buildCategoryChart(summary.category_volume || {});
    renderTable(cases);
  }

  function buildClearanceChart(clearanceCounts) {
    const labels = Object.keys(clearanceCounts);
    const data = labels.map(k => clearanceCounts[k]);

    if (clearanceChart) clearanceChart.destroy();
    const ctx = document.getElementById("clearanceChart").getContext("2d");
    clearanceChart = new Chart(ctx, {
      type: "pie",
      data: {
        labels,
        datasets: [{
          data
        }]
      },
      options: {
        plugins: {
          legend: {
            labels: { color: "#e5e7eb" }
          }
        }
      }
    });
  }

  function buildCategoryChart(categoryVolume) {
    const labels = Object.keys(categoryVolume);
    const data = labels.map(k => categoryVolume[k]);

    if (categoryChart) categoryChart.destroy();
    const ctx = document.getElementById("categoryChart").getContext("2d");
    categoryChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          data
        }]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#e5e7eb" } },
          y: { ticks: { color: "#e5e7eb" } }
        }
      }
    });
  }

  function renderTable(cases) {
    const tbody = document.querySelector("#casesTable tbody");
    tbody.innerHTML = "";

    for (const c of cases) {
      const tr = document.createElement("tr");

      let tsText = "–";
      if (c.created_at) {
        try {
          tsText = new Date(c.created_at).toLocaleString("de-DE");
        } catch {}
      }

      const src = c.source || "-";
      const cat = c.category || "-";
      const cl = c.classification || "-";
      const amt = (typeof c.amount === "number") ? c.amount : null;
      const intel = c.intel_summary || "";

      const sourceClass =
        src === "TWITCH" ? "badge-twitch" :
        src === "KOFI"   ? "badge-kofi"   :
        src === "TEBEX"  ? "badge-tebex"  :
        "badge";

      const catLower = cat.toLowerCase();
      const catClass =
        catLower.includes("SUB".toLowerCase()) ? "badge-sub" :
        catLower.includes("BITS".toLowerCase()) ? "badge-bits" :
        catLower.includes("DON") ? "badge-don" :
        "badge";

      tr.innerHTML = `
        <td>${tsText}</td>
        <td>${c.case_id || "-"}</td>
        <td><span class="badge ${sourceClass}">${src}</span></td>
        <td><span class="badge ${catClass}">${cat}</span></td>
        <td>${cl}</td>
        <td>${amt !== null ? formatNumberDE(amt) : "–"}</td>
        <td>${intel}</td>
      `;

      tbody.appendChild(tr);
    }
  }

  // Initialer Aufruf + Auto-Refresh
  fetchCases();
  setInterval(fetchCases, REFRESH_INTERVAL_MS);
</script>
</body>
</html>
    """
    return Response(html, mimetype="text/html")


def main():
    host = os.getenv("DASHBOARD_LISTEN_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_LISTEN_PORT", "5000"))
    print(f"White House Live Dashboard läuft auf http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()

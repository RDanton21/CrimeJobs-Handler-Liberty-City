function getParam(name, fallback){
  const url = new URL(window.location.href);
  return url.searchParams.get(name) ?? fallback;
}

const SCOPE = (getParam("scope", "current") || "current").toLowerCase();
const LIMIT = Math.max(1, Math.min(parseInt(getParam("limit", "5"), 10) || 5, 20));
const REFRESH_MS = Math.max(2000, parseInt(getParam("ms", "10000"), 10) || 10000);
const DEFAULT_API = new URL("/api/leaderboard", window.location.origin).toString();
const API_URL = getParam("api", DEFAULT_API) + `?scope=${SCOPE}&limit=${LIMIT}`;

document.getElementById("scopeLabel").textContent =
  SCOPE === "current" ? "Current Stream" : "All-Time";

function fmtEur(n){
  return n.toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " €";
}
function fmtTime(){
  return new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function setState(text){ document.getElementById("chipState").textContent = text; }

function render(donors){
  const ol = document.getElementById("lbList");
  if (!donors || donors.length === 0){
    ol.innerHTML = '<li class="lb-empty">Noch keine Spenden in diesem Zeitraum.</li>';
    return;
  }
  const rows = donors.map((d, i) => {
    const rank = i + 1;
    const rankClass = rank <= 3 ? `rank-${rank}` : "";
    const events = d.events > 1 ? `<span class="lb-events">(${d.events})</span>` : "";
    const name = (d.name || "Anonym").replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]));
    return `
      <li class="${rankClass}">
        <div class="lb-rank">#${rank}</div>
        <div class="lb-name">${name}${events}</div>
        <div class="lb-amount">${fmtEur(d.total_eur || 0)}</div>
      </li>`;
  });
  ol.innerHTML = rows.join("");
}

async function tick(){
  const lastEl = document.getElementById("last");
  try{
    const res = await fetch(API_URL, { cache: "no-store" });
    if(!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    render(data.donors || []);
    setState("Live • " + fmtTime());
    lastEl.textContent = SCOPE === "current" ? "Aktueller Stream" : "Gesamt";
  }catch(e){
    setState("Offline • API nicht erreichbar");
    lastEl.textContent = `?scope=current|all  ?limit=5`;
  }
}

setState("Verbinde…");
tick();
setInterval(tick, REFRESH_MS);

function getParam(name, fallback){
  const url = new URL(window.location.href);
  return url.searchParams.get(name) ?? fallback;
}

// Default: same-origin to avoid Mixed Content / CORS
const DEFAULT_API = new URL("/api/stats", window.location.origin).toString();
const API_URL = getParam("api", DEFAULT_API);
// Schnelles Polling -> Balken reagiert quasi sofort auf Donations
const REFRESH_MS = Math.max(500, parseInt(getParam("ms", "1500"), 10) || 1500);
const SOURCE_LABEL = "https://www.sektorrp.eu";

function colorFor(cappedPercent){
  // Discord logic: green only from 95%
  if (cappedPercent < 25) return "#3E2F5B";
  if (cappedPercent < 50) return "#E94560";
  if (cappedPercent < 95) return "#FFD800";
  return "#4EFF00";
}

function setState(text){
  document.getElementById("chipState").textContent = text;
}

function fmtTime(){
  return new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// --- Donation-Puls: Balken leuchtet kurz auf, Prozentzahl poppt ---
function pulse(){
  const shell = document.querySelector(".barShell");
  const pct = document.getElementById("pct");
  for (const el of [shell, pct]){
    if (!el) continue;
    el.classList.remove("bump");
    void el.offsetWidth; // Reflow erzwingen -> Animation startet neu
    el.classList.add("bump");
  }
}

// --- Konfetti (Canvas, ohne Abhängigkeiten) ---
const canvas = document.getElementById("confetti");
const ctx = canvas.getContext("2d");
let confettiPieces = [];
let confettiRAF = null;

function sizeCanvas(){
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
}
window.addEventListener("resize", sizeCanvas);
sizeCanvas();

const CONFETTI_COLORS = ["#E94560", "#FFD800", "#4EFF00", "#3E2F5B", "#ffffff", "#00d4ff"];

function launchConfetti(n = 180){
  for (let i = 0; i < n; i++){
    confettiPieces.push({
      x: Math.random() * canvas.width,
      y: -20 - Math.random() * canvas.height * 0.3,
      r: 4 + Math.random() * 7,
      c: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
      vx: -2.5 + Math.random() * 5,
      vy: 2 + Math.random() * 4.5,
      rot: Math.random() * Math.PI,
      vr: -0.25 + Math.random() * 0.5
    });
  }
  if (!confettiRAF) confettiRAF = requestAnimationFrame(stepConfetti);
}

function stepConfetti(){
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  confettiPieces = confettiPieces.filter(p => p.y < canvas.height + 40);
  for (const p of confettiPieces){
    p.x += p.vx;
    p.y += p.vy;
    p.vy += 0.05;
    p.rot += p.vr;
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(p.rot);
    ctx.fillStyle = p.c;
    ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * 0.6);
    ctx.restore();
  }
  if (confettiPieces.length){
    confettiRAF = requestAnimationFrame(stepConfetti);
  } else {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    confettiRAF = null;
  }
}

let prevNetto = null;   // null = erster Tick (keine Animation beim Start)
let prevLaps = null;    // wie oft das Goal voll erreicht wurde
let isComplete = false; // true solange Stand >= 100% (für Endlos-Konfetti)

async function tick(){
  const bar = document.getElementById("barFill");
  const over = document.getElementById("barOver");
  const pctEl = document.getElementById("pct");
  const lastEl = document.getElementById("last");
  const badge = document.getElementById("overBadge");

  try{
    const res = await fetch(API_URL, { cache: "no-store" });
    if(!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();

    const goal = Number(data.goal || 0);
    const netto = Number(data.netto_total || 0);

    const percent = goal > 0 ? (netto / goal) * 100 : 0;
    const laps = Math.floor(percent / 100);   // Anzahl voll erreichter Goals

    // Basis-Balken (0–100%) und Overcharge-Schicht (Überschuss > 100%)
    let baseWidth, overWidth;
    if (percent <= 100){
      baseWidth = Math.max(0, percent);
      overWidth = 0;
    }else{
      baseWidth = 100;
      // Überschuss innerhalb der aktuellen Runde (füllt sich erneut von links)
      let rem = (percent - 100) % 100;
      if (rem <= 0) rem = 100;   // exakte Goal-Grenze (z.B. 200%) -> volle Schicht
      overWidth = Math.min(rem, 100);
    }

    bar.style.width = baseWidth.toFixed(2) + "%";
    over.style.width = overWidth.toFixed(2) + "%";

    if (baseWidth >= 95) bar.classList.add("glow");
    else bar.classList.remove("glow");

    pctEl.textContent = percent.toFixed(1) + "%";

    // Badge bei Überschreitung (ab dem 2. Goal mit Multiplikator)
    if (percent > 100){
      badge.style.display = "";
      badge.textContent = laps >= 2 ? ("🔥 GOAL ×" + laps) : "🔥 ÜBER GOAL";
    }else{
      badge.style.display = "none";
    }

    // Donation erkannt: Betrag ist gestiegen -> Puls (nicht beim ersten Laden)
    if (prevNetto !== null && netto > prevNetto + 0.001){
      pulse();
    }

    // Großer Konfetti-Ausbruch bei jedem neu erreichten vollen Goal
    // (auch beim 1. Mal), aber nicht beim ersten Laden der Seite
    if (prevLaps !== null && laps > prevLaps){
      launchConfetti(180);
    }

    // Endlos-Feier: solange Goal erreicht/überschritten ist
    isComplete = percent >= 100;

    prevLaps = laps;
    prevNetto = netto;

    setState("Live • " + fmtTime());
    lastEl.textContent = SOURCE_LABEL;

  }catch(e){
    // Letzte Anzeige beibehalten, nur Offline-Status zeigen
    setState("Offline • API nicht erreichbar");
    lastEl.textContent = SOURCE_LABEL;
  }
}

setState("Verbinde…");
tick();
setInterval(tick, REFRESH_MS);

// Endlos-Konfetti: leichter Nachschub alle 2,5 s, solange Goal erreicht ist
setInterval(() => { if (isComplete) launchConfetti(70); }, 2500);

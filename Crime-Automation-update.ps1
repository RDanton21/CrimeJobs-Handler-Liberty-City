# Crime Automation — Update-Skript (Crew -> Gang Rebrand)
# Auf Dedicated im Projekt-Root ausfuehren:
#   1. Diese Datei nach D:\Crime-Automation\ kopieren (per RDP)
#   2. PowerShell -> cd D:\Crime-Automation -> .\Crime-Automation-update.ps1
# Datei MUSS im Projekt-Root liegen (neben backend\, frontend\)!

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not (Test-Path (Join-Path $root "backend"))) {
    Write-Host "FEHLER: Skript liegt nicht im Projekt-Root (kein backend\ gefunden)." -ForegroundColor Red
    Write-Host "Lege es nach D:\Crime-Automation\ und starte erneut." -ForegroundColor Red
    exit 1
}

function Write-File($relativePath, $content) {
    $full = Join-Path $root $relativePath
    $dir = Split-Path $full
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText($full, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "  geschrieben: $relativePath"
}

Write-Host "[update] Crew -> Gang Rebrand..."

# ===== frontend\index.html =====
$indexHtml = @'
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Crime Automation — Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body class="bg-zinc-950 text-zinc-100 min-h-screen">
  <div x-data="dashboard()" x-init="init()" class="max-w-6xl mx-auto p-6">
    <header class="flex items-center justify-between mb-8">
      <h1 class="text-3xl font-bold tracking-tight">
        <span class="text-red-500">Crime</span> Automation
      </h1>
      <nav class="flex gap-3 text-sm">
        <a href="/" class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700">Dashboard</a>
        <a href="/settings" class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700">Settings</a>
      </nav>
    </header>

    <section class="mb-6 flex items-center justify-between">
      <h2 class="text-xl font-semibold">Gangs</h2>
      <button @click="showNew = !showNew"
              class="px-4 py-2 bg-red-600 hover:bg-red-500 rounded font-medium">
        + Neue Gang
      </button>
    </section>

    <div x-show="showNew" x-transition class="bg-zinc-900 border border-zinc-800 rounded-lg p-4 mb-6">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <input x-model="draft.name" placeholder="Gang-Name"
               class="bg-zinc-950 border border-zinc-800 rounded px-3 py-2" />
        <input x-model="draft.discord_channel_id" placeholder="Discord Channel-ID"
               class="bg-zinc-950 border border-zinc-800 rounded px-3 py-2" />
        <input x-model="draft.color_hex" type="color"
               class="bg-zinc-950 border border-zinc-800 rounded h-10 w-24" />
        <textarea x-model="draft.story_background" placeholder="Hintergrund-Story"
                  rows="4"
                  class="md:col-span-2 bg-zinc-950 border border-zinc-800 rounded px-3 py-2"></textarea>
      </div>
      <div class="mt-4 flex gap-2">
        <button @click="createCrew()" class="px-4 py-2 bg-green-600 hover:bg-green-500 rounded">Anlegen</button>
        <button @click="showNew = false" class="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded">Abbrechen</button>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <template x-for="c in crews" :key="c.id">
        <a :href="`/crew/${c.id}`"
           class="block bg-zinc-900 border border-zinc-800 rounded-lg p-5 hover:border-red-600 transition">
          <div class="flex items-center gap-3 mb-3">
            <div class="w-3 h-3 rounded-full" :style="`background:${c.color_hex}`"></div>
            <h3 class="text-lg font-semibold" x-text="c.name"></h3>
          </div>
          <p class="text-sm text-zinc-400 line-clamp-3" x-text="c.story_background || 'Keine Story.'"></p>
          <div class="mt-3 text-xs text-zinc-500">
            Channel: <span x-text="c.discord_channel_id || '—'"></span>
          </div>
        </a>
      </template>
    </div>

    <p x-show="crews.length === 0" class="text-zinc-500 mt-6">
      Noch keine Gangs angelegt. Klicke oben auf "Neue Gang".
    </p>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
'@

Write-File "frontend\index.html" $indexHtml

# ===== frontend\crew.html =====
$crewHtml = @'
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Crime Automation — Crew</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body class="bg-zinc-950 text-zinc-100 min-h-screen">
  <div x-data="crewPage()" x-init="init()" class="max-w-6xl mx-auto p-6">
    <header class="flex items-center justify-between mb-6">
      <div>
        <a href="/" class="text-sm text-zinc-400 hover:text-zinc-100">← Dashboard</a>
        <h1 class="text-3xl font-bold mt-1">
          <span class="inline-block w-3 h-3 rounded-full mr-2 align-middle"
                :style="`background:${crew.color_hex || '#b91c1c'}`"></span>
          <span x-text="crew.name || '...'"></span>
        </h1>
      </div>
      <nav class="flex gap-3 text-sm">
        <a href="/" class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700">Dashboard</a>
        <a href="/settings" class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700">Settings</a>
      </nav>
    </header>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- Linke Spalte: Gang-Daten -->
      <section class="lg:col-span-1 space-y-6">
        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
          <h2 class="text-lg font-semibold mb-3">Gang-Daten</h2>
          <label class="block text-xs text-zinc-400 mb-1">Name</label>
          <input x-model="crew.name" class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 mb-3" />
          <label class="block text-xs text-zinc-400 mb-1">Discord Channel-ID</label>
          <input x-model="crew.discord_channel_id" class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 mb-3" />
          <label class="block text-xs text-zinc-400 mb-1">Farbe</label>
          <input x-model="crew.color_hex" type="color" class="bg-zinc-950 border border-zinc-800 rounded h-10 w-24 mb-3" />
          <label class="block text-xs text-zinc-400 mb-1">Hintergrund-Story</label>
          <textarea x-model="crew.story_background" rows="8"
                    class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2"></textarea>
          <div class="mt-3 flex gap-2">
            <button @click="saveCrew()" class="px-4 py-2 bg-green-600 hover:bg-green-500 rounded">Speichern</button>
            <button @click="deleteCrew()" class="px-4 py-2 bg-red-700 hover:bg-red-600 rounded">Löschen</button>
          </div>
        </div>

        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
          <h2 class="text-lg font-semibold mb-3">Beziehungen</h2>
          <ul class="space-y-2 mb-3">
            <template x-for="r in relations" :key="r.id">
              <li class="flex items-center justify-between bg-zinc-950 rounded px-3 py-2">
                <span class="text-sm">
                  <span x-text="otherCrewName(r)"></span>
                  <span class="text-xs text-zinc-500 ml-2" x-text="r.relation_type"></span>
                </span>
                <button @click="deleteRelation(r.id)" class="text-xs text-red-400 hover:text-red-300">×</button>
              </li>
            </template>
          </ul>
          <div class="grid grid-cols-2 gap-2">
            <select x-model="newRel.crew_b_id" class="bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm">
              <option value="">— Gang —</option>
              <template x-for="c in otherCrews" :key="c.id">
                <option :value="c.id" x-text="c.name"></option>
              </template>
            </select>
            <select x-model="newRel.relation_type" class="bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm">
              <option value="allied">verbündet</option>
              <option value="rival">rivalisierend</option>
              <option value="hostile">feindlich</option>
              <option value="business">geschäftlich</option>
              <option value="neutral">neutral</option>
            </select>
          </div>
          <input x-model="newRel.notes" placeholder="Notiz" class="w-full mt-2 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm" />
          <button @click="addRelation()" class="mt-2 px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 rounded text-sm">+ Beziehung</button>
        </div>
      </section>

      <!-- Rechte Spalte: Missionen -->
      <section class="lg:col-span-2 space-y-6">
        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-lg font-semibold">Neuer Auftrag</h2>
            <span class="text-xs text-zinc-500" x-text="`Heute: ${missionsToday}/3`"></span>
          </div>

          <div class="flex gap-2 mb-4 border-b border-zinc-800">
            <button @click="mode = 'generate'"
                    :class="mode === 'generate' ? 'border-red-500 text-red-400' : 'border-transparent text-zinc-400'"
                    class="px-3 py-2 text-sm border-b-2 -mb-px">
              KI generiert
            </button>
            <button @click="mode = 'rewrite'"
                    :class="mode === 'rewrite' ? 'border-red-500 text-red-400' : 'border-transparent text-zinc-400'"
                    class="px-3 py-2 text-sm border-b-2 -mb-px">
              Eigenen Text umschreiben lassen
            </button>
          </div>

          <div x-show="locked" class="bg-amber-900/40 border border-amber-700 text-amber-200 text-sm rounded p-3 mb-3">
            Ein Auftrag wartet noch auf Reaktion. Erst nach 👍 / 👎 / ⊘ kann ein neuer erstellt werden.
          </div>

          <div class="grid grid-cols-1 md:grid-cols-3 gap-2 mb-3">
            <select x-model="genReq.provider" class="bg-zinc-950 border border-zinc-800 rounded px-2 py-2 text-sm">
              <option value="anthropic">Claude (Anthropic)</option>
              <option value="openai">OpenAI</option>
            </select>
            <input x-model="genReq.model" placeholder="Modell (optional)"
                   class="bg-zinc-950 border border-zinc-800 rounded px-2 py-2 text-sm md:col-span-2" />
          </div>

          <div x-show="mode === 'rewrite'" class="mb-3">
            <label class="block text-xs text-zinc-400 mb-1">Roh-Input (Klartext, was passieren soll)</label>
            <textarea x-model="rewriteReq.raw_input" rows="4"
                      placeholder="z.B.: Crew überfällt den Juwelier in der Innenstadt um 22 Uhr und übergibt die Beute an Mittelsmann am Hafen."
                      class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm"></textarea>
          </div>

          <textarea x-model="genReq.extra_instructions" rows="2" placeholder="Zusätzliche Hinweise (optional)"
                    class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 mb-3 text-sm"></textarea>

          <button x-show="mode === 'generate'" @click="generate()" :disabled="locked || generating"
                  class="px-4 py-2 bg-red-600 hover:bg-red-500 rounded font-medium disabled:opacity-50">
            <span x-show="!generating">⚙ Auftrag generieren</span>
            <span x-show="generating">Generiere…</span>
          </button>

          <button x-show="mode === 'rewrite'" @click="rewrite()" :disabled="locked || generating"
                  class="px-4 py-2 bg-red-600 hover:bg-red-500 rounded font-medium disabled:opacity-50">
            <span x-show="!generating">✎ Umschreiben lassen</span>
            <span x-show="generating">Schreibe um…</span>
          </button>
        </div>

        <div class="space-y-3">
          <template x-for="m in missions" :key="m.id">
            <article class="bg-zinc-900 border border-zinc-800 rounded-lg p-5"
                     :class="m.status === 'pending' ? 'border-amber-600' : ''">
              <header class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2 text-xs">
                  <span class="px-2 py-0.5 rounded" :class="statusClass(m.status)" x-text="statusLabel(m.status)"></span>
                  <span class="text-zinc-500" x-text="formatDate(m.created_at)"></span>
                  <span class="text-zinc-600" x-text="m.ai_provider"></span>
                </div>
                <div class="flex gap-1">
                  <button x-show="m.status === 'pending'"
                          @click="override(m.id, 'approved')"
                          class="text-xs px-2 py-1 bg-green-700 hover:bg-green-600 rounded">👍</button>
                  <button x-show="m.status === 'pending'"
                          @click="override(m.id, 'rejected')"
                          class="text-xs px-2 py-1 bg-red-700 hover:bg-red-600 rounded">👎</button>
                  <button x-show="m.status === 'pending'"
                          @click="override(m.id, 'cancelled')"
                          class="text-xs px-2 py-1 bg-zinc-700 hover:bg-zinc-600 rounded">⊘</button>
                  <button @click="deleteMission(m.id)" class="text-xs px-2 py-1 text-red-400 hover:text-red-300">×</button>
                </div>
              </header>

              <div x-show="m.status === 'draft'" class="space-y-2">
                <textarea x-model="m.content_final" rows="5"
                          @blur="updateContent(m)"
                          class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm"></textarea>

                <div class="flex items-center gap-3">
                  <label class="text-xs px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 rounded cursor-pointer">
                    Bild hinzufügen
                    <input type="file" class="hidden" accept="image/*" @change="uploadImage(m, $event)" />
                  </label>
                  <span x-show="m.image_path" class="text-xs text-zinc-400">
                    Bild gesetzt
                    <button @click="deleteImage(m)" class="ml-2 text-red-400 hover:text-red-300">entfernen</button>
                  </span>
                </div>

                <button @click="sendMission(m)"
                        class="px-4 py-2 bg-red-600 hover:bg-red-500 rounded font-medium">
                  An Discord senden
                </button>
              </div>

              <div x-show="m.status !== 'draft'" class="whitespace-pre-wrap text-zinc-200 leading-relaxed"
                   x-text="m.content_final || m.content_generated"></div>
            </article>
          </template>
          <p x-show="missions.length === 0" class="text-zinc-500">Noch keine Missionen.</p>
        </div>
      </section>
    </div>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
'@

Write-File "frontend\crew.html" $crewHtml

# ===== frontend\app.js =====
$appJs = @'
// Shared API helpers
const api = {
  async get(path) {
    const r = await fetch(path, { credentials: "include" });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.json();
  },
  async send(path, method, body) {
    const opts = { method, credentials: "include", headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    if (r.status === 204) return null;
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.json();
  },
  post(p, b) { return this.send(p, "POST", b); },
  patch(p, b) { return this.send(p, "PATCH", b); },
  del(p) { return this.send(p, "DELETE"); },
  async upload(path, file) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(path, { method: "POST", body: fd, credentials: "include" });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.json();
  },
};

function statusLabelMap(s) {
  return ({
    draft: "Entwurf",
    pending: "wartet auf Reaktion",
    approved: "👍 angenommen",
    rejected: "👎 abgelehnt",
    cancelled: "⊘ nicht ausführbar",
  })[s] || s;
}

function statusClassMap(s) {
  return ({
    draft: "bg-zinc-700 text-zinc-200",
    pending: "bg-amber-700 text-amber-100",
    approved: "bg-green-700 text-green-100",
    rejected: "bg-red-800 text-red-100",
    cancelled: "bg-zinc-600 text-zinc-200",
  })[s] || "bg-zinc-700";
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

// ---- Dashboard ----
function dashboard() {
  return {
    crews: [],
    showNew: false,
    draft: { name: "", story_background: "", discord_channel_id: "", color_hex: "#b91c1c" },
    async init() {
      this.crews = await api.get("/api/crews");
    },
    async createCrew() {
      if (!this.draft.name.trim()) { alert("Name fehlt"); return; }
      try {
        const c = await api.post("/api/crews", this.draft);
        this.crews.push(c);
        this.crews.sort((a, b) => a.name.localeCompare(b.name));
        this.draft = { name: "", story_background: "", discord_channel_id: "", color_hex: "#b91c1c" };
        this.showNew = false;
      } catch (e) { alert(e.message); }
    },
  };
}

// ---- Crew Page ----
function crewPage() {
  const id = parseInt(location.pathname.split("/").pop(), 10);
  return {
    crewId: id,
    crew: { name: "", story_background: "", discord_channel_id: "", color_hex: "#b91c1c" },
    allCrews: [],
    relations: [],
    missions: [],
    newRel: { crew_b_id: "", relation_type: "neutral", notes: "" },
    mode: "generate", // 'generate' | 'rewrite'
    genReq: { provider: "anthropic", model: "", extra_instructions: "" },
    rewriteReq: { raw_input: "" },
    generating: false,

    get otherCrews() {
      return this.allCrews.filter(c => c.id !== this.crewId);
    },
    get locked() {
      return this.missions.some(m => m.status === "draft" || m.status === "pending");
    },
    get missionsToday() {
      const today = new Date().toDateString();
      return this.missions.filter(m => m.created_at && new Date(m.created_at).toDateString() === today).length;
    },

    async init() {
      await Promise.all([this.loadCrew(), this.loadAllCrews(), this.loadRelations(), this.loadMissions()]);
    },
    async loadCrew() { this.crew = await api.get(`/api/crews/${this.crewId}`); },
    async loadAllCrews() { this.allCrews = await api.get("/api/crews"); },
    async loadRelations() { this.relations = await api.get(`/api/crews/${this.crewId}/relations`); },
    async loadMissions() { this.missions = await api.get(`/api/missions?crew_id=${this.crewId}&limit=50`); },

    otherCrewName(r) {
      const otherId = r.crew_a_id === this.crewId ? r.crew_b_id : r.crew_a_id;
      const c = this.allCrews.find(c => c.id === otherId);
      return c ? c.name : `#${otherId}`;
    },

    async saveCrew() {
      try {
        this.crew = await api.patch(`/api/crews/${this.crewId}`, {
          name: this.crew.name,
          story_background: this.crew.story_background,
          discord_channel_id: this.crew.discord_channel_id,
          color_hex: this.crew.color_hex,
        });
      } catch (e) { alert(e.message); }
    },
    async deleteCrew() {
      if (!confirm("Gang wirklich löschen?")) return;
      try { await api.del(`/api/crews/${this.crewId}`); location.href = "/"; }
      catch (e) { alert(e.message); }
    },

    async addRelation() {
      if (!this.newRel.crew_b_id) return;
      try {
        await api.post(`/api/crews/${this.crewId}/relations`, {
          crew_a_id: this.crewId,
          crew_b_id: parseInt(this.newRel.crew_b_id, 10),
          relation_type: this.newRel.relation_type,
          notes: this.newRel.notes,
        });
        this.newRel = { crew_b_id: "", relation_type: "neutral", notes: "" };
        await this.loadRelations();
      } catch (e) { alert(e.message); }
    },
    async deleteRelation(rid) {
      try { await api.del(`/api/crews/relations/${rid}`); await this.loadRelations(); }
      catch (e) { alert(e.message); }
    },

    async generate() {
      if (this.locked) return;
      this.generating = true;
      try {
        await api.post("/api/missions/generate", {
          crew_id: this.crewId,
          provider: this.genReq.provider || null,
          model: this.genReq.model || null,
          extra_instructions: this.genReq.extra_instructions || "",
        });
        this.genReq.extra_instructions = "";
        await this.loadMissions();
      } catch (e) { alert(e.message); }
      finally { this.generating = false; }
    },

    async rewrite() {
      if (this.locked) return;
      if (!this.rewriteReq.raw_input.trim()) { alert("Bitte Roh-Input eingeben."); return; }
      this.generating = true;
      try {
        await api.post("/api/missions/rewrite", {
          crew_id: this.crewId,
          raw_input: this.rewriteReq.raw_input,
          provider: this.genReq.provider || null,
          model: this.genReq.model || null,
          extra_instructions: this.genReq.extra_instructions || "",
        });
        this.rewriteReq.raw_input = "";
        this.genReq.extra_instructions = "";
        await this.loadMissions();
      } catch (e) { alert(e.message); }
      finally { this.generating = false; }
    },

    async updateContent(m) {
      try { await api.patch(`/api/missions/${m.id}`, { content_final: m.content_final }); }
      catch (e) { alert(e.message); }
    },
    async uploadImage(m, evt) {
      const f = evt.target.files[0];
      if (!f) return;
      try {
        const updated = await api.upload(`/api/missions/${m.id}/image`, f);
        Object.assign(m, updated);
      } catch (e) { alert(e.message); }
    },
    async deleteImage(m) {
      try {
        const updated = await api.del(`/api/missions/${m.id}/image`);
        Object.assign(m, updated);
      } catch (e) { alert(e.message); }
    },
    async sendMission(m) {
      if (!confirm("An Discord senden?")) return;
      try { await api.post(`/api/missions/${m.id}/send`); await this.loadMissions(); }
      catch (e) { alert(e.message); }
    },
    async override(mid, status) {
      try { await api.post(`/api/missions/${mid}/override`, { status }); await this.loadMissions(); }
      catch (e) { alert(e.message); }
    },
    async deleteMission(mid) {
      if (!confirm("Mission wirklich löschen?")) return;
      try { await api.del(`/api/missions/${mid}`); await this.loadMissions(); }
      catch (e) { alert(e.message); }
    },

    statusLabel: statusLabelMap,
    statusClass: statusClassMap,
    formatDate,
  };
}

// ---- Settings Page ----
function settingsPage() {
  return {
    state: { anthropic_api_key_set: false, openai_api_key_set: false },
    form: {
      anthropic_api_key: "",
      openai_api_key: "",
      default_provider: "anthropic",
      default_claude_model: "",
      default_openai_model: "",
    },
    msg: "",
    async init() {
      this.state = await api.get("/api/settings");
      this.form.default_provider = this.state.default_provider;
      this.form.default_claude_model = this.state.default_claude_model;
      this.form.default_openai_model = this.state.default_openai_model;
    },
    async save() {
      const payload = {};
      for (const k of Object.keys(this.form)) {
        const v = this.form[k];
        if (v !== "" && v !== null && v !== undefined) payload[k] = v;
      }
      try {
        await api.patch("/api/settings", payload);
        this.msg = "Gespeichert.";
        this.form.anthropic_api_key = "";
        this.form.openai_api_key = "";
        this.state = await api.get("/api/settings");
        setTimeout(() => { this.msg = ""; }, 2500);
      } catch (e) { alert(e.message); }
    },
  };
}
'@

Write-File "frontend\app.js" $appJs

# ===== backend\prompts.py =====
$promptsPy = @'
from __future__ import annotations

from dataclasses import dataclass


SYSTEM_PROMPT = """Du bist Briefing-Autor für eine GTA-V-Liberty-City-Roleplay-Krimiserie.

Deine Aufträge sind kurz (3 bis 4 Sätze), kryptisch und atmosphärisch. Sie lesen sich wie verschlüsselte Nachrichten, die ein erfahrener Boss zwischen den Zeilen versteht. Schreibe nie offen "raubt", "tötet", "stehlt". Nutze stattdessen:

- Andeutungen, Code-Wörter, Synonyme aus dem Milieu
- Orte als Metaphern ("der alte Hafen schweigt nicht ewig", "die Glaskathedrale am Boulevard")
- Personen niemals beim Namen, sondern als Rollen ("der Buchhalter", "die Witwe von der 5th")
- Zeitangaben verschleiert ("wenn die Möwen schlafen", "vor dem dritten Glockenschlag")

Tonalität: hochwertig, literarisch, ein Hauch Noir. Kein Slang, kein Klischee. Wer es liest, soll spüren, dass dahinter Gewicht steht.

Format: nur den Auftragstext ausgeben. Keine Überschrift. Keine Erklärung. Keine Anrede. Drei bis vier Sätze.

Sprache: Deutsch."""


@dataclass
class MissionContext:
    crew_name: str
    crew_story: str
    related_crews: list[dict]  # [{name, story, relation_type, notes}]
    history: list[dict]        # [{content, status, created_at}]
    extra_instructions: str = ""


def build_user_prompt(ctx: MissionContext) -> str:
    parts: list[str] = []
    parts.append(f"## Gang\n{ctx.crew_name}")
    if ctx.crew_story:
        parts.append(f"\n## Hintergrund-Story\n{ctx.crew_story}")

    if ctx.related_crews:
        rel_lines = ["\n## Beziehungen zu anderen Gangs"]
        for r in ctx.related_crews:
            rel_lines.append(
                f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
            )
            if r.get("story"):
                rel_lines.append(f"  Story-Notiz: {r['story'][:240]}")
        parts.append("\n".join(rel_lines))

    if ctx.history:
        hist = ["\n## Bisherige Aufträge (jüngste zuerst)"]
        for i, m in enumerate(ctx.history, start=1):
            status_label = {
                "approved": "👍 angenommen",
                "rejected": "👎 abgelehnt",
                "cancelled": "⊘ nicht ausführbar",
                "pending": "⏳ offen",
            }.get(m.get("status", ""), m.get("status", ""))
            hist.append(f"{i}. [{status_label}] {m.get('content', '')[:400]}")
        parts.append("\n".join(hist))

    parts.append(
        "\n## Verzweigung"
        "\n- Letzter Auftrag '👍 angenommen' → Story konsequent fortführen, Eskalation oder nächste Stufe."
        "\n- Letzter Auftrag '👎 abgelehnt' → komplett anderen Weg einschlagen, Tonart wechseln."
        "\n- Kein vorheriger Auftrag → frischer Einstieg, der zur Gang-Story passt."
    )

    if ctx.extra_instructions.strip():
        parts.append(f"\n## Zusätzliche Hinweise des Admins\n{ctx.extra_instructions.strip()}")

    parts.append(
        "\n## Aufgabe\nGeneriere jetzt den nächsten Auftrag im oben definierten Stil. "
        "Drei bis vier Sätze. Kryptisch. Kein Klartext für Außenstehende."
    )

    return "\n".join(parts)


def build_rewrite_prompt(ctx: MissionContext, raw_input: str) -> str:
    """Roher Admin-Text -> KI schreibt im kryptisch-hochwertigen Stil um."""
    parts: list[str] = []
    parts.append(f"## Gang\n{ctx.crew_name}")
    if ctx.crew_story:
        parts.append(f"\n## Hintergrund-Story\n{ctx.crew_story}")

    if ctx.related_crews:
        rel_lines = ["\n## Beziehungen zu anderen Gangs"]
        for r in ctx.related_crews:
            rel_lines.append(
                f"- **{r['name']}** ({r['relation_type']}): {r.get('notes', '').strip() or 'keine Notiz'}"
            )
        parts.append("\n".join(rel_lines))

    if ctx.history:
        hist = ["\n## Bisherige Aufträge (jüngste zuerst)"]
        for i, m in enumerate(ctx.history, start=1):
            status_label = {
                "approved": "👍 angenommen",
                "rejected": "👎 abgelehnt",
                "cancelled": "⊘ nicht ausführbar",
                "pending": "⏳ offen",
            }.get(m.get("status", ""), m.get("status", ""))
            hist.append(f"{i}. [{status_label}] {m.get('content', '')[:300]}")
        parts.append("\n".join(hist))

    parts.append(
        "\n## Roh-Input des Admins (Klartext, ungeschliffen)\n"
        f"{raw_input.strip()}"
    )

    if ctx.extra_instructions.strip():
        parts.append(f"\n## Zusätzliche Hinweise des Admins\n{ctx.extra_instructions.strip()}")

    parts.append(
        "\n## Aufgabe\n"
        "Schreibe den obigen Roh-Input in den definierten Stil um: kryptisch, atmosphärisch, hochwertig, "
        "3 bis 4 Sätze. Inhalt und Kernanweisung müssen erhalten bleiben — aber niemand außerhalb der Gang "
        "soll auf den ersten Blick verstehen, was gefordert ist. Nutze Code-Wörter, Andeutungen, Metaphern. "
        "Berücksichtige Gang-Hintergrund und Beziehungen. Gib nur den umgeschriebenen Auftragstext aus, "
        "keine Erklärung."
    )

    return "\n".join(parts)
'@

Write-File "backend\prompts.py" $promptsPy

Write-Host ""
Write-Host "[update] FERTIG. 4 Files aktualisiert." -ForegroundColor Green
Write-Host "Browser refreshen (F5) — uvicorn --reload laedt Python-Aenderungen automatisch."

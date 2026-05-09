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
    approved: "👍 Erledigt",
    rejected: "👎 Fehlgeschlagen",
    cancelled: "❌ nicht ausführbar",
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
    showArchive: false,

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
      // Auto-Refresh Missionen alle 5 Sek (fuer Discord-Reaktions-Updates)
      setInterval(() => { this.loadMissions().catch(() => {}); }, 5000);
    },
    async loadCrew() { this.crew = await api.get(`/api/crews/${this.crewId}`); },
    async loadAllCrews() { this.allCrews = await api.get("/api/crews"); },
    async loadRelations() { this.relations = await api.get(`/api/crews/${this.crewId}/relations`); },
    async loadMissions() {
      const arch = this.showArchive ? "&archived=true" : "";
      this.missions = await api.get(`/api/missions?crew_id=${this.crewId}&limit=50${arch}`);
    },
    async toggleArchive() {
      this.showArchive = !this.showArchive;
      await this.loadMissions();
    },

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
    async archiveMission(mid) {
      if (!confirm("Mission ins Archiv verschieben? Discord-Nachricht wird gelöscht.")) return;
      try { await api.del(`/api/missions/${mid}`); await this.loadMissions(); }
      catch (e) { alert(e.message); }
    },
    async restoreMission(mid) {
      try { await api.post(`/api/missions/${mid}/restore`); await this.loadMissions(); }
      catch (e) { alert(e.message); }
    },
    async purgeMission(mid) {
      if (!confirm("Endgültig löschen? Nicht wiederherstellbar.")) return;
      try { await api.del(`/api/missions/${mid}/purge`); await this.loadMissions(); }
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

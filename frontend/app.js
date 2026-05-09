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

function cardBorderClass(s) {
  return ({
    approved: "border-green-500",
    rejected: "border-red-500",
    cancelled: "border-yellow-500",
  })[s] || "border-zinc-800";
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
    draft: { name: "", story_background: "", discord_channel_id: "", info_channel_id: "", color_hex: "#b91c1c" },
    async init() {
      await this.loadCrews();
      setInterval(() => { this.loadCrews().catch(() => {}); }, 5000);
    },
    async loadCrews() {
      this.crews = await api.get("/api/crews");
    },
    async createCrew() {
      if (!this.draft.name.trim()) { alert("Name fehlt"); return; }
      try {
        const c = await api.post("/api/crews", this.draft);
        this.crews.push(c);
        this.crews.sort((a, b) => a.name.localeCompare(b.name));
        this.draft = { name: "", story_background: "", discord_channel_id: "", info_channel_id: "", color_hex: "#b91c1c" };
        this.showNew = false;
      } catch (e) { alert(e.message); }
    },
    statusLabel: statusLabelMap,
    statusClass: statusClassMap,
    cardBorder: cardBorderClass,
    formatDate,
  };
}

// ---- Crew Page ----
function crewPage() {
  const id = parseInt(location.pathname.split("/").pop(), 10);
  return {
    crewId: id,
    crew: { name: "", story_background: "", discord_channel_id: "", info_channel_id: "", color_hex: "#b91c1c" },
    allCrews: [],
    relations: [],
    missions: [],
    newRel: { crew_b_id: "", relation_type: "neutral", notes: "" },
    mode: "generate", // 'generate' | 'rewrite'
    genReq: { provider: "anthropic", model: "", extra_instructions: "" },
    rewriteReq: { raw_input: "" },
    pendingImage: null,
    generating: false,
    showArchive: false,
    bossInfoByMission: {},

    get otherCrews() {
      return this.allCrews.filter(c => c.id !== this.crewId);
    },
    get missionsToday() {
      const today = new Date().toDateString();
      return this.missions.filter(m => m.created_at && new Date(m.created_at).toDateString() === today).length;
    },

    async init() {
      await Promise.all([this.loadCrew(), this.loadAllCrews(), this.loadRelations(), this.loadMissions()]);
      await this.loadBossInfo();
      // Auto-Refresh alle 5 Sek (fuer Discord-Reaktions-Updates + Boss-Texte)
      setInterval(() => {
        this.loadMissions().catch(() => {});
        this.loadBossInfo().catch(() => {});
      }, 5000);
    },
    async loadCrew() { this.crew = await api.get(`/api/crews/${this.crewId}`); },
    async loadAllCrews() { this.allCrews = await api.get("/api/crews"); },
    async loadRelations() { this.relations = await api.get(`/api/crews/${this.crewId}/relations`); },
    async loadMissions() {
      const arch = this.showArchive ? "&archived=true" : "";
      this.missions = await api.get(`/api/missions?crew_id=${this.crewId}&limit=50${arch}`);
    },
    async loadBossInfo() {
      if (!this.crew || !this.crew.info_channel_id) return;
      try {
        const data = await api.get(`/api/crews/${this.crewId}/boss_info`);
        const map = {};
        for (const entry of data) map[entry.mission_id] = entry.messages || [];
        this.bossInfoByMission = map;
      } catch (e) {
        // Bot evtl. offline oder Permission-Issue — silent
      }
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
          info_channel_id: this.crew.info_channel_id,
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

    setPendingImage(evt) {
      this.pendingImage = evt.target.files[0] || null;
    },
    clearPendingImage() {
      this.pendingImage = null;
      if (this.$refs.genImageInput) this.$refs.genImageInput.value = "";
    },
    async _attachPendingImage(missionId) {
      if (!this.pendingImage || !missionId) return;
      try { await api.upload(`/api/missions/${missionId}/image`, this.pendingImage); }
      catch (e) { alert("Bild-Upload fehlgeschlagen: " + e.message); }
    },

    async generate() {
      this.generating = true;
      try {
        const m = await api.post("/api/missions/generate", {
          crew_id: this.crewId,
          provider: this.genReq.provider || null,
          model: this.genReq.model || null,
          extra_instructions: this.genReq.extra_instructions || "",
        });
        await this._attachPendingImage(m && m.id);
        this.genReq.extra_instructions = "";
        this.clearPendingImage();
        await this.loadMissions();
      } catch (e) { alert(e.message); }
      finally { this.generating = false; }
    },

    async rewrite() {
      if (!this.rewriteReq.raw_input.trim()) { alert("Bitte Roh-Input eingeben."); return; }
      this.generating = true;
      try {
        const m = await api.post("/api/missions/rewrite", {
          crew_id: this.crewId,
          raw_input: this.rewriteReq.raw_input,
          provider: this.genReq.provider || null,
          model: this.genReq.model || null,
          extra_instructions: this.genReq.extra_instructions || "",
        });
        await this._attachPendingImage(m && m.id);
        this.rewriteReq.raw_input = "";
        this.genReq.extra_instructions = "";
        this.clearPendingImage();
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

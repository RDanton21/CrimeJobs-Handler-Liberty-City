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

const DISTRICTS = ["Algonquin", "Bohan", "Broker", "Colony Island", "Dukes"];

function _coerceUtc(iso) {
  // Backend liefert UTC-Zeitstempel ohne tz-Suffix. JS würde das als lokal
  // interpretieren → Anzeige 2h zu früh (CEST). Fix: Z anhängen wenn keine tz da.
  if (!iso) return iso;
  if (/[zZ]$/.test(iso)) return iso;
  if (/[+-]\d\d:?\d\d$/.test(iso)) return iso;
  return iso + "Z";
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(_coerceUtc(iso));
  return d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

function relativeTime(iso) {
  if (!iso) return "";
  const ms = new Date(_coerceUtc(iso)) - new Date();
  if (ms <= 0) return "abgelaufen";
  const min = Math.round(ms / 60000);
  if (min < 60) return `noch ${min} Min`;
  const hrs = Math.round(min / 60);
  if (hrs < 24) return `noch ${hrs} Std`;
  const days = Math.round(hrs / 24);
  return `noch ${days} Tage`;
}

// ---- Dashboard ----
function dashboard() {
  return {
    crews: [],
    stats: {},
    statsFilter: { crew_id: "", range: "all" },
    districtFilter: "",
    statusFilter: "",
    DISTRICTS,
    showNew: false,
    draft: { name: "", story_background: "", crime_business: "", crime_business_channel_id: "", discord_channel_id: "", info_channel_id: "", district: "", color_hex: "#b91c1c" },
    notifications: {},
    seenAt: JSON.parse(localStorage.getItem("crewSeenAt") || "{}"),
    archivingAll: false,
    searchQuery: "",
    showBulk: false,
    bulkScope: "all",
    bulkDistrict: "",
    bulkSelectedCrews: [],
    bulkMode: "manual",
    bulkProvider: "anthropic",
    bulkContent: "",
    bulkDeadlineValue: "",
    bulkDeadlineUnit: "min",
    bulkSending: false,
    bulkBusyLabel: "",
    bulkResult: "",
    bulkResultIsError: false,
    bulkPhase: "input",  // 'input' | 'preview'
    bulkPreviewText: "",

    get bulkTargets() {
      let list = [];
      if (this.bulkScope === "all") list = this.crews;
      else if (this.bulkScope === "district") {
        list = this.bulkDistrict ? this.crews.filter(c => c.district === this.bulkDistrict) : [];
      }
      else if (this.bulkScope === "manual") {
        const ids = this.bulkSelectedCrews.map(s => parseInt(s, 10));
        list = this.crews.filter(c => ids.includes(c.id));
      }
      // Nur Crews mit Discord-Channel — Firmen ohne Channel werden uebersprungen
      return list.filter(c => (c.discord_channel_id || "").trim());
    },

    // Crews mit gesetzter Channel-ID — fuer manual-Auswahl-Liste
    get sendableCrews() {
      return this.crews.filter(c => (c.discord_channel_id || "").trim());
    },

    // Anzahl Crews, die wegen fehlender Channel-ID aus dem aktuellen Scope
    // ausgeschlossen wurden (nur fuer Anzeige in Phase 1)
    get bulkExcludedCount() {
      let list = [];
      if (this.bulkScope === "all") list = this.crews;
      else if (this.bulkScope === "district") {
        list = this.bulkDistrict ? this.crews.filter(c => c.district === this.bulkDistrict) : [];
      }
      else return 0;
      return list.filter(c => !(c.discord_channel_id || "").trim()).length;
    },
    _bulkDeadlineMinutes() {
      const n = parseInt(this.bulkDeadlineValue, 10);
      if (!n || n <= 0) return null;
      if (this.bulkDeadlineUnit === "hour") return n * 60;
      if (this.bulkDeadlineUnit === "day") return n * 60 * 24;
      return n;
    },
    async sendBulk() {
      const text = (this.bulkContent || "").trim();
      const targets = this.bulkTargets;
      if (this.bulkMode === "manual" && !text) { alert("Bitte Auftragstext eingeben."); return; }
      if (this.bulkMode === "ai_rewrite" && !text) { alert("Bitte Roh-Input eingeben."); return; }
      if (targets.length === 0) { alert("Keine Empfänger ausgewählt."); return; }

      this.bulkResult = "";
      this.bulkResultIsError = false;

      if (this.bulkMode === "manual") {
        if (!confirm(`Auftrag an ${targets.length} Gang(s) senden?`)) return;
        this.bulkPreviewText = text;
        await this._bulkDispatch(targets);
        return;
      }

      // AI-Modi: einmalig generieren mit erster Crew als Story-Kontext, dann Vorschau
      this.bulkSending = true;
      this.bulkBusyLabel = "Generiere…";
      try {
        const ctxCrew = targets[0];
        let m;
        if (this.bulkMode === "ai_rewrite") {
          m = await api.post("/api/missions/rewrite", {
            crew_id: ctxCrew.id,
            raw_input: text,
            provider: this.bulkProvider || null,
          });
        } else {
          m = await api.post("/api/missions/generate", {
            crew_id: ctxCrew.id,
            extra_instructions: text,
            provider: this.bulkProvider || null,
          });
        }
        this.bulkPreviewText = m.content_final || m.content_generated || "";
        // Draft purgen — beim Confirm wird via /manual frisch versendet
        try { await api.del(`/api/missions/${m.id}/purge`); } catch (e) {}
        this.bulkPhase = "preview";
      } catch (e) {
        alert(`KI-Fehler: ${e.message}`);
      } finally {
        this.bulkSending = false;
        this.bulkBusyLabel = "";
      }
    },

    async bulkConfirmSend() {
      const targets = this.bulkTargets;
      const text = (this.bulkPreviewText || "").trim();
      if (!text || targets.length === 0) return;
      await this._bulkDispatch(targets);
    },

    bulkDiscardPreview() {
      this.bulkPreviewText = "";
      this.bulkPhase = "input";
    },

    async _bulkDispatch(targets) {
      const text = (this.bulkPreviewText || "").trim();
      if (!text) return;
      const fixedTargets = [...targets];
      this.bulkSending = true;
      this.bulkBusyLabel = `Sende ${fixedTargets.length} parallel…`;
      const minutes = this._bulkDeadlineMinutes();
      try {
        const results = await api.post("/api/missions/bulk_send", {
          crew_ids: fixedTargets.map(c => c.id),
          content: text,
          deadline_minutes: minutes,
        });
        const ok = results.filter(r => r.ok).length;
        const failed = results.filter(r => !r.ok);
        let resultText = `Gesendet: ${ok}/${fixedTargets.length}`;
        if (failed.length) {
          resultText += "\nFehler:\n" + failed.map(r => `${r.name}: ${r.error}`).join("\n");
        }
        this.bulkResult = resultText;
        this.bulkResultIsError = failed.length > 0;
        if (failed.length === 0) {
          this.bulkContent = "";
          this.bulkPreviewText = "";
          this.bulkDeadlineValue = "";
          this.bulkPhase = "input";
        }
      } catch (e) {
        this.bulkResult = `Bulk-Send fehlgeschlagen: ${e.message}`;
        this.bulkResultIsError = true;
      } finally {
        this.bulkSending = false;
        this.bulkBusyLabel = "";
      }
    },

    get filteredCrews() {
      let list = this.crews;
      if (this.districtFilter) list = list.filter(c => c.district === this.districtFilter);
      if (this.statusFilter) list = list.filter(c => c.last_mission_status === this.statusFilter);
      if (this.searchQuery && this.searchQuery.trim()) {
        const q = this.searchQuery.trim().toLowerCase();
        list = list.filter(c => (c.name || "").toLowerCase().includes(q));
      }
      return list;
    },
    get groupedCrews() {
      // Gruppiert die filteredCrews nach Stadtteil (Algonquin/Bohan/...).
      // Innerhalb jeder Gruppe alphabetisch nach Name. Crews ohne Stadtteil ans Ende.
      const groups = {};
      for (const c of this.filteredCrews) {
        const key = c.district || "— ohne Stadtteil —";
        if (!groups[key]) groups[key] = [];
        groups[key].push(c);
      }
      const sortedKeys = Object.keys(groups).sort((a, b) => {
        if (a === "— ohne Stadtteil —") return 1;
        if (b === "— ohne Stadtteil —") return -1;
        return a.localeCompare(b, "de");
      });
      return sortedKeys.map(district => ({
        district,
        crews: groups[district].sort((a, b) =>
          (a.name || "").localeCompare(b.name || "", "de")
        ),
      }));
    },
    toggleStatusFilter(s) {
      this.statusFilter = (this.statusFilter === s) ? "" : s;
    },
    async init() {
      await this.loadCrews();
      await this.loadStats();
      await this.loadNotifications();
      setInterval(() => {
        this.loadCrews().catch(() => {});
        this.loadStats().catch(() => {});
        this.loadNotifications().catch(() => {});
      }, 5000);
    },
    async loadCrews() {
      this.crews = await api.get("/api/crews");
    },
    async archiveAllActive() {
      let missions;
      try { missions = await api.get("/api/missions?archived=false&limit=500"); }
      catch (e) { alert("Konnte aktive Aufträge nicht laden: " + e.message); return; }
      if (!missions || missions.length === 0) {
        alert("Keine aktiven Aufträge zum Archivieren.");
        return;
      }
      if (!confirm(`${missions.length} aktive(r) Auftrag(e) archivieren? Discord-Posts werden gelöscht, Boss-Feedback wird snapshottet.`)) return;
      if (!confirm("Wirklich? Diese Aktion betrifft alle Crews gleichzeitig.")) return;

      this.archivingAll = true;
      let ok = 0, fail = 0;
      try {
        for (const m of missions) {
          try { await api.del(`/api/missions/${m.id}`); ok++; }
          catch (e) { fail++; }
        }
        alert(`Archiviert: ${ok}` + (fail > 0 ? `, Fehler: ${fail}` : ""));
        await Promise.all([this.loadCrews(), this.loadStats(), this.loadNotifications()]);
      } finally {
        this.archivingAll = false;
      }
    },
    async loadNotifications() {
      try {
        const data = await api.get("/api/crews/notifications");
        const map = {};
        for (const n of data) map[n.crew_id] = n.latest_boss_message_at;
        this.notifications = map;
      } catch (e) { /* Bot offline -> silent */ }
    },
    hasUnread(c) {
      const latest = this.notifications[c.id];
      if (!latest) return false;
      const seen = this.seenAt[c.id];
      if (!seen) return true;
      return new Date(latest).getTime() > new Date(seen).getTime();
    },
    markCrewSeen(c) {
      const latest = this.notifications[c.id];
      if (!latest) return;
      this.seenAt = { ...this.seenAt, [c.id]: latest };
      localStorage.setItem("crewSeenAt", JSON.stringify(this.seenAt));
    },
    _rangeSince(range) {
      const now = new Date();
      if (range === "today") {
        const d = new Date(now); d.setHours(0, 0, 0, 0); return d.toISOString();
      }
      if (range === "week") {
        const d = new Date(now); d.setDate(d.getDate() - 7); return d.toISOString();
      }
      if (range === "month") {
        const d = new Date(now); d.setDate(d.getDate() - 30); return d.toISOString();
      }
      return null;
    },
    async loadStats() {
      const params = new URLSearchParams();
      if (this.statsFilter.crew_id) params.set("crew_id", this.statsFilter.crew_id);
      if (this.districtFilter) params.set("district", this.districtFilter);
      const since = this._rangeSince(this.statsFilter.range);
      if (since) params.set("since", since);
      const qs = params.toString() ? "?" + params.toString() : "";
      this.stats = await api.get(`/api/missions/stats${qs}`);
    },
    async createCrew() {
      if (!this.draft.name.trim()) { alert("Name fehlt"); return; }
      try {
        const c = await api.post("/api/crews", this.draft);
        this.crews.push(c);
        this.crews.sort((a, b) => a.name.localeCompare(b.name));
        this.draft = { name: "", story_background: "", crime_business: "", crime_business_channel_id: "", discord_channel_id: "", info_channel_id: "", district: "", color_hex: "#b91c1c" };
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
    crew: { name: "", story_background: "", crime_business: "", crime_business_channel_id: "", discord_channel_id: "", info_channel_id: "", district: "", color_hex: "#b91c1c" },
    DISTRICTS,
    allCrews: [],
    relations: [],
    missions: [],
    newRel: { crew_b_id: "", relation_type: "neutral", notes: "" },
    mode: "generate", // 'generate' | 'rewrite'
    genReq: { provider: "anthropic", model: "", extra_instructions: "", append_text: "", deadline_value: "", deadline_unit: "min", scheduled_send_at: "" },
    rewriteReq: { raw_input: "" },
    pendingImage: null,
    generating: false,
    showArchive: false,
    bossInfoByMission: {},
    rewritingMissionId: null,
    editingMissionId: null,
    // Crime-Business-Workflow: idle -> preview -> (post | discard)
    cbPhase: "idle",     // 'idle' | 'preview'
    cbBusy: false,        // generiert/sendet gerade?
    cbPreviewText: "",    // editierbarer Vorschau-Text
    cbProvider: "",       // welcher AI-Provider hat generiert (Info-Anzeige)
    cbMessage: "",
    cbIsError: false,

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
      const fresh = await api.get(`/api/missions?crew_id=${this.crewId}&limit=50${arch}`);
      // Bei DRAFT-Missions: lokalen content_final behalten (User könnte gerade
      // editieren). Andere Felder (status, sent_at, etc.) werden voll aktualisiert.
      // Sobald Mission gesendet wird (Status != draft), kommt der DB-Wert durch.
      this.missions = fresh.map(f => {
        if (f.status === "draft") {
          const oldM = (this.missions || []).find(mm => mm.id === f.id);
          if (oldM && oldM.content_final !== undefined) {
            return { ...f, content_final: oldM.content_final };
          }
        }
        return f;
      });
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
    bossInfoFor(m) {
      if (m.archived_at && m.archived_boss_info) {
        try {
          const arr = JSON.parse(m.archived_boss_info);
          return Array.isArray(arr) ? arr : [];
        } catch (e) { return []; }
      }
      return this.bossInfoByMission[m.id] || [];
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
          crime_business: this.crew.crime_business || "",
          crime_business_channel_id: this.crew.crime_business_channel_id || "",
          discord_channel_id: this.crew.discord_channel_id,
          info_channel_id: this.crew.info_channel_id,
          district: this.crew.district || "",
          color_hex: this.crew.color_hex,
        });
      } catch (e) { alert(e.message); }
    },
    async deleteCrew() {
      if (!confirm("Gang wirklich löschen?")) return;
      try { await api.del(`/api/crews/${this.crewId}`); location.href = "/"; }
      catch (e) { alert(e.message); }
    },

    // Schritt 1 — KI-Vorschau generieren. Wenn regenerate=true, ueberschreibt
    // den aktuellen Preview-Text mit einer neuen KI-Generierung.
    async previewCrimeBusiness(regenerate = false) {
      this.cbMessage = "";
      this.cbIsError = false;
      const cb = (this.crew.crime_business || "").trim();
      const ch = (this.crew.crime_business_channel_id || "").trim();
      if (!cb) { this.cbMessage = "Bitte erst Crime-Business eintragen und speichern."; this.cbIsError = true; return; }
      if (!ch) { this.cbMessage = "Bitte erst Crime-Business-Channel-ID eintragen und speichern."; this.cbIsError = true; return; }
      this.cbBusy = true;
      try {
        const res = await api.post(`/api/crews/${this.crewId}/crime-business/preview`, {});
        this.cbPreviewText = res.text || "";
        this.cbProvider = res.ai_provider || "";
        this.cbPhase = "preview";
        this.cbMessage = regenerate
          ? `✓ Neu generiert (${res.char_count} Zeichen).`
          : `✓ Vorschau bereit (${res.char_count} Zeichen). Du kannst editieren, bevor du sendest.`;
        this.cbIsError = false;
      } catch (e) {
        this.cbMessage = "Fehler bei Generierung: " + (e.message || e);
        this.cbIsError = true;
      } finally {
        this.cbBusy = false;
      }
    },

    // Schritt 2 — den (ggf. editierten) Preview-Text an Discord posten.
    async postCrimeBusiness() {
      this.cbMessage = "";
      this.cbIsError = false;
      const content = (this.cbPreviewText || "").trim();
      if (!content) {
        this.cbMessage = "Vorschau-Text ist leer.";
        this.cbIsError = true;
        return;
      }
      if (content.length > 1990) {
        this.cbMessage = `Text zu lang (${content.length}/1990 Zeichen). Bitte kürzen.`;
        this.cbIsError = true;
        return;
      }
      this.cbBusy = true;
      try {
        const res = await api.post(`/api/crews/${this.crewId}/crime-business/post`, { content });
        this.cbMessage = `✓ Gesendet (${res.char_count} Zeichen, Message-ID ${res.discord_message_id}).`;
        this.cbIsError = false;
        // Zuruecksetzen
        this.cbPhase = "idle";
        this.cbPreviewText = "";
        this.cbProvider = "";
      } catch (e) {
        this.cbMessage = "Fehler beim Senden: " + (e.message || e);
        this.cbIsError = true;
      } finally {
        this.cbBusy = false;
      }
    },

    discardCrimeBusinessPreview() {
      this.cbPhase = "idle";
      this.cbPreviewText = "";
      this.cbProvider = "";
      this.cbMessage = "Vorschau verworfen.";
      this.cbIsError = false;
    },

    async addRelation() {
      if (!this.newRel.crew_b_id) {
        alert("Bitte erst eine Gang aus dem Dropdown auswählen.");
        return;
      }
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

    _deadlineMinutes() {
      const n = parseInt(this.genReq.deadline_value, 10);
      if (!n || n <= 0) return null;
      if (this.genReq.deadline_unit === "hour") return n * 60;
      if (this.genReq.deadline_unit === "day") return n * 60 * 24;
      return n;
    },
    _scheduledSendIso() {
      // datetime-local liefert lokale Zeit ohne tz → in UTC ISO konvertieren
      const v = (this.genReq.scheduled_send_at || "").trim();
      if (!v) return null;
      const d = new Date(v);
      if (isNaN(d.getTime())) return null;
      return d.toISOString();
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
          append_text: this.genReq.append_text || "",
          deadline_minutes: this._deadlineMinutes(),
          scheduled_send_at: this._scheduledSendIso(),
        });
        await this._attachPendingImage(m && m.id);
        this.genReq.extra_instructions = "";
        this.genReq.append_text = "";
        this.genReq.deadline_value = "";
        this.genReq.scheduled_send_at = "";
        this.clearPendingImage();
        await this.loadMissions();
      } catch (e) { alert(e.message); }
      finally { this.generating = false; }
    },

    async sendManual() {
      const text = (this.genReq.append_text || "").trim();
      if (!text) { alert("Bitte Text in den Zusatzinfos eingeben."); return; }
      const scheduled = this._scheduledSendIso();
      const confirmMsg = scheduled
        ? `Diesen Text geplant senden (zum gewählten Zeitpunkt)?`
        : "Diesen Text direkt (ohne KI) an Discord senden?";
      if (!confirm(confirmMsg)) return;
      this.generating = true;
      try {
        const m = await api.post("/api/missions/manual", {
          crew_id: this.crewId,
          content: text,
          deadline_minutes: this._deadlineMinutes(),
          scheduled_send_at: scheduled,
        });
        await this._attachPendingImage(m && m.id);
        if (!scheduled) {
          await api.post(`/api/missions/${m.id}/send`);
        }
        this.genReq.append_text = "";
        this.genReq.deadline_value = "";
        this.genReq.scheduled_send_at = "";
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
          append_text: this.genReq.append_text || "",
          deadline_minutes: this._deadlineMinutes(),
          scheduled_send_at: this._scheduledSendIso(),
        });
        await this._attachPendingImage(m && m.id);
        this.rewriteReq.raw_input = "";
        this.genReq.extra_instructions = "";
        this.genReq.append_text = "";
        this.genReq.deadline_value = "";
        this.genReq.scheduled_send_at = "";
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
      const msg = m.scheduled_send_at
        ? "Schedule überschreiben und JETZT an Discord senden?"
        : "An Discord senden?";
      if (!confirm(msg)) return;
      try {
        // Aktuellen content_final synchron persistieren, damit Bot den User-Edit liest
        await api.patch(`/api/missions/${m.id}`, { content_final: m.content_final });
        await api.post(`/api/missions/${m.id}/send`);
        await this.loadMissions();
      }
      catch (e) { alert(e.message); }
    },
    async cancelSchedule(m) {
      try {
        const updated = await api.patch(`/api/missions/${m.id}`, { clear_scheduled_send_at: true });
        Object.assign(m, updated);
      } catch (e) { alert(e.message); }
    },
    async rewriteMission(m) {
      if (!confirm("Aktuellen Text durch neue KI-Variante ersetzen?")) return;
      this.rewritingMissionId = m.id;
      try {
        const updated = await api.post(`/api/missions/${m.id}/rewrite`);
        Object.assign(m, updated);
      } catch (e) { alert(e.message); }
      finally { this.rewritingMissionId = null; }
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
    async deleteDraft(mid) {
      if (!confirm("Entwurf endgültig löschen? Nicht wiederherstellbar.")) return;
      try { await api.del(`/api/missions/${mid}/purge`); await this.loadMissions(); }
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
    relativeTime,
  };
}

// ---- Archive Page ----
function archivePage() {
  return {
    missions: [],
    crews: [],
    crewFilter: "",
    purging: false,

    async init() {
      await Promise.all([this.loadCrews(), this.loadMissions()]);
    },
    async loadCrews() {
      this.crews = await api.get("/api/crews");
    },
    async loadMissions() {
      this.missions = await api.get("/api/missions?archived=true&limit=500");
    },
    get filteredMissions() {
      if (!this.crewFilter) return this.missions;
      const id = parseInt(this.crewFilter, 10);
      return this.missions.filter(m => m.crew_id === id);
    },
    crewName(id) {
      const c = this.crews.find(c => c.id === id);
      return c ? c.name : `#${id}`;
    },
    archivedBossInfo(m) {
      if (!m.archived_boss_info) return [];
      try {
        const arr = JSON.parse(m.archived_boss_info);
        return Array.isArray(arr) ? arr : [];
      } catch (e) { return []; }
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
    async purgeAll() {
      const targets = this.filteredMissions;
      if (targets.length === 0) return;
      const filterHint = this.crewFilter ? ` (Filter: ${this.crewName(parseInt(this.crewFilter, 10))})` : "";
      if (!confirm(`${targets.length} archivierte Aufträge${filterHint} endgültig löschen? Nicht wiederherstellbar.`)) return;
      if (!confirm("Wirklich? Diese Aktion ist endgültig.")) return;
      this.purging = true;
      let failed = 0;
      try {
        for (const m of targets) {
          try { await api.del(`/api/missions/${m.id}/purge`); }
          catch (e) { failed++; }
        }
        await this.loadMissions();
        if (failed > 0) alert(`${failed} Auftrag/Aufträge konnten nicht gelöscht werden.`);
      } finally { this.purging = false; }
    },

    statusLabel: statusLabelMap,
    statusClass: statusClassMap,
    formatDate,
  };
}

// ---- Settings Page ----
function settingsPage() {
  return {
    state: { anthropic_api_key_set: false, openai_api_key_set: false, system_prompt_default: "" },
    form: {
      anthropic_api_key: "",
      openai_api_key: "",
      default_provider: "anthropic",
      default_claude_model: "",
      default_openai_model: "",
      system_prompt: "",
    },
    msg: "",
    promptMsg: "",
    expiryMessages: [],
    newExpiryMsg: "",
    reactionMessages: [],
    newReactionMsg: "",
    systemPrompts: [],
    editingPromptId: null,
    newPromptForm: { name: "", text: "" },
    async init() {
      this.state = await api.get("/api/settings");
      this.form.default_provider = this.state.default_provider;
      this.form.default_claude_model = this.state.default_claude_model;
      this.form.default_openai_model = this.state.default_openai_model;
      this.form.system_prompt = this.state.system_prompt || "";
      await this.loadExpiryMessages();
      await this.loadReactionMessages();
      await this.loadSystemPrompts();
    },
    async loadSystemPrompts() {
      try { this.systemPrompts = await api.get("/api/system-prompts"); }
      catch (e) { /* silent */ }
    },
    async createPrompt() {
      const name = (this.newPromptForm.name || "").trim();
      const text = (this.newPromptForm.text || "").trim();
      if (!name || !text) { alert("Name und Text sind Pflicht."); return; }
      try {
        await api.post("/api/system-prompts", { name, text });
        this.newPromptForm = { name: "", text: "" };
        await this.loadSystemPrompts();
      } catch (e) { alert(e.message); }
    },
    async updatePrompt(sp) {
      try {
        await api.patch(`/api/system-prompts/${sp.id}`, { name: sp.name, text: sp.text });
        this.editingPromptId = null;
        await this.loadSystemPrompts();
      } catch (e) { alert(e.message); }
    },
    async activatePrompt(id) {
      try { await api.post(`/api/system-prompts/${id}/activate`); await this.loadSystemPrompts(); }
      catch (e) { alert(e.message); }
    },
    async deactivatePrompts() {
      try { await api.post("/api/system-prompts/deactivate"); await this.loadSystemPrompts(); }
      catch (e) { alert(e.message); }
    },
    async deletePrompt(id) {
      if (!confirm("Diesen Prompt löschen?")) return;
      try { await api.del(`/api/system-prompts/${id}`); await this.loadSystemPrompts(); }
      catch (e) { alert(e.message); }
    },
    async prefillPromptWithDefault() {
      try {
        const r = await api.get("/api/system-prompts/default");
        this.newPromptForm.text = r.text || "";
        if (!this.newPromptForm.name) this.newPromptForm.name = "Default-Kopie";
      } catch (e) { alert(e.message); }
    },
    async loadReactionMessages() {
      try { this.reactionMessages = await api.get("/api/reaction-messages"); }
      catch (e) { /* silent */ }
    },
    async addReactionMsg() {
      const text = (this.newReactionMsg || "").trim();
      if (!text) return;
      try {
        await api.post("/api/reaction-messages", { text });
        this.newReactionMsg = "";
        await this.loadReactionMessages();
      } catch (e) { alert(e.message); }
    },
    async deleteReactionMsg(id) {
      try { await api.del(`/api/reaction-messages/${id}`); await this.loadReactionMessages(); }
      catch (e) { alert(e.message); }
    },
    async savePrompt() {
      try {
        await api.patch("/api/settings", { system_prompt: this.form.system_prompt || "" });
        this.promptMsg = this.form.system_prompt.trim()
          ? "Prompt gespeichert."
          : "Prompt geleert — Default wird verwendet.";
        this.state = await api.get("/api/settings");
        setTimeout(() => { this.promptMsg = ""; }, 2500);
      } catch (e) { alert(e.message); }
    },
    resetPromptToDefault() {
      this.form.system_prompt = this.state.system_prompt_default || "";
    },
    clearPrompt() {
      this.form.system_prompt = "";
    },
    async loadExpiryMessages() {
      try { this.expiryMessages = await api.get("/api/expiry-messages"); }
      catch (e) { /* silent */ }
    },
    async addExpiryMsg() {
      const text = (this.newExpiryMsg || "").trim();
      if (!text) return;
      try {
        await api.post("/api/expiry-messages", { text });
        this.newExpiryMsg = "";
        await this.loadExpiryMessages();
      } catch (e) { alert(e.message); }
    },
    async deleteExpiryMsg(id) {
      try { await api.del(`/api/expiry-messages/${id}`); await this.loadExpiryMessages(); }
      catch (e) { alert(e.message); }
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

// ---------------------------------------------------------------------------
// Lore-Seite (Stadtteile + Gang-Stories)
// ---------------------------------------------------------------------------
function lorePage() {
  return {
    DISTRICT_ORDER: ["Algonquin", "Bohan", "Broker", "Colony Island", "Dukes"],
    tab: "districts",
    loading: true,
    error: "",
    // Districts-Tab
    districts: [],
    selectedDistrict: "algonquin",
    // Crews-Tab
    crews: [],
    selectedCrewId: null,
    crewSearch: "",

    async init() {
      // marked-Optionen sicher setzen (Lib via CDN in lore.html geladen)
      if (window.marked) {
        window.marked.setOptions({ breaks: false, gfm: true });
      }
      try {
        const [districtsResp, crewsResp] = await Promise.all([
          api.get("/api/lore/districts"),
          api.get("/api/crews"),
        ]);
        this.districts = districtsResp.districts || [];
        this.crews = (crewsResp || []).slice().sort((a, b) => a.name.localeCompare(b.name));
        if (this.districts.length && !this.districts.find(d => d.slug === this.selectedDistrict)) {
          this.selectedDistrict = this.districts[0].slug;
        }
        if (!this.selectedCrewId && this.crews.length) {
          this.selectedCrewId = this.crews[0].id;
        }
      } catch (e) {
        this.error = "Lore konnte nicht geladen werden: " + (e.message || e);
      } finally {
        this.loading = false;
      }
    },

    crewsByDistrict(districtName) {
      return this.crews.filter(c => (c.district || "") === districtName);
    },

    crewsByDistrictFiltered(districtName) {
      const search = (this.crewSearch || "").trim().toLowerCase();
      const list = this.crewsByDistrict(districtName);
      if (!search) return list;
      return list.filter(c => (c.name || "").toLowerCase().includes(search));
    },

    filteredCrewsTotal() {
      const search = (this.crewSearch || "").trim().toLowerCase();
      if (!search) return this.crews.length;
      return this.crews.filter(c => (c.name || "").toLowerCase().includes(search)).length;
    },

    selectedCrew() {
      return this.crews.find(c => c.id === this.selectedCrewId) || null;
    },

    renderMd(md) {
      if (!md) return "";
      if (window.marked && typeof window.marked.parse === "function") {
        return window.marked.parse(md);
      }
      // Fallback: nur HTML-escapen, falls marked nicht geladen
      const div = document.createElement("div");
      div.innerText = md;
      return "<pre>" + div.innerHTML + "</pre>";
    },

    // Convert crew.story_background -> Array von Discord-tauglichen Text-Bloecken,
    // jeder <= ~1900 Zeichen (Discord-Limit ist 2000, kleine Reserve).
    // Splittet bevorzugt an Sektionsgrenzen (---), dann an Sub-Header (### / ##),
    // dann an Absaetzen, im Notfall an Wortgrenzen.
    discordParts(crew) {
      const md = crew && crew.story_background ? crew.story_background : "";
      if (!md.trim()) return [];
      const cleaned = this._discordClean(md);
      return this._splitForDiscord(cleaned, 1900);
    },

    _discordClean(md) {
      // Discord-Markdown ist sehr aehnlich zu Standard-MD, aber:
      // - Tabellen werden NICHT gerendert (haben wir keine in den Stories)
      // - Horizontale Trennlinien (---) rendert Discord NICHT — wir machen
      //   eine optische Pause draus.
      // - Mehrere Leerzeilen reduzieren wir auf max. eine.
      let s = md.replace(/\r\n/g, "\n");
      s = s.replace(/^\s*---\s*$/gm, "─────────────────────");
      s = s.replace(/\n{3,}/g, "\n\n");
      return s.trim();
    },

    _splitForDiscord(text, maxLen) {
      if (text.length <= maxLen) return [text];
      const parts = [];
      const sepLine = "─────────────────────";
      let blocks = text.split("\n" + sepLine + "\n");
      blocks = blocks.map(b => b.trim()).filter(Boolean);
      for (const block of blocks) {
        if (block.length <= maxLen) {
          parts.push(block);
          continue;
        }
        // Sub-Header oder Header-Splits
        const headerSplit = block.split(/\n(?=#{1,3} )/);
        let buf = "";
        for (const seg of headerSplit) {
          const candidate = buf ? buf + "\n\n" + seg : seg;
          if (candidate.length <= maxLen) {
            buf = candidate;
          } else {
            if (buf) parts.push(buf);
            if (seg.length <= maxLen) {
              buf = seg;
            } else {
              const paraParts = this._splitByParagraphs(seg, maxLen);
              for (let i = 0; i < paraParts.length - 1; i++) parts.push(paraParts[i]);
              buf = paraParts[paraParts.length - 1];
            }
          }
        }
        if (buf) parts.push(buf);
      }
      return parts.map(p => p.trim()).filter(Boolean);
    },

    _splitByParagraphs(text, maxLen) {
      const paras = text.split(/\n\n+/);
      const out = [];
      let buf = "";
      for (const p of paras) {
        const candidate = buf ? buf + "\n\n" + p : p;
        if (candidate.length <= maxLen) {
          buf = candidate;
        } else {
          if (buf) out.push(buf);
          if (p.length <= maxLen) {
            buf = p;
          } else {
            const words = p.split(/\s+/);
            buf = "";
            for (const w of words) {
              const cand2 = buf ? buf + " " + w : w;
              if (cand2.length <= maxLen) {
                buf = cand2;
              } else {
                if (buf) out.push(buf);
                buf = w;
              }
            }
          }
        }
      }
      if (buf) out.push(buf);
      return out;
    },

    async copyToClipboard(text, evt) {
      try {
        await navigator.clipboard.writeText(text);
        const btn = evt && evt.target;
        if (btn) {
          const orig = btn.textContent;
          btn.textContent = "✓ Kopiert!";
          btn.classList.add("bg-green-700");
          btn.classList.remove("bg-zinc-700", "hover:bg-zinc-600");
          setTimeout(() => {
            btn.textContent = orig;
            btn.classList.remove("bg-green-700");
            btn.classList.add("bg-zinc-700", "hover:bg-zinc-600");
          }, 1500);
        }
      } catch (e) {
        alert("Kopieren fehlgeschlagen: " + e.message);
      }
    },
  };
}


// ---------------------------------------------------------------------------
// Ranking-Seite (Crew + Stadtteil-Performance)
// ---------------------------------------------------------------------------
function rankingPage() {
  return {
    loading: true,
    error: "",
    rangeSince: "all",     // 'today' | '7d' | '30d' | 'all'
    crimeOnly: true,
    data: { crews: [], districts: [], since: null, crime_only: true },
    _refreshTimer: null,

    async init() {
      await this.load();
      this._refreshTimer = setInterval(() => this.load().catch(() => {}), 15000);
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const params = new URLSearchParams();
        const since = this._sinceIso();
        if (since) params.set("since", since);
        params.set("crime_only", this.crimeOnly ? "true" : "false");
        const url = `/api/missions/ranking?${params.toString()}`;
        this.data = await api.get(url);
      } catch (e) {
        this.error = "Konnte Ranking nicht laden: " + (e.message || e);
        this.data = { crews: [], districts: [], since: null, crime_only: this.crimeOnly };
      } finally {
        this.loading = false;
      }
    },

    _sinceIso() {
      const now = new Date();
      const utc = (d) => new Date(Date.UTC(
        d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(),
        d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()
      ));
      if (this.rangeSince === "today") {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        return utc(d).toISOString().replace(/\.\d{3}Z$/, "");
      }
      if (this.rangeSince === "7d") {
        const d = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
        return utc(d).toISOString().replace(/\.\d{3}Z$/, "");
      }
      if (this.rangeSince === "30d") {
        const d = new Date(now.getTime() - 30 * 24 * 3600 * 1000);
        return utc(d).toISOString().replace(/\.\d{3}Z$/, "");
      }
      return null; // 'all' -> kein since
    },

    medalClass(idx) {
      if (idx === 0) return "medal-gold";
      if (idx === 1) return "medal-silver";
      if (idx === 2) return "medal-bronze";
      return "";
    },
  };
}

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
  put(p, b) { return this.send(p, "PUT", b); },
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
    // Personal-Bedarf Live-Feed
    personnelMode: localStorage.getItem("personnelMode") || "active",  // 'active' | '24h' | '7d' | '30d'
    personnel: { items: [], count: 0, etag: "", generated_at: "" },
    personnelEtag: localStorage.getItem("personnelEtagSeen") || "",
    personnelChangeCount: 0,                   // wie viele Updates seit dem letzten "Bell-Klick"
    personnelToast: "",                         // Toast-Banner-Text (auto-leer nach 6s)
    personnelEditing: null,                     // mission_id, dessen Brief gerade editiert wird
    personnelDraft: "",                         // Text-Buffer für Edit
    personnelSaving: false,
    personnelInitialLoad: true,                 // erstes Laden -> kein Toast
    personnelTemplates: [],                     // Quick-Pick Vorlagen
    personnelAiBusy: false,                     // KI-Vorschlag läuft
    personnelPosting: null,                     // mission_id, dessen Post gerade läuft
    personnelPostToast: "",                     // kurze Bestätigung nach erfolgreichem Post
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
      await this.loadPersonnel();
      // Templates einmalig — ändern sich nicht zur Laufzeit
      try { this.personnelTemplates = (await api.get("/api/dashboard/personnel/templates")).templates || []; }
      catch (e) { this.personnelTemplates = []; }
      setInterval(() => {
        this.loadCrews().catch(() => {});
        this.loadStats().catch(() => {});
        this.loadNotifications().catch(() => {});
      }, 5000);
      // Personal-Bedarf — 30s Polling mit ETag-Vergleich für Notifications
      setInterval(() => { this.loadPersonnel().catch(() => {}); }, 30000);
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

    // ---- Personal-Bedarf-Widget ----
    async loadPersonnel() {
      try {
        let url = "/api/dashboard/personnel?mode=" + this.personnelMode;
        if (this.personnelMode !== "active") {
          const hoursMap = { "24h": 24, "7d": 168, "30d": 720 };
          url = `/api/dashboard/personnel?mode=window&hours=${hoursMap[this.personnelMode] || 24}`;
        }
        const data = await api.get(url);
        const newEtag = data.etag || "";
        const prevEtag = this.personnel.etag || "";
        this.personnel = data;
        // Change-Detection: ETag hat sich geändert ggü. vorherigem Poll
        if (!this.personnelInitialLoad && newEtag && newEtag !== prevEtag) {
          this.personnelChangeCount++;
          this.personnelToast = `🎭 Personal-Bedarf aktualisiert (${this.personnel.count} Missions)`;
          setTimeout(() => { this.personnelToast = ""; }, 6000);
          // Browser-Notification (wenn erlaubt + Tab nicht aktiv)
          this._tryBrowserNotification(this.personnelToast);
        }
        this.personnelInitialLoad = false;
      } catch (e) {
        // Backend evtl. nicht restartet — leise sein, nicht im UI lärmen
      }
    },
    get personnelUnseen() {
      // Bell-Counter: alles, was seit dem letzten "ack" angekommen ist
      return this.personnelChangeCount;
    },
    ackPersonnel() {
      this.personnelChangeCount = 0;
      this.personnelEtag = this.personnel.etag || "";
      localStorage.setItem("personnelEtagSeen", this.personnelEtag);
    },
    setPersonnelMode(mode) {
      this.personnelMode = mode;
      localStorage.setItem("personnelMode", mode);
      this.personnelInitialLoad = true;  // Modus-Wechsel ist keine Notification
      this.loadPersonnel();
    },
    _tryBrowserNotification(text) {
      try {
        if (document.hidden && "Notification" in window && Notification.permission === "granted") {
          new Notification("Crime Automation", { body: text, icon: "/static/logo.png" });
        }
      } catch (e) {}
    },
    async requestNotificationPermission() {
      if (!("Notification" in window)) {
        alert("Browser unterstützt keine Notifications.");
        return;
      }
      const perm = await Notification.requestPermission();
      alert(perm === "granted"
        ? "Notifications aktiviert. Du wirst bei Personal-Änderungen benachrichtigt, wenn der Tab nicht aktiv ist."
        : "Notifications wurden nicht erlaubt.");
    },
    formatSlotShort(iso) {
      if (!iso) return "ohne Slot";
      const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
      const isTomorrow = d.toDateString() === tomorrow.toDateString();
      const hhmm = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
      if (sameDay) return `heute ${hhmm}`;
      if (isTomorrow) return `morgen ${hhmm}`;
      return d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    },
    personnelStatusBadge(status) {
      const map = {
        draft: { label: "geplant", cls: "bg-zinc-700 text-zinc-200" },
        pending: { label: "live", cls: "bg-amber-700 text-amber-100" },
        approved: { label: "👍 fertig", cls: "bg-green-800 text-green-100" },
        rejected: { label: "👎 fertig", cls: "bg-red-800 text-red-100" },
        cancelled: { label: "❌", cls: "bg-zinc-700 text-zinc-300" },
      };
      return map[status] || { label: status, cls: "bg-zinc-700 text-zinc-200" };
    },
    // Edit-Flow
    startEditPersonnel(item) {
      this.personnelEditing = item.mission_id;
      this.personnelDraft = item.personnel_brief || "";
    },
    cancelEditPersonnel() {
      this.personnelEditing = null;
      this.personnelDraft = "";
    },
    async savePersonnel(item) {
      this.personnelSaving = true;
      try {
        await api.patch(`/api/dashboard/missions/${item.mission_id}/personnel`,
                        { personnel_brief: this.personnelDraft });
        this.personnelEditing = null;
        this.personnelDraft = "";
        // Sofort neu laden — der eigene Edit triggert den ETag-Change
        // wir wollen das aber NICHT als Notification anzeigen
        this.personnelInitialLoad = true;
        await this.loadPersonnel();
      } catch (e) {
        alert("Fehler beim Speichern: " + (e.message || e));
      } finally {
        this.personnelSaving = false;
      }
    },
    applyPersonnelTemplate(templateId) {
      if (!templateId) return;
      const t = this.personnelTemplates.find(t => t.id === templateId);
      if (!t) return;
      // Wenn Draft schon Inhalt hat -> nachfragen
      if (this.personnelDraft && this.personnelDraft.trim()) {
        if (!confirm(`Vorlage „${t.label}" laden? Der aktuelle Text wird überschrieben.`)) return;
      }
      this.personnelDraft = t.content || "";
    },
    async aiSuggestPersonnel(item) {
      this.personnelAiBusy = true;
      try {
        const r = await api.post(`/api/dashboard/missions/${item.mission_id}/personnel/ai-suggest`, {});
        if (this.personnelDraft && this.personnelDraft.trim()) {
          if (!confirm("KI-Vorschlag laden? Der aktuelle Text wird überschrieben.")) return;
        }
        this.personnelDraft = r.suggestion || "";
      } catch (e) {
        alert("KI-Vorschlag fehlgeschlagen: " + (e.message || e));
      } finally {
        this.personnelAiBusy = false;
      }
    },
    async postPersonnelToDiscord(item) {
      if (!(item.personnel_brief || "").trim()) {
        alert("Bitte erst Personal-Brief speichern, dann posten.");
        return;
      }
      const replacing = !!item.personnel_discord_message_id;
      const msg = replacing
        ? `Personal-Brief für „${item.crew_name}" im Admin-Channel aktualisieren (vorherigen Post ersetzen)?`
        : `Personal-Brief für „${item.crew_name}" in den Admin-Channel posten?`;
      if (!confirm(msg)) return;
      this.personnelPosting = item.mission_id;
      try {
        const r = await api.post(`/api/dashboard/missions/${item.mission_id}/personnel/post`, {});
        this.personnelPostToast = replacing
          ? `✓ Aktualisiert in Admin-Channel (Crew „${item.crew_name}")`
          : `✓ Gepostet in Admin-Channel (Crew „${item.crew_name}")`;
        setTimeout(() => { this.personnelPostToast = ""; }, 5000);
        // Personnel neu laden — message_id ist jetzt gesetzt
        this.personnelInitialLoad = true;
        await this.loadPersonnel();
      } catch (e) {
        alert("Discord-Post fehlgeschlagen: " + (e.message || e));
      } finally {
        this.personnelPosting = null;
      }
    },
  };
}

// ---- Crew Page ----
function crewPage() {
  const id = parseInt(location.pathname.split("/").pop(), 10);
  return {
    crewId: id,
    crew: { name: "", story_background: "", crime_business: "", crime_business_channel_id: "", discord_channel_id: "", info_channel_id: "", district: "", color_hex: "#b91c1c", bonus_points: 0 },
    bonusFreeValue: null,
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
    // KI-Folgeauftrags-Vorschläge (3 Stueck, basieren auf letzter Reaktion)
    suggestions: [],
    suggestionsBusy: false,
    suggestionsLoaded: false,
    suggestionsLastStatus: "",  // 'approved' | 'rejected' | 'cancelled' | 'pending' | ''
    suggestionsMessage: "",
    suggestionsIsError: false,
    // Personal-Brief — pro Mission auf dieser Crew-Seite
    personnelEditingId: null,        // welche Mission gerade editiert wird
    personnelDraftCrew: "",          // Edit-Buffer
    personnelSavingCrew: false,
    personnelAiBusyCrew: false,
    personnelPostingId: null,        // Mission die gerade gepostet wird
    personnelTemplatesCrew: [],       // Quick-Pick Vorlagen (einmal geladen)
    personnelChannelConfigured: false, // gibt's eine Admin-Channel-ID in Settings?

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
      // Personal-Brief-Templates einmalig laden (für Quick-Pick im Edit-Modus)
      try {
        const r = await api.get("/api/dashboard/personnel/templates");
        this.personnelTemplatesCrew = r.templates || [];
      } catch (e) { this.personnelTemplatesCrew = []; }
      // Settings checken: ist Admin-Channel gesetzt? (Posten-Button nur dann zeigen)
      try {
        const s = await api.get("/api/settings");
        this.personnelChannelConfigured = !!(s.personnel_admin_channel_id || "").trim();
      } catch (e) { this.personnelChannelConfigured = false; }
      // Auto-Refresh alle 5 Sek (fuer Discord-Reaktions-Updates + Boss-Texte)
      setInterval(() => {
        this.loadMissions().catch(() => {});
        this.loadBossInfo().catch(() => {});
      }, 5000);
    },
    // ---- Personal-Brief auf der Crew-Seite ----
    startEditPersonnelCrew(m) {
      this.personnelEditingId = m.id;
      this.personnelDraftCrew = m.personnel_brief || "";
    },
    cancelEditPersonnelCrew() {
      this.personnelEditingId = null;
      this.personnelDraftCrew = "";
    },
    applyPersonnelTemplateCrew(templateId) {
      if (!templateId) return;
      const t = this.personnelTemplatesCrew.find(t => t.id === templateId);
      if (!t) return;
      if (this.personnelDraftCrew && this.personnelDraftCrew.trim()) {
        if (!confirm(`Vorlage „${t.label}" laden? Der aktuelle Text wird überschrieben.`)) return;
      }
      this.personnelDraftCrew = t.content || "";
    },
    async aiSuggestPersonnelCrew(m) {
      this.personnelAiBusyCrew = true;
      try {
        const r = await api.post(`/api/dashboard/missions/${m.id}/personnel/ai-suggest`, {});
        if (this.personnelDraftCrew && this.personnelDraftCrew.trim()) {
          if (!confirm("KI-Vorschlag laden? Der aktuelle Text wird überschrieben.")) return;
        }
        this.personnelDraftCrew = r.suggestion || "";
      } catch (e) {
        alert("KI-Vorschlag fehlgeschlagen: " + (e.message || e));
      } finally {
        this.personnelAiBusyCrew = false;
      }
    },
    async savePersonnelCrew(m) {
      this.personnelSavingCrew = true;
      try {
        const r = await api.patch(`/api/dashboard/missions/${m.id}/personnel`,
                                  { personnel_brief: this.personnelDraftCrew });
        // Lokales mission-Objekt updaten, damit Anzeige sofort frisch ist
        m.personnel_brief = r.personnel_brief;
        m.personnel_updated_at = r.personnel_updated_at;
        this.personnelEditingId = null;
        this.personnelDraftCrew = "";
      } catch (e) {
        alert("Fehler beim Speichern: " + (e.message || e));
      } finally {
        this.personnelSavingCrew = false;
      }
    },
    async postPersonnelToDiscordCrew(m) {
      if (!(m.personnel_brief || "").trim()) {
        alert("Bitte erst Personal-Brief speichern, dann posten.");
        return;
      }
      const replacing = !!m.personnel_discord_message_id;
      const msg = replacing
        ? `Personal-Brief im Admin-Channel aktualisieren (vorherigen Post ersetzen)?`
        : `Personal-Brief in den Admin-Channel posten?`;
      if (!confirm(msg)) return;
      this.personnelPostingId = m.id;
      try {
        const r = await api.post(`/api/dashboard/missions/${m.id}/personnel/post`, {});
        m.personnel_discord_message_id = r.message_id || "";
      } catch (e) {
        alert("Discord-Post fehlgeschlagen: " + (e.message || e));
      } finally {
        this.personnelPostingId = null;
      }
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

    async adjustBonus(delta) {
      try {
        this.crew = await api.post(`/api/crews/${this.crewId}/bonus`, { points: delta });
      } catch (e) { alert(e.message); }
    },
    async adjustBonusFree() {
      const n = parseInt(this.bonusFreeValue, 10);
      if (!n) return;
      try {
        this.crew = await api.post(`/api/crews/${this.crewId}/bonus`, { points: n });
        this.bonusFreeValue = null;
      } catch (e) { alert(e.message); }
    },
    async resetBonus() {
      if (!confirm("Bonus-Punkte auf 0 zurücksetzen?")) return;
      try {
        this.crew = await api.patch(`/api/crews/${this.crewId}`, { bonus_points: 0 });
      } catch (e) { alert(e.message); }
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

    // ---- KI-Folgeauftrags-Vorschläge ----
    suggestionsStatusLabel() {
      const map = {
        approved: "👍 erledigt → Vorschläge eskalieren / nächste Stufe",
        rejected: "👎 fehlgeschlagen → Vorschläge wechseln den Ton / Ansatz",
        cancelled: "❌ nicht ausführbar → Vorschläge sind realistischer skaliert",
        pending: "⏳ offen → Vorschläge sind parallele Operationen",
      };
      return map[this.suggestionsLastStatus] || "kein Verlauf → frische Einstiege";
    },

    async loadSuggestions(force = false) {
      this.suggestionsMessage = "";
      this.suggestionsIsError = false;
      this.suggestionsBusy = true;
      try {
        const provider = (this.genReq && this.genReq.provider) || "anthropic";
        const model = (this.genReq && this.genReq.model) || "";
        const res = await api.post(`/api/missions/suggestions/${this.crewId}`, {
          crew_id: this.crewId,
          provider,
          model,
          extra_instructions: "",
        });
        this.suggestions = Array.isArray(res.suggestions) ? res.suggestions : [];
        this.suggestionsLastStatus = res.last_status || "";
        this.suggestionsLoaded = true;
        if (this.suggestions.length === 0) {
          this.suggestionsMessage = "Keine Vorschläge geparst. Roh-Antwort der KI:\n" + (res.raw || "");
          this.suggestionsIsError = true;
        } else if (force) {
          this.suggestionsMessage = `✓ Neu generiert (${this.suggestions.length} Vorschläge).`;
        }
      } catch (e) {
        this.suggestionsMessage = "Fehler beim Generieren: " + (e.message || e);
        this.suggestionsIsError = true;
      } finally {
        this.suggestionsBusy = false;
      }
    },

    async adoptSuggestion(s) {
      const text = (s && s.content ? String(s.content) : "").trim();
      if (!text) { alert("Vorschlag ist leer."); return; }
      if (!confirm(`Diesen Vorschlag als Entwurf übernehmen?\n\nTitel: ${s.title || "(ohne)"}\n\nDer Auftrag wird als DRAFT angelegt — du kannst danach editieren und senden.`)) return;
      this.suggestionsBusy = true;
      try {
        await api.post("/api/missions/manual", {
          crew_id: this.crewId,
          content: text,
          deadline_minutes: 0,
          scheduled_send_at: null,
        });
        this.suggestionsMessage = `✓ „${s.title || "Vorschlag"}" als Entwurf gespeichert.`;
        this.suggestionsIsError = false;
        await this.loadMissions();
      } catch (e) {
        this.suggestionsMessage = "Fehler beim Übernehmen: " + (e.message || e);
        this.suggestionsIsError = true;
      } finally {
        this.suggestionsBusy = false;
      }
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
        // Defensive 3-Schritt-Update — Alpine.js erkennt bei einzelnen
        // Array-Items nicht immer zuverlässig die Property-Änderung:
        // 1) Felder direkt setzen (triggert x-model im Textarea)
        m.content_final = updated.content_final;
        m.content_generated = updated.content_generated;
        m.ai_provider = updated.ai_provider;
        m.personnel_brief = updated.personnel_brief;
        m.personnel_updated_at = updated.personnel_updated_at;
        // 2) Missions-Array komplett ersetzen — garantiert Rerender
        this.missions = this.missions.map(x => x.id === m.id ? { ...x, ...updated } : x);
        // 3) Frisch vom Backend als Backup-Sync
        await this.loadMissions();
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

// ---- Story Page ----
function storyPage() {
  return {
    files: [],
    activeFile: "",
    content: "",
    dirty: false,
    loading: false,
    saving: false,
    msg: "",
    initError: "",
    viewMode: "view",       // "view" = Prosa-Vorschau, "edit" = Textarea
    pdfExporting: false,

    async init() {
      if (window.marked) window.marked.setOptions({ breaks: false, gfm: true });
      await this.refreshFileList();
      if (this.files.length) await this.selectFile(this.files[0].filename);
    },
    async refreshFileList() {
      try {
        this.files = await api.get("/api/story/files");
        this.initError = "";
      } catch (e) {
        this.initError = `Konnte Story-Files nicht laden: ${e.message}`;
        console.error("storyPage refreshFileList:", e);
      }
    },
    async selectFile(filename) {
      if (this.dirty && !confirm("Ungespeicherte Änderungen verwerfen?")) return;
      this.activeFile = filename;
      this.loading = true;
      this.dirty = false;
      this.viewMode = "view";   // bei Tab-Wechsel zurück zur Vorschau
      try {
        const r = await api.get(`/api/story/file/${encodeURIComponent(filename)}`);
        this.content = r.content || "";
      } catch (e) { alert(e.message); }
      finally { this.loading = false; }
    },
    async saveFile() {
      if (!this.activeFile) return;
      this.saving = true;
      this.msg = "";
      try {
        await api.send(
          `/api/story/file/${encodeURIComponent(this.activeFile)}`,
          "PUT",
          { content: this.content }
        );
        this.dirty = false;
        this.msg = "✓ Gespeichert (Backup als .bak abgelegt)";
        await this.refreshFileList();
        setTimeout(() => { this.msg = ""; }, 3000);
      } catch (e) { alert(e.message); }
      finally { this.saving = false; }
    },
    async reload() {
      if (this.dirty && !confirm("Ungespeicherte Änderungen verwerfen?")) return;
      if (this.activeFile) await this.selectFile(this.activeFile);
    },
    activeFileLabel() {
      const f = this.files.find(x => x.filename === this.activeFile);
      return f ? f.label : (this.activeFile || "");
    },
    renderMd(md) {
      if (!md) return "";
      if (window.marked && typeof window.marked.parse === "function") {
        return window.marked.parse(md);
      }
      const div = document.createElement("div");
      div.innerText = md;
      return "<pre>" + div.innerHTML + "</pre>";
    },
    _slugifyForFilename(s) {
      return (s || "story")
        .toString()
        .normalize("NFD").replace(/[̀-ͯ]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 80) || "story";
    },
    async exportFilePdf() {
      if (!this.activeFile) return;
      if (typeof window.html2pdf !== "function") {
        alert("PDF-Library nicht geladen (html2pdf). Seite neu laden bitte.");
        return;
      }
      const area = document.getElementById("pdf-render-area");
      if (!area) {
        alert("PDF-Render-Bereich fehlt im DOM.");
        return;
      }
      this.pdfExporting = true;
      try {
        const title = this.activeFileLabel();
        const subtitle = `Story · docs/${this.activeFile}`;
        const contentHtml = this.renderMd(this.content || "");
        area.innerHTML = `
          <h1>${(title || "").replace(/</g, "&lt;")}</h1>
          <div class="pdf-subtitle">${subtitle.replace(/</g, "&lt;")}</div>
          ${contentHtml}
        `;
        const opts = {
          margin:       [12, 12, 14, 12],
          filename:     "story-" + this._slugifyForFilename(title) + ".pdf",
          image:        { type: "jpeg", quality: 0.95 },
          html2canvas:  { scale: 2, useCORS: true, backgroundColor: "#ffffff" },
          jsPDF:        { unit: "mm", format: "a4", orientation: "portrait" },
          pagebreak:    { mode: ["css", "legacy"] },
        };
        await window.html2pdf().set(opts).from(area).save();
      } catch (e) {
        alert("PDF-Export fehlgeschlagen: " + (e.message || e));
      } finally {
        area.innerHTML = "";
        this.pdfExporting = false;
      }
    },
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
    rankingForm: {
      ranking_daily_enabled: "false",
      ranking_daily_channel_id: "",
      ranking_daily_time: "03:33",
      ranking_daily_range: "all",
      ranking_daily_crime_only: "true",
      ranking_daily_show_districts: "true",
      ranking_daily_title: "🏆 Crew-Ranking — Liberty City",
      ranking_daily_intro: "",
    },
    rankingMsg: "",
    top3Titles: [],
    newTop3Title: "",
    top3Form: {
      ranking_top3_enabled: "false",
      ranking_top3_channel_id: "",
      ranking_top3_time: "08:00",
      ranking_top3_range: "all",
      ranking_top3_crime_only: "true",
      ranking_top3_title: "🥇 Die Spitze von Liberty City",
      ranking_top3_intro: "",
    },
    top3Msg: "",
    // Personnel-Admin-Channel
    personnelChannelForm: { personnel_admin_channel_id: "" },
    personnelChannelSaving: false,
    personnelChannelMsg: "",
    personnelChannelMsgError: false,
    async init() {
      this.state = await api.get("/api/settings");
      this.form.default_provider = this.state.default_provider;
      this.form.default_claude_model = this.state.default_claude_model;
      this.form.default_openai_model = this.state.default_openai_model;
      this.form.system_prompt = this.state.system_prompt || "";
      // Daily-Ranking-Konfig laden (Strings, weil settings_store nur strings hat)
      for (const k of Object.keys(this.rankingForm)) {
        if (this.state[k] !== undefined && this.state[k] !== "") this.rankingForm[k] = this.state[k];
      }
      // Defaults korrigieren wenn DB leer
      if (!this.rankingForm.ranking_daily_enabled) this.rankingForm.ranking_daily_enabled = "false";
      if (!this.rankingForm.ranking_daily_time) this.rankingForm.ranking_daily_time = "03:33";
      if (!this.rankingForm.ranking_daily_range) this.rankingForm.ranking_daily_range = "all";
      if (!this.rankingForm.ranking_daily_crime_only) this.rankingForm.ranking_daily_crime_only = "true";
      if (!this.rankingForm.ranking_daily_show_districts) this.rankingForm.ranking_daily_show_districts = "true";
      if (!this.rankingForm.ranking_daily_title) this.rankingForm.ranking_daily_title = "🏆 Crew-Ranking — Liberty City";
      // Top3-Form befüllen
      for (const k of Object.keys(this.top3Form)) {
        if (this.state[k] !== undefined && this.state[k] !== "") this.top3Form[k] = this.state[k];
      }
      if (!this.top3Form.ranking_top3_enabled) this.top3Form.ranking_top3_enabled = "false";
      if (!this.top3Form.ranking_top3_time) this.top3Form.ranking_top3_time = "08:00";
      if (!this.top3Form.ranking_top3_range) this.top3Form.ranking_top3_range = "all";
      if (!this.top3Form.ranking_top3_crime_only) this.top3Form.ranking_top3_crime_only = "true";
      if (!this.top3Form.ranking_top3_title) this.top3Form.ranking_top3_title = "🥇 Die Spitze von Liberty City";
      // Personnel-Channel-Form befüllen
      this.personnelChannelForm.personnel_admin_channel_id = this.state.personnel_admin_channel_id || "";
      await this.loadTop3Titles();
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
    async saveRanking() {
      try {
        const payload = {};
        for (const k of Object.keys(this.rankingForm)) {
          payload[k] = String(this.rankingForm[k] || "");
        }
        await api.patch("/api/settings", payload);
        this.rankingMsg = "Gespeichert.";
        setTimeout(() => { this.rankingMsg = ""; }, 2500);
      } catch (e) { alert(e.message); }
    },
    async loadTop3Titles() {
      try { this.top3Titles = await api.get("/api/top3-title-pool"); }
      catch (e) { /* silent */ }
    },
    async addTop3Title() {
      const text = (this.newTop3Title || "").trim();
      if (!text) return;
      try {
        await api.post("/api/top3-title-pool", { text });
        this.newTop3Title = "";
        await this.loadTop3Titles();
      } catch (e) { alert(e.message); }
    },
    async deleteTop3Title(id) {
      try { await api.del(`/api/top3-title-pool/${id}`); await this.loadTop3Titles(); }
      catch (e) { alert(e.message); }
    },

    async saveTop3() {
      try {
        const payload = {};
        for (const k of Object.keys(this.top3Form)) {
          payload[k] = String(this.top3Form[k] || "");
        }
        await api.patch("/api/settings", payload);
        this.top3Msg = "Gespeichert.";
        setTimeout(() => { this.top3Msg = ""; }, 2500);
      } catch (e) { alert(e.message); }
    },
    async savePersonnelChannel() {
      this.personnelChannelSaving = true;
      this.personnelChannelMsg = "";
      this.personnelChannelMsgError = false;
      try {
        const id = String(this.personnelChannelForm.personnel_admin_channel_id || "").trim();
        await api.patch("/api/settings", { personnel_admin_channel_id: id });
        this.personnelChannelMsg = id
          ? 'Gespeichert. Im Dashboard-Widget steht jetzt der "📤 Posten"-Button bereit.'
          : 'Gespeichert (leer — Posten ist deaktiviert).';
        setTimeout(() => { this.personnelChannelMsg = ""; }, 4000);
      } catch (e) {
        this.personnelChannelMsg = "Fehler: " + (e.message || e);
        this.personnelChannelMsgError = true;
      } finally {
        this.personnelChannelSaving = false;
      }
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
    // Edit-Mode State
    editingDistrictSlug: null,
    districtDraft: "",
    districtSaving: false,
    districtError: "",
    editingCrewId: null,
    crewDraft: "",
    crewSaving: false,
    crewError: "",
    // PDF-Export State
    pdfExporting: false,

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

    // ───── Edit: Stadtteil-Markdown ─────
    selectedDistrictObj() {
      return this.districts.find(d => d.slug === this.selectedDistrict) || null;
    },
    startEditDistrict() {
      const d = this.selectedDistrictObj();
      if (!d) return;
      this.editingDistrictSlug = d.slug;
      this.districtDraft = d.content_md || "";
      this.districtError = "";
    },
    cancelEditDistrict() {
      this.editingDistrictSlug = null;
      this.districtDraft = "";
      this.districtError = "";
    },
    async saveDistrict() {
      if (!this.editingDistrictSlug) return;
      this.districtSaving = true;
      this.districtError = "";
      try {
        const updated = await api.patch(`/api/lore/districts/${this.editingDistrictSlug}`,
                                        { content_md: this.districtDraft });
        const idx = this.districts.findIndex(d => d.slug === updated.slug);
        if (idx >= 0) {
          this.districts[idx] = {
            ...this.districts[idx],
            content_md: updated.content_md,
            has_override: true,
          };
        }
        this.editingDistrictSlug = null;
        this.districtDraft = "";
      } catch (e) {
        this.districtError = "Speichern fehlgeschlagen: " + (e.message || e);
      } finally {
        this.districtSaving = false;
      }
    },
    async resetDistrict(slug) {
      if (!confirm("Override löschen und Original-Text aus DISTRICTS.md wiederherstellen?")) return;
      try {
        await api.del(`/api/lore/districts/${slug}/override`);
        const r = await api.get("/api/lore/districts");
        this.districts = r.districts || [];
      } catch (e) {
        alert("Reset fehlgeschlagen: " + (e.message || e));
      }
    },

    // ───── Edit: Crew-Story ─────
    startEditCrew() {
      const c = this.selectedCrew();
      if (!c) return;
      this.editingCrewId = c.id;
      this.crewDraft = c.story_background || "";
      this.crewError = "";
    },
    cancelEditCrew() {
      this.editingCrewId = null;
      this.crewDraft = "";
      this.crewError = "";
    },
    async saveCrew() {
      if (!this.editingCrewId) return;
      this.crewSaving = true;
      this.crewError = "";
      try {
        const updated = await api.patch(`/api/crews/${this.editingCrewId}`,
                                        { story_background: this.crewDraft });
        const idx = this.crews.findIndex(c => c.id === updated.id);
        if (idx >= 0) {
          this.crews[idx] = { ...this.crews[idx], story_background: updated.story_background };
        }
        this.editingCrewId = null;
        this.crewDraft = "";
      } catch (e) {
        this.crewError = "Speichern fehlgeschlagen: " + (e.message || e);
      } finally {
        this.crewSaving = false;
      }
    },

    // ───── PDF-Export ─────
    _slugifyForFilename(s) {
      return (s || "lore")
        .toString()
        .normalize("NFD").replace(/[̀-ͯ]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 80) || "lore";
    },
    async _renderHtmlToPdf({ title, subtitle, contentHtml, filename }) {
      if (typeof window.html2pdf !== "function") {
        alert("PDF-Library nicht geladen (html2pdf). Seite neu laden bitte.");
        return;
      }
      const area = document.getElementById("pdf-render-area");
      if (!area) {
        alert("PDF-Render-Bereich fehlt im DOM.");
        return;
      }
      const safeTitle = (title || "").replace(/</g, "&lt;");
      const safeSubtitle = (subtitle || "").replace(/</g, "&lt;");
      area.innerHTML = `
        <h1>${safeTitle}</h1>
        ${safeSubtitle ? `<div class="pdf-subtitle">${safeSubtitle}</div>` : ""}
        ${contentHtml}
      `;
      const opts = {
        margin:       [12, 12, 14, 12],   // mm
        filename:     filename,
        image:        { type: "jpeg", quality: 0.95 },
        html2canvas:  { scale: 2, useCORS: true, backgroundColor: "#ffffff" },
        jsPDF:        { unit: "mm", format: "a4", orientation: "portrait" },
        pagebreak:    { mode: ["css", "legacy"] },
      };
      try {
        await window.html2pdf().set(opts).from(area).save();
      } finally {
        area.innerHTML = "";   // wieder leeren damit nichts hängen bleibt
      }
    },
    async exportDistrictPdf(district) {
      if (!district) return;
      this.pdfExporting = true;
      try {
        const contentHtml = this.renderMd(district.content_md);
        const fname = "stadtteil-" + this._slugifyForFilename(district.name) + ".pdf";
        await this._renderHtmlToPdf({
          title: district.name,
          subtitle: "Stadtteil-Lore · Liberty City",
          contentHtml: contentHtml,
          filename: fname,
        });
      } catch (e) {
        alert("PDF-Export fehlgeschlagen: " + (e.message || e));
      } finally {
        this.pdfExporting = false;
      }
    },
    async exportCrewPdf(crew) {
      if (!crew) return;
      this.pdfExporting = true;
      try {
        const story = (crew.story_background || "").trim();
        const contentHtml = story
          ? this.renderMd(story)
          : "<p><em>Diese Crew hat noch keine Story-Background hinterlegt.</em></p>";
        const fname = "crew-" + this._slugifyForFilename(crew.name) + ".pdf";
        const subtitle = crew.district ? `Fraktion · ${crew.district}` : "Fraktion";
        await this._renderHtmlToPdf({
          title: crew.name,
          subtitle: subtitle,
          contentHtml: contentHtml,
          filename: fname,
        });
      } catch (e) {
        alert("PDF-Export fehlgeschlagen: " + (e.message || e));
      } finally {
        this.pdfExporting = false;
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
    crimeOnly: false,
    data: { crews: [], districts: [], since: null, crime_only: false },
    _refreshTimer: null,
    // Discord-Post (One-Click, nutzt Settings)
    posting: false,
    postingMode: "",   // 'full' | 'top3' während aktiver Sendung
    postResult: "",
    postResultIsError: false,
    // Ranking-Reset
    resetting: false,

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

    _rangeIsoFromKey(rangeKey) {
      const now = new Date();
      const utc = (d) => new Date(Date.UTC(
        d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(),
        d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()
      ));
      if (rangeKey === "today") {
        const d = new Date(); d.setHours(0, 0, 0, 0);
        return utc(d).toISOString().replace(/\.\d{3}Z$/, "");
      }
      if (rangeKey === "7d") return utc(new Date(now.getTime() - 7 * 86400 * 1000)).toISOString().replace(/\.\d{3}Z$/, "");
      if (rangeKey === "30d") return utc(new Date(now.getTime() - 30 * 86400 * 1000)).toISOString().replace(/\.\d{3}Z$/, "");
      return null;
    },

    async _postFromSettings(mode) {
      // Lädt die zur Mode passenden Settings (ranking_daily_* oder ranking_top3_*)
      // und postet direkt. Keine Channel-Abfrage.
      this.posting = true;
      this.postingMode = mode;
      this.postResult = "";
      this.postResultIsError = false;
      try {
        const settings = await api.get("/api/settings");
        const prefix = mode === "top3" ? "ranking_top3" : "ranking_daily";
        const channelId = (settings[`${prefix}_channel_id`] || "").trim();
        if (!channelId) {
          throw new Error(`Channel-ID für ${mode === "top3" ? "Top 3" : "Gesamt"} ist in den Settings nicht gesetzt.`);
        }
        const rangeKey = settings[`${prefix}_range`] || "all";
        const body = {
          channel_id: channelId,
          since: this._rangeIsoFromKey(rangeKey),
          crime_only: (settings[`${prefix}_crime_only`] || "true").toLowerCase() === "true",
          title: settings[`${prefix}_title`] || (mode === "top3"
            ? "🥇 Die Spitze von Liberty City"
            : "🏆 Crew-Ranking — Liberty City"),
          intro: settings[`${prefix}_intro`] || "",
          show_district_aggregate: mode === "full"
            && (settings.ranking_daily_show_districts || "true").toLowerCase() === "true",
          top_n: mode === "top3" ? 3 : 25,
          mode: mode,
        };
        const r = await api.post("/api/missions/ranking/post-to-discord", body);
        this.postResult = `✓ ${mode === "top3" ? "Top 3" : "Gesamt"} gepostet (${r.crews_posted} Crews · ${r.range} · ${r.scope})`;
        setTimeout(() => { this.postResult = ""; }, 4000);
      } catch (e) {
        this.postResult = "Fehler: " + (e.message || e);
        this.postResultIsError = true;
      } finally {
        this.posting = false;
        this.postingMode = "";
      }
    },

    async postFullNow() { await this._postFromSettings("full"); },
    async postTop3Now() { await this._postFromSettings("top3"); },

    async resetRanking() {
      // Doppelter Confirm — destruktive Aktion.
      if (!confirm(
        "⚠ Ranking zurücksetzen?\n\n" +
        "• Alle Bonus-Punkte werden auf 0 gesetzt.\n" +
        "• Es wird ein neuer Stichtag (jetzt) gespeichert.\n" +
        "• Im 'Gesamt'-View zählen nur noch Missions ab diesem Zeitpunkt.\n\n" +
        "Bestehende Missions bleiben in der DB erhalten."
      )) return;
      if (!confirm("Wirklich? Das kann nur durch manuelles Eintragen wieder rückgängig gemacht werden.")) return;

      this.resetting = true;
      this.postResult = "";
      this.postResultIsError = false;
      try {
        const r = await api.post("/api/missions/ranking/reset", {});
        const stamp = (r && r.reset_at) ? new Date(r.reset_at + "Z").toLocaleString("de-DE") : "—";
        this.postResult = `✓ Ranking zurückgesetzt (${r.bonus_resets} Crews mit Bonus genullt · Stichtag: ${stamp})`;
        // Wenn aktuell ein Zeitraum-Filter aktiv ist, auf 'all' wechseln,
        // damit der Effekt sofort sichtbar ist.
        this.rangeSince = "all";
        await this.load();
        setTimeout(() => { this.postResult = ""; }, 6000);
      } catch (e) {
        this.postResult = "Fehler beim Reset: " + (e.message || e);
        this.postResultIsError = true;
      } finally {
        this.resetting = false;
      }
    },
  };
}


// ---- Mittler / Quest-Geber Page ----
function questGiversPage() {
  return {
    activeTab: "givers",
    loading: true,
    error: "",
    // Raw-Markdown pro Datei (für Edit-Modus)
    giversRaw: "",
    personnelRaw: "",
    // Gerendertes HTML (für Anzeige-Modus)
    giversHtml: "",
    personnelHtml: "",
    // Edit-State pro Tab
    editing: false,           // true = aktueller Tab im Edit-Modus
    draft: "",                // Textarea-Buffer
    saving: false,
    saveMsg: "",
    saveError: false,

    async init() { await this.reload(); },

    async reload() {
      this.loading = true;
      this.error = "";
      try {
        const [givers, personnel] = await Promise.all([
          api.get("/api/story/file/QUEST_GIVERS.md").catch(() => ({ content: "" })),
          api.get("/api/story/file/QUEST_PERSONNEL.md").catch(() => ({ content: "" })),
        ]);
        this.giversRaw = givers.content || "";
        this.personnelRaw = personnel.content || "";
        this._render();
      } catch (e) {
        this.error = "Konnte Doku nicht laden: " + (e.message || e);
      } finally {
        this.loading = false;
      }
    },
    _render() {
      const empty = "*(Datei leer oder nicht vorhanden)*";
      this.giversHtml = this._renderMarkdown(this.giversRaw || empty);
      this.personnelHtml = this._renderMarkdown(this.personnelRaw || empty);
    },
    get currentFilename() {
      return this.activeTab === "givers" ? "QUEST_GIVERS.md" : "QUEST_PERSONNEL.md";
    },
    get currentRaw() {
      return this.activeTab === "givers" ? this.giversRaw : this.personnelRaw;
    },
    switchTab(tab) {
      if (this.editing && !confirm("Edit-Modus verlassen? Ungespeicherte Änderungen gehen verloren.")) return;
      this.activeTab = tab;
      this.editing = false;
      this.draft = "";
      this.saveMsg = "";
    },
    startEdit() {
      this.draft = this.currentRaw;
      this.editing = true;
      this.saveMsg = "";
    },
    cancelEdit() {
      if (this.draft !== this.currentRaw &&
          !confirm("Änderungen verwerfen?")) return;
      this.editing = false;
      this.draft = "";
      this.saveMsg = "";
    },
    insertGiverTemplate() {
      const tpl = `
---

## NEU. <Name> — „<Spitzname>"

**Rolle:** <Hauptfunktion>
**Stil:** <kurze Charakterisierung>
**Sprechweise:** <wie redet er/sie>
**Erscheinung:** <Aussehen, Alter, Kleidung>

**Schwerpunkt:** <wofür wird er/sie gerufen>

**Beziehung zu Crews:** <wie sie ihn/sie wahrnehmen>

**Typische Aufträge:**
- <Auftragstyp 1>
- <Auftragstyp 2>
- <Auftragstyp 3>

**Catchphrase / Stilanker:**
> *„<einprägsamer Satz>"*
`;
      this.draft = (this.draft || "").replace(/\s+$/, "") + tpl;
    },
    insertNpcTemplate() {
      const tpl = `
| <Nr> | **<Archetype-Name>** | <typischer Einsatz> | <Kostüm-Trigger> |`;
      this.draft = (this.draft || "").replace(/\s+$/, "") + tpl;
    },
    // ---- Konsistenz-Check ----
    checking: false,
    checkReport: "",                // Markdown
    checkReportHtml: "",            // Gerendertes HTML
    checkError: "",
    showCheckPanel: false,
    recommendations: [],            // [{title, instruction, target}]
    applyingIdx: null,              // Index der gerade laufenden Empfehlung
    // Preview-Modal nach KI-Edit
    previewOpen: false,
    previewTitle: "",
    previewOldContent: "",
    previewNewContent: "",
    previewSaving: false,
    previewError: "",

    _renderMarkdown(md) {
      if (!md) return "";
      // marked.js bevorzugt — 2 Varianten (v5+: marked.parse, v4: marked())
      if (window.marked) {
        if (typeof window.marked.parse === "function") return window.marked.parse(md);
        if (typeof window.marked === "function") return window.marked(md);
      }
      // Mini-Fallback: deckt H1-H4, **fett**, *kursiv*, `code`, Listen, Absätze ab
      const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const lines = md.split("\n");
      const out = [];
      let inList = false, paraBuf = [];
      const flushPara = () => {
        if (paraBuf.length) { out.push("<p>" + paraBuf.join(" ") + "</p>"); paraBuf = []; }
      };
      const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
      const inline = (s) => esc(s)
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\*([^*]+)\*/g, "<em>$1</em>")
        .replace(/`([^`]+)`/g, "<code>$1</code>");
      for (const ln of lines) {
        const t = ln.trim();
        if (!t) { flushPara(); closeList(); continue; }
        let m;
        if ((m = t.match(/^(#{1,6})\s+(.+)$/))) {
          flushPara(); closeList();
          out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`);
        } else if (t.match(/^[-*]\s+/)) {
          flushPara();
          if (!inList) { out.push("<ul>"); inList = true; }
          out.push("<li>" + inline(t.replace(/^[-*]\s+/, "")) + "</li>");
        } else if (t === "---") {
          flushPara(); closeList();
          out.push("<hr>");
        } else {
          closeList();
          paraBuf.push(inline(t));
        }
      }
      flushPara(); closeList();
      return out.join("\n");
    },
    async runConsistencyCheck() {
      this.checking = true;
      this.checkError = "";
      this.showCheckPanel = true;
      this.recommendations = [];
      try {
        const r = await api.post("/api/story/quest-givers/consistency-check", {});
        this.checkReport = r.report || "";
        this.recommendations = r.recommendations || [];
        this.checkReportHtml = this._renderMarkdown(this.checkReport);
      } catch (e) {
        this.checkError = "Check fehlgeschlagen: " + (e.message || e);
        this.checkReportHtml = "";
        this.checkReport = "";
        this.recommendations = [];
      } finally {
        this.checking = false;
      }
    },
    closeCheckPanel() {
      this.showCheckPanel = false;
    },
    async applyRecommendation(idx) {
      const rec = this.recommendations[idx];
      if (!rec) return;
      this.applyingIdx = idx;
      this.previewError = "";
      try {
        const r = await api.post(
          "/api/story/quest-givers/apply-recommendation",
          { instruction: rec.instruction }
        );
        this.previewTitle = rec.title;
        this.previewOldContent = this.giversRaw;
        this.previewNewContent = r.new_content || "";
        this.previewOpen = true;
      } catch (e) {
        alert("KI-Edit fehlgeschlagen: " + (e.message || e));
      } finally {
        this.applyingIdx = null;
      }
    },
    async confirmPreview() {
      // Speichert den preview_new als neue QUEST_GIVERS.md (mit .bak-Backup
      // durch den PUT-Endpoint)
      this.previewSaving = true;
      this.previewError = "";
      try {
        await api.put("/api/story/file/QUEST_GIVERS.md",
                      { content: this.previewNewContent });
        // Lokales Raw + Render updaten
        this.giversRaw = this.previewNewContent;
        this._render();
        this.previewOpen = false;
        this.saveMsg = "✓ Übernommen. Backup als .bak abgelegt.";
        setTimeout(() => { this.saveMsg = ""; }, 4000);
        // Konsistenz-Check neu laufen lassen, damit die Liste frisch ist
        this.runConsistencyCheck();
      } catch (e) {
        this.previewError = "Speichern fehlgeschlagen: " + (e.message || e);
      } finally {
        this.previewSaving = false;
      }
    },
    cancelPreview() {
      if (this.previewSaving) return;
      this.previewOpen = false;
      this.previewNewContent = "";
      this.previewError = "";
    },
    async save() {
      this.saving = true;
      this.saveMsg = "";
      this.saveError = false;
      try {
        await api.put(`/api/story/file/${this.currentFilename}`,
                      { content: this.draft });
        // Lokales Raw + Render updaten
        if (this.activeTab === "givers") this.giversRaw = this.draft;
        else this.personnelRaw = this.draft;
        this._render();
        this.editing = false;
        this.draft = "";
        this.saveMsg = "✓ Gespeichert. Backup als .bak abgelegt.";
        setTimeout(() => { this.saveMsg = ""; }, 4000);
      } catch (e) {
        this.saveMsg = "Fehler: " + (e.message || e);
        this.saveError = true;
      } finally {
        this.saving = false;
      }
    },
  };
}

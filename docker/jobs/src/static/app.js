// SEKTOR Personal-Boerse — Alpine.js-Komponente (jobsBoard).
// Ausgelagert aus index.html, damit eine strikte CSP ohne Inline-Skripte
// moeglich ist (script-src 'self'). Muss VOR alpine.min.js geladen werden
// (beide defer -> Ausfuehrung in Dokument-Reihenfolge).
function jobsBoard() {
  return {
    loading: true,
    me: null,
    board: null,
    activeDay: null,
    expanded: {},   // mission_id -> Auftrags-Text aufgeklappt
    briefOpen: {},  // mission_id -> Regie-Details (Personal-Brief) aufgeklappt
    busySlots: {},  // slot_id -> Request laeuft
    myOpen: false,  // Overlay "Meine Eintragungen"
    myStats: null,  // eigene Einsatz-Bilanz (beim Oeffnen des Overlays geladen)
    jumpedTo: null, // mission_id kurz hervorheben nach dem Sprung
    now: Math.floor(Date.now() / 1000),  // tickt, damit "Läuft gerade" umspringt
    statsOpen: false,     // Admin-Auswertung
    statsLoading: false,
    stats: null,
    audit: null,          // Admin-Protokoll (mit der Auswertung geladen)
    clearing: false,      // "Erledigte entfernen" laeuft
    toast: '',
    toastError: false,
    _toastTimer: null,

    // Tage in Wochen-Zeilen gruppieren: pro Kalenderwoche eine Reihe,
    // damit nichts horizontal gescrollt werden muss.
    dayRows() {
      if (!this.board || !this.board.days) return [];
      const rows = [];
      let cur = null;
      for (const d of this.board.days) {
        const key = d.week || d.date;
        if (!cur || cur.week !== key) {
          cur = {
            week: key,
            week_label: d.week_label || '',
            period: d.period,
            period_label: d.period_label || '',
            days: [],
          };
          rows.push(cur);
        }
        cur.days.push(d);
      }
      return rows;
    },

    // Personal-Brief lesbar machen. Der Text kommt als Markdown-artiger
    // Fliesstext aus der KI ("**Mittler:** ... - 1x #6 Tankwart -> Funktion: ...").
    // WICHTIG: erst HTML escapen, dann formatieren — der Text stammt aus
    // der Datenbank und darf niemals als Markup ausgefuehrt werden.
    formatBrief(raw) {
      if (!raw) return '';
      const esc = String(raw)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');

      // Umbrueche erzwingen, falls die KI alles in eine Zeile geschrieben hat:
      // vor jedem bekannten Label, vor "- 1x/2x ..." und vor jedem Pfeil-Detail.
      // Aeltere Briefs sagen noch "Quest-NPCs" -> auf die neue Bezeichnung mappen.
      let t = esc
        .replace(/\*\*Quest-NPCs[^*]*\*\*/g, '**Sektor Questgeber**')
        .replace(/NPC-Spieler/g, 'Questgeber')
        .replace(/\s*---\s*/g, '\n---\n')
        .replace(/\s*(\*\*(?:Mittler|Sektor Questgeber|Slot|Team-Auslastung)[^*]*\*\*)/g, '\n$1')
        .replace(/\s+-\s+(?=\d+\s*[x×])/g, '\n- ')
        .replace(/\s*(?:→|-&gt;)\s*/g, '\n→ ');

      const out = [];
      for (let line of t.split('\n')) {
        line = line.trim();
        if (!line) continue;
        if (line === '---') { out.push('<hr class="my-2 border-[#3d4a4d]/50">'); continue; }
        // **fett**
        line = line.replace(/\*\*(.+?)\*\*/g, '<strong class="text-zinc-200">$1</strong>');
        if (line.startsWith('→ ')) {
          const rest = line.slice(2);
          const m = rest.match(/^([^:]{1,20}):\s*(.*)$/);
          const body = m
            ? '<span class="text-[#d9ae6e]">' + m[1] + ':</span> ' + m[2]
            : rest;
          out.push('<div class="pl-4 text-zinc-400">' + body + '</div>');
        } else if (line.startsWith('- ')) {
          out.push('<div class="mt-1.5 font-medium text-zinc-300">' + line.slice(2) + '</div>');
        } else {
          out.push('<div class="mt-1">' + line + '</div>');
        }
      }
      return out.join('');
    },

    async init() {
      try {
        const r = await fetch('/api/me');
        if (r.ok) {
          this.me = await r.json();
          await this.loadBoard(true);
        }
      } catch (e) { /* nicht eingeloggt / Server weg -> Login-Card */ }
      this.loading = false;

      // Auto-Refresh alle 30s, aber nur wenn der Tab sichtbar ist
      setInterval(() => {
        if (this.me && document.visibilityState === 'visible') this.loadBoard(false);
      }, 30000);
      document.addEventListener('visibilitychange', () => {
        if (this.me && document.visibilityState === 'visible') {
          this.now = Math.floor(Date.now() / 1000);
          this.loadBoard(false);
        }
      });
      // Uhr fuer "Läuft gerade" — unabhaengig vom Board-Refresh, damit das
      // Label auch ohne neue Daten zur richtigen Minute umspringt
      setInterval(() => { this.now = Math.floor(Date.now() / 1000); }, 15000);
    },

    async loadBoard(pickDay) {
      try {
        const r = await fetch('/api/board');
        if (r.status === 401) {
          // Session weg (Logout/Rolle entzogen): Overlays mit schliessen,
          // sonst laegen sie ueber der Login-Karte
          this.me = null; this.board = null;
          this.myOpen = false; this.statsOpen = false;
          return;
        }
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          this.showToast(j.detail || 'Board konnte nicht geladen werden', true);
          return;
        }
        this.board = await r.json();
        // Admin-Status kann sich durch den Rollen-Recheck aendern —
        // das Board liefert den aktuellen Stand mit
        if (this.board.me) this.me = { ...this.me, is_admin: !!this.board.me.is_admin };
        // activeDay kann verschwinden (z.B. Pseudo-Tag "Ausserhalb Event",
        // sobald dessen letzte Mission weg ist) -> sonst leere Seite
        if (pickDay || !this.activeDay
            || !this.board.days.find(d => d.date === this.activeDay)) {
          this.pickDefaultDay();
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
      }
    },

    pickDefaultDay() {
      if (!this.board || !this.board.days.length) return;
      const now = new Date();
      const today = now.getFullYear() + '-'
        + String(now.getMonth() + 1).padStart(2, '0') + '-'
        + String(now.getDate()).padStart(2, '0');
      const hit = this.board.days.find(d => d.date === today);
      this.activeDay = hit ? hit.date : this.board.days[0].date;
    },

    currentDay() {
      if (!this.board) return null;
      return this.board.days.find(d => d.date === this.activeDay) || null;
    },

    myCount() {
      if (!this.board) return 0;
      let n = 0;
      for (const d of this.board.days)
        for (const m of d.missions)
          for (const s of m.slots)
            if (s.mine) n++;
      return n;
    },

    // Alle eigenen Eintragungen fuers "Meine Slots"-Overlay — chronologisch,
    // mit Tag und Auftrag als Kontext. Keine zusaetzliche Abfrage noetig:
    // die Daten stecken bereits im geladenen Board.
    mySlots() {
      if (!this.board) return [];
      const meId = this.me && this.me.discord_user_id;
      const out = [];
      for (const d of this.board.days) {
        for (const m of d.missions) {
          for (const s of m.slots) {
            if (s.mine) {
              // Mitspieler im selben Slot (ohne mich)
              const others = (s.assigned || [])
                .filter(a => a.player_discord_id !== meId)
                .map(a => a.username);
              out.push({ slot: s, mission: m, dayLabel: d.label, date: d.date, others });
            }
          }
        }
      }
      return out;
    },

    // ---- Admin-Funktionen (Server prueft die Berechtigung erneut) ----
    async openStats() {
      this.statsOpen = true;
      this.statsLoading = true;
      try {
        const [r, rAudit] = await Promise.all([
          fetch('/api/admin/stats'),
          fetch('/api/admin/audit'),
        ]);
        if (r.ok) {
          this.stats = await r.json();
          this.audit = rAudit.ok ? await rAudit.json() : null;
        } else {
          const j = await r.json().catch(() => ({}));
          this.showToast(j.detail || 'Auswertung nicht verfügbar', true);
          this.statsOpen = false;
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
        this.statsOpen = false;
      }
      this.statsLoading = false;
    },

    // Protokoll-Zeile lesbar machen
    auditLabel(a) {
      const wer = a.target_username ? '„' + a.target_username + '“' : '';
      const slot = a.slot_id ? ' (Slot ' + a.slot_id + ')' : '';
      if (a.action === 'kick') return 'hat ' + wer + ' ausgetragen' + slot;
      if (a.action === 'attendance')
        return 'hat ' + wer + ' als „' + a.details + '“ markiert' + slot;
      if (a.action === 'clear_completed') return 'hat aufgeräumt: ' + a.details;
      return a.action + (a.details ? ': ' + a.details : '');
    },

    // ISO-Zeit kurz: "23.07. 21:15"
    dateTimeShort(iso) {
      if (!iso) return '';
      const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
      if (isNaN(d)) return '';
      return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
        + ' ' + d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    },

    async clearCompleted() {
      if (this.clearing) return;
      if (!confirm('Alle erledigten Aufträge vom Board entfernen?\n\n'
                 + 'Die Aufträge selbst bleiben im Crime-Dashboard bestehen, '
                 + 'und die Auswertung behält alle Einsätze.')) return;
      this.clearing = true;
      try {
        const r = await fetch('/api/admin/clear-completed', { method: 'POST' });
        const j = await r.json().catch(() => ({}));
        if (r.ok) {
          this.showToast(j.detail || 'Erledigte Aufträge entfernt', false);
          await this.loadBoard(false);
        } else {
          this.showToast(j.detail || 'Entfernen fehlgeschlagen', true);
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
      }
      this.clearing = false;
    },

    // ISO-Datum kurz darstellen (fuer die Auswertungstabelle)
    dateShort(iso) {
      if (!iso) return '—';
      const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
      if (isNaN(d)) return '—';
      return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' });
    },

    // Laeuft das Einsatzfenster gerade? Nutzt this.now, damit Alpine das
    // Label beim Ticken neu bewertet. Archivierte Auftraege laufen nicht mehr.
    isRunning(mission) {
      if (!mission || mission.archived_at) return false;
      const start = mission.window_start;
      const end = mission.window_end;
      if (!start || !end) return false;
      return this.now >= start && this.now <= end;
    },

    // Text auf N Zeichen kuerzen, ohne mitten im Wort zu schneiden
    shorten(text, max) {
      const t = (text || '').replace(/\s+/g, ' ').trim();
      if (t.length <= max) return t;
      const cut = t.slice(0, max);
      const lastSpace = cut.lastIndexOf(' ');
      return (lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut) + ' …';
    },

    // Aus dem Overlay zum Auftrag im Kalender springen: Overlay zu,
    // richtigen Tag waehlen, Auftragstext aufklappen, hinscrollen und
    // kurz hervorheben.
    jumpToMission(entry) {
      this.myOpen = false;
      this.activeDay = entry.date;
      this.expanded[entry.mission.id] = true;
      this.$nextTick(() => {
        const el = document.getElementById('mission-' + entry.mission.id);
        if (!el) return;
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        this.jumpedTo = entry.mission.id;
        setTimeout(() => { this.jumpedTo = null; }, 2500);
      });
    },

    eventLabel() {
      if (!this.board || !this.board.event) return '';
      const f = (iso) => {
        const d = new Date(iso);
        return String(d.getDate()).padStart(2, '0') + '.'
          + String(d.getMonth() + 1).padStart(2, '0') + '.' + d.getFullYear();
      };
      return 'Event: ' + f(this.board.event.start) + ' – ' + f(this.board.event.end);
    },

    async assign(slot, mission) {
      if (this.busySlots[slot.id]) return;
      this.busySlots[slot.id] = true;
      try {
        const r = await fetch('/api/slots/' + slot.id + '/assign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mission_id: mission.id }),
        });
        if (r.status === 201) {
          this.showToast('Eingetragen: ' + (slot.name || 'Slot'), false);
        } else {
          const j = await r.json().catch(() => ({}));
          this.showToast(j.detail || 'Eintragen fehlgeschlagen', true);
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
      }
      this.busySlots[slot.id] = false;
      await this.loadBoard(false);
    },

    async unassign(slot) {
      if (this.busySlots[slot.id]) return;
      this.busySlots[slot.id] = true;
      try {
        const r = await fetch('/api/slots/' + slot.id + '/assign', { method: 'DELETE' });
        if (r.status === 204) {
          this.showToast('Ausgetragen: ' + (slot.name || 'Slot'), false);
        } else {
          const j = await r.json().catch(() => ({}));
          this.showToast(j.detail || 'Austragen fehlgeschlagen', true);
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
      }
      this.busySlots[slot.id] = false;
      await this.loadBoard(false);
    },

    // "Meine Slots" oeffnen + eigene Bilanz nachladen (best effort)
    async openMy() {
      this.myOpen = true;
      try {
        const r = await fetch('/api/me/stats');
        this.myStats = r.ok ? await r.json() : null;
      } catch (e) {
        this.myStats = null;  // Bilanz ist optional — Overlay bleibt nutzbar
      }
    },

    // Warteliste: beitreten/verlassen. Nachruecken macht der Server (FIFO + DM).
    async joinWaitlist(slot, mission) {
      if (this.busySlots[slot.id]) return;
      this.busySlots[slot.id] = true;
      try {
        const r = await fetch('/api/slots/' + slot.id + '/waitlist', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mission_id: mission.id }),
        });
        if (r.status === 201) {
          this.showToast('Auf der Warteliste: ' + (slot.name || 'Slot')
                       + ' — du rückst automatisch nach', false);
        } else {
          const j = await r.json().catch(() => ({}));
          this.showToast(j.detail || 'Warteliste fehlgeschlagen', true);
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
      }
      this.busySlots[slot.id] = false;
      await this.loadBoard(false);
    },

    async leaveWaitlist(slot) {
      if (this.busySlots[slot.id]) return;
      this.busySlots[slot.id] = true;
      try {
        const r = await fetch('/api/slots/' + slot.id + '/waitlist', { method: 'DELETE' });
        if (r.status === 204) {
          this.showToast('Von der Warteliste ausgetragen', false);
        } else {
          const j = await r.json().catch(() => ({}));
          this.showToast(j.detail || 'Austragen fehlgeschlagen', true);
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
      }
      this.busySlots[slot.id] = false;
      await this.loadBoard(false);
    },

    // Anwesenheit durchschalten: offen -> erschienen -> No-Show -> offen.
    // Lokal sofort umschalten (kein Board-Reload), der Server prueft is_admin.
    async cycleAttendance(slot, player) {
      const next = player.attended === 1 ? false : player.attended === 0 ? null : true;
      try {
        const r = await fetch(
          '/api/admin/attendance/' + slot.id + '/' + player.player_discord_id,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ attended: next }),
          }
        );
        if (r.ok) {
          player.attended = next === null ? null : (next ? 1 : 0);
        } else {
          const j = await r.json().catch(() => ({}));
          this.showToast(j.detail || 'Anwesenheit speichern fehlgeschlagen', true);
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
      }
    },

    // Admin-Kick: fremdes Assignment entfernen (Server prueft is_admin)
    async adminKick(slot, player) {
      if (!confirm('„' + player.username + '“ wirklich aus diesem Slot austragen?')) return;
      try {
        const r = await fetch(
          '/api/admin/assignments/' + slot.id + '/' + player.player_discord_id,
          { method: 'DELETE' }
        );
        if (r.status === 204) {
          this.showToast('Ausgetragen (Admin): ' + player.username, false);
        } else {
          const j = await r.json().catch(() => ({}));
          this.showToast(j.detail || 'Austragen fehlgeschlagen', true);
        }
      } catch (e) {
        this.showToast('Verbindung zum Server fehlgeschlagen', true);
      }
      await this.loadBoard(false);
    },

    showToast(msg, isError) {
      this.toast = msg;
      this.toastError = !!isError;
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => { this.toast = ''; }, 4000);
    },
  };
}

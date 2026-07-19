# 🤖 Discord-Bot Setup — Schritt für Schritt

**Komplette Anleitung — auch wenn du noch nie einen Bot eingerichtet hast.**

Diese Anleitung führt dich von Null bis zum laufenden Discord-Bot. Jeder Schritt enthält genau, was du klicken sollst und was du sehen musst. Wenn dir was unklar ist, scrolle ans Ende zu „Häufige Fehler".

## Inhalt

1. [Was du vorher haben musst](#0-was-du-vorher-haben-musst)
2. [Schritt 1: Discord Developer Portal öffnen](#1-discord-developer-portal-öffnen)
3. [Schritt 2: Bot-Application erstellen](#2-bot-application-erstellen)
4. [Schritt 3: Bot-Profil einrichten](#3-bot-profil-einrichten-name--avatar)
5. [Schritt 4: Privileged Gateway Intents aktivieren](#4-privileged-gateway-intents-aktivieren-wichtigster-schritt)
6. [Schritt 5: Bot-Token kopieren](#5-bot-token-kopieren-streng-geheim)
7. [Schritt 6: Token in `.env` eintragen](#6-token-in-env-eintragen)
8. [Schritt 7: OAuth2 URL erstellen](#7-oauth2-url-erstellen-um-den-bot-einzuladen)
9. [Schritt 8: Bot in deinen Server einladen](#8-bot-in-deinen-server-einladen)
10. [Schritt 9: Bot-Rolle im Server konfigurieren](#9-bot-rolle-im-server-konfigurieren)
11. [Schritt 10: Channel-Permissions setzen](#10-channel-permissions-setzen)
12. [Schritt 11: Bot starten und testen](#11-bot-starten-und-testen)
13. [Schritt 12: Im Tool verbinden](#12-im-tool-verbinden)
14. [Notfall: Token wurde geleakt](#-notfall-token-wurde-geleakt)
15. [Häufige Fehler + Lösungen](#häufige-fehler--lösungen)
16. [Schnell-Referenz](#-schnell-referenz)

---

## 0. Was du vorher haben musst

- ✅ Ein **Discord-Account** (kostenlos auf <https://discord.com>)
- ✅ Ein **eigener Discord-Server** (oder Admin-Rechte auf einem)
- ✅ **2-Faktor-Authentifizierung** auf deinem Discord-Account aktiviert (für Bot-Erstellung **erforderlich**)
  - Falls noch nicht: Discord öffnen → ⚙️ Einstellungen → Mein Account → **Zwei-Faktor-Authentifizierung aktivieren**
- ✅ Eine bereits **installierte Kopie** von Crime Automation auf deinem Server (siehe [INSTALLATION.md](INSTALLATION.md))

> 💡 **Tipp:** Discord-Server kostenlos erstellen: Discord öffnen → Plus-Symbol links → „Eigenen Server erstellen". Dauert 30 Sekunden.

---

## 1. Discord Developer Portal öffnen

1. Browser öffnen
2. Gehe zu: **<https://discord.com/developers/applications>**
3. Falls du noch nicht eingeloggt bist: mit deinem Discord-Account einloggen
4. Du landest auf der **„Applications"**-Seite

**Was du sehen solltest:**
- Oben rechts dein Discord-Avatar
- Eine Liste deiner bisherigen Applications (oder leer, wenn das deine erste ist)
- Ein blauer Button **„New Application"** oben rechts

> ⚠️ Falls du keinen Button siehst: 2FA ist nicht aktiv. Aktiviere es zuerst (siehe oben).

---

## 2. Bot-Application erstellen

1. Klicke oben rechts auf **„New Application"**
2. Ein Dialog öffnet sich
3. **Name eingeben** — zum Beispiel: `Il Padrino` oder `SEKT6R Bot` oder dein Custom-Name
   - Der Name kann später noch geändert werden
   - Bot-User-Name (mit `#1234` Tag) wird daraus generiert
4. Häkchen bei **„I agree to the Discord Developer Terms of Service"**
5. **„Create"** klicken

**Was du sehen solltest:**
- Eine neue Seite mit deiner Application
- Links eine Sidebar mit Optionen: General Information, OAuth2, Bot, etc.
- Oben dein eingegebener Name

---

## 3. Bot-Profil einrichten (Name + Avatar)

Optional aber empfohlen — macht den Bot im Server professioneller.

### Auf der „General Information"-Seite

1. **App Icon** hochladen (oben links — das wird der Bot-Avatar im Discord)
   - PNG/JPG, mindestens 512×512 px empfohlen
2. **Description** ausfüllen (z.B. „Crime Automation Bot für SEKT6R RP")
3. **Tags** wählen (optional, z.B. „roleplay", „custom-bot")
4. Ganz unten: **„Save Changes"** klicken (taucht erst auf, wenn was geändert wurde)

### Auf der „Bot"-Seite (linke Sidebar → „Bot")

1. **Username** anpassen (das ist der Anzeigename im Discord, z.B. `Il Padrino`)
2. **Banner** hochladen (optional)
3. **„Public Bot"** — Häkchen entfernen, falls du nicht willst, dass andere den Bot einladen können
   - **Empfehlung**: Häkchen entfernen für privaten Bot
4. **„Requires OAuth2 Code Grant"** — bleibt deaktiviert (nicht nötig)
5. **„Save Changes"** klicken

---

## 4. Privileged Gateway Intents aktivieren (WICHTIGSTER SCHRITT)

**Wenn du das vergisst, funktioniert das Boss-Feedback NICHT.**

1. Bleib auf der **„Bot"**-Seite
2. Scrolle runter zu **„Privileged Gateway Intents"**
3. **Drei Toggles** sind sichtbar:
   - **Presence Intent** — kannst du auslassen
   - **Server Members Intent** — ✅ **aktivieren** (für User-Info bei Boss-Feedback)
   - **Message Content Intent** — ✅ **AKTIVIEREN** (zwingend für Boss-Feedback-Lesen!)
4. Beide Toggles werden grün
5. Discord zeigt einen Warnhinweis: „This intent will be required for bots in 100+ servers." → das ist okay, betrifft dich nicht (du bist auf 1 Server)
6. Scrolle runter und klicke **„Save Changes"**

**Was du sehen solltest:**
- Toggles sind grün
- Speichern-Banner verschwindet

> 🚨 **Häufiger Fehler**: Vergessen → Bot startet, kann aber im Info-Channel keine Texte lesen → Boss-Feedback funktioniert nicht. Beheben: hierher zurück und aktivieren, dann Bot neu starten.

---

## 5. Bot-Token kopieren (STRENG GEHEIM)

> ⚠️ **Sicherheits-Warnung**: Der Bot-Token ist wie ein Passwort. Wer ihn hat, kann den Bot vollständig kontrollieren — Nachrichten löschen, Channels verändern, Bann-Aktionen. NIEMALS:
> - In den Chat schicken
> - Auf GitHub committen (deshalb steht `.env` in `.gitignore`)
> - In Screenshots zeigen
> - Per E-Mail/DM unverschlüsselt teilen

1. Bleib auf der **„Bot"**-Seite
2. Scrolle nach oben zur **„Token"**-Sektion
3. Klicke **„Reset Token"** (auch wenn es das erste Mal ist — der Token wird neu generiert)
   - Discord fragt: „Are you sure?" → **Yes, do it!**
   - Falls 2FA-Code abgefragt wird: aus deiner Authenticator-App eingeben
4. **Token erscheint sichtbar** — eine lange Zeichenkette, etwa so:
   ```
   MTAwMzM0NTY3ODkw.GxYzAB.aBcDeFgHiJkLmNoPqRsTuVwXyZ-1234567890_abcdef
   ```
5. **Klicke „Copy"** rechts neben dem Token → kopiert ihn in die Zwischenablage
6. **WICHTIG**: Sobald du die Seite verlässt, wird der Token **nicht mehr angezeigt**. Wenn du ihn nochmal brauchst, musst du erneut „Reset Token" klicken (und der alte wird ungültig).

> 💡 Empfehlung: Token sofort im nächsten Schritt in `.env` eintragen, **bevor** du den Tab wechselst.

---

## 6. Token in `.env` eintragen

### Wo ist die `.env`-Datei?

Im **Projekt-Root** deines Crime-Automation-Ordners:

```
D:\Crime-Automation\
├── .env                    ← HIER
├── .env.example            ← Vorlage
├── backend\
├── frontend\
└── ...
```

### Falls `.env` noch nicht existiert

```powershell
cd D:\Crime-Automation
Copy-Item .env.example .env
```

Oder unter Linux/macOS:
```bash
cp .env.example .env
```

### Token eintragen

1. Öffne `.env` mit einem **Text-Editor** (Notepad, VS Code, Notepad++, etc.)
   - ⚠️ **Nicht** mit Word/LibreOffice öffnen — die fügen Formatierung ein, die alles kaputtmacht!
2. Suche die Zeile mit `DISCORD_BOT_TOKEN=`
3. Füge deinen kopierten Token **direkt nach dem `=`** ein, **ohne Leerzeichen** und **ohne Anführungszeichen**:

   ✅ **Richtig:**
   ```env
   DISCORD_BOT_TOKEN=MTAwMzM0NTY3ODkw.GxYzAB.aBcDeFgHiJkLmNoPqRsTuVwXyZ-1234567890_abcdef
   ```

   ❌ **Falsch** (mit Leerzeichen):
   ```env
   DISCORD_BOT_TOKEN = MTAwMzM0NTY3ODkw.GxYzAB...
   ```

   ❌ **Falsch** (mit Anführungszeichen):
   ```env
   DISCORD_BOT_TOKEN="MTAwMzM0NTY3ODkw.GxYzAB..."
   ```

4. **Speichern** (Strg+S in Notepad/VSCode)

### Vollständige Minimal-`.env`

```env
# Discord Bot — DIESEN TOKEN GEHEIM HALTEN
DISCORD_BOT_TOKEN=MTAwMzM0NTY3ODkw.GxYzAB.aBcDeFgHiJkLmNoPqRsTuVwXyZ-1234567890_abcdef

# Admin-Login fürs Tool — eigenes Passwort wählen!
ADMIN_USERNAME=admin
ADMIN_PASSWORD=mein_super_sicheres_passwort_min_16_zeichen

# KI (optional — kann auch später im Web-UI gesetzt werden)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

> 💡 **Passwort-Tipp:** Mindestens 16 Zeichen, gemischt aus Groß-/Kleinbuchstaben, Zahlen, Sonderzeichen. Online-Generator: <https://www.lastpass.com/features/password-generator>

---

## 7. OAuth2 URL erstellen (um den Bot einzuladen)

Jetzt brauchst du eine **Einladungs-URL**, mit der du den Bot auf deinen Server holst.

### Im Discord Developer Portal

1. Linke Sidebar → **„OAuth2"** → **„URL Generator"** (Unter-Menüpunkt)
2. Unter **„Scopes"** Häkchen setzen bei:
   - ✅ **bot**
   - ✅ **applications.commands** (optional, für zukünftige Slash-Commands)

> 🚨 **Häufiger Fehler**: Vergessen, das `bot`-Häkchen zu setzen → URL erlaubt Bot-Einladung nicht.

3. Nachdem du **bot** ankreuzt, erscheint eine zweite Box: **„Bot Permissions"**
4. Setze Häkchen bei:

   | Permission | Wofür |
   |---|---|
   | ✅ **View Channels** | Channels sehen (sonst sieht der Bot nichts) |
   | ✅ **Send Messages** | Aufträge senden |
   | ✅ **Embed Links** | Embeds für Aufträge + Ranking |
   | ✅ **Attach Files** | Bilder zu Aufträgen |
   | ✅ **Read Message History** | Boss-Feedback-Backlog lesen |
   | ✅ **Add Reactions** | 👍/👎/❌ als initiale Reaktionen setzen |
   | ✅ **Manage Messages** | Reaktions-Cleanup (Single-Vote-Enforcement) |

5. **Ganz unten** wird automatisch eine **„Generated URL"** angezeigt — sie sieht so aus:
   ```
   https://discord.com/api/oauth2/authorize?client_id=1234567890123456789&permissions=274877985856&scope=bot%20applications.commands
   ```
6. **Klicke „Copy"** rechts neben der URL → in Zwischenablage

---

## 8. Bot in deinen Server einladen

1. **Kopierte URL** in einem neuen Browser-Tab öffnen
2. Eine Discord-Authorize-Seite öffnet sich
3. **„Add to Server"-Dropdown** öffnet sich
4. Wähle deinen Server aus der Liste
   - ⚠️ Falls Server nicht in der Liste: du brauchst **Admin-Rechte** auf dem Server, sonst kannst du dort keine Bots einladen
5. Klicke **„Continue"** (oder ähnlich)
6. **Permissions-Übersicht** zeigt nochmal, was du erlaubst → **„Authorize"** klicken
7. ggf. **Captcha** lösen (Discord-Bot-Schutz)
8. Erfolgsmeldung: **„Authorized"** → das Tab kannst du schließen

### Verifikation im Discord-Server

1. Discord öffnen
2. Deinen Server auswählen
3. Rechte Sidebar zeigt die **Mitgliederliste** — dein Bot sollte da als **online (grüner Punkt)** angezeigt werden... ⚠️ falls er **offline (grauer Punkt)** ist: das ist normal, weil das Crime-Automation-Skript noch nicht läuft. Das machen wir in Schritt 11.

---

## 9. Bot-Rolle im Server konfigurieren

Wenn der Bot zum Server beitritt, wird automatisch eine **Rolle mit dem Bot-Namen** erstellt. Diese Rolle hat die Permissions, die du in Schritt 7 eingestellt hast.

### Was du prüfen sollst

1. **Server-Einstellungen** öffnen (Server-Name oben → Pfeil nach unten → Server-Einstellungen)
2. Linke Sidebar → **„Rollen"**
3. Die Bot-Rolle (heißt wie dein Bot, z.B. `Il Padrino`) finden
4. Klicke drauf → **Permissions-Tab**
5. **Stelle sicher**, dass folgende Permissions aktiv sind:
   - ✅ View Channels
   - ✅ Send Messages
   - ✅ Embed Links
   - ✅ Attach Files
   - ✅ Read Message History
   - ✅ Add Reactions
   - ✅ Manage Messages

> 💡 Falls das nicht stimmt: Häkchen setzen + **„Änderungen speichern"** klicken.

### Bot-Rolle nach oben verschieben (optional, aber empfohlen)

Damit der Bot **deine eigenen Channels editieren** kann, sollte seine Rolle **über** den User-Rollen stehen.

1. Im Rollen-Tab: die Bot-Rolle per **Drag-and-Drop nach oben** ziehen
2. Über alle „normalen User"-Rollen, aber **unter** „Server-Owner" und „Admin"
3. **Änderungen speichern**

---

## 10. Channel-Permissions setzen

Manchmal überschreiben Channel-spezifische Permissions die Bot-Rollen-Permissions. Stelle sicher, dass der Bot in **jedem benutzten Channel** Posts machen darf.

### Pro Channel prüfen

1. Im Discord-Server: **Rechtsklick** auf den Channel (z.B. `#aufträge-vipers`)
2. → **„Channel bearbeiten"**
3. → **„Berechtigungen"**
4. Liste der Rollen + Permissions
5. Bot-Rolle finden (oder hinzufügen falls fehlend)
6. **Permissions setzen:**
   - ✅ Channel anzeigen
   - ✅ Nachrichten senden
   - ✅ Embeds einbetten
   - ✅ Anhänge senden
   - ✅ Nachrichtenverlauf lesen
   - ✅ Reaktionen hinzufügen
   - ✅ Nachrichten verwalten
7. **Änderungen speichern**

### Schnellweg: alle Aufträge-Channels in einer Kategorie

Wenn du eine **Kategorie** für alle Auftragskanäle hast (z.B. `📂 Crime-Automation`):

1. Rechtsklick auf die **Kategorie**
2. → „Kategorie bearbeiten" → „Berechtigungen"
3. Bot-Rolle hinzufügen mit allen oben genannten Permissions
4. **Sync down to channels** (synchronisiert auf alle Channels darunter)

---

## 11. Bot starten und testen

### Tool starten

#### Falls du als Windows-Service installiert hast

```powershell
Start-Service CrimeAutoBot
Start-Service CrimeAutoBackend
```

#### Falls du manuell startest

In **zwei Terminals** (beide im Projekt-Root mit aktiviertem venv):

```bash
# Terminal 1 — Backend
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — Bot
python -m backend.bot
```

#### Quick-Start (Windows)

```cmd
scripts\run_all.bat
```

### Verifikation

#### 1. Bot-Health prüfen

Im Browser: <http://127.0.0.1:8001/health>

Erwartete Antwort:
```json
{ "ok": true, "ready": true }
```

- `ok: true` → Bot-Prozess läuft
- `ready: true` → Discord-Verbindung steht

#### 2. Bot im Discord-Server prüfen

1. Discord öffnen → Server → Mitgliederliste rechts
2. Bot sollte **grünen Punkt** (online) haben

#### 3. Bot-Log prüfen

```powershell
Get-Content logs\bot.log -Tail 20
```

Erwartete Zeilen:
```
2026-06-14 13:00:00 [crime-bot] Bot HTTP API auf http://127.0.0.1:8001
2026-06-14 13:00:01 [crime-bot] Bot ready as Il Padrino#4671 (id=...)
```

#### 4. Test-Nachricht aus dem Tool

1. Browser: <http://127.0.0.1:8000>
2. Mit `ADMIN_USERNAME` + `ADMIN_PASSWORD` einloggen
3. **„+ Neue Gang"** anlegen mit deiner Channel-ID
4. Crew anklicken → Tab „Manuell" → Text eingeben → **„An Discord senden"**
5. In Discord sollte die Nachricht im konfigurierten Channel erscheinen, mit 👍/👎/❌ als initialen Reaktionen

---

## 12. Im Tool verbinden

### Channel-IDs sammeln

Für jede Crew brauchst du die **Channel-ID** des Discord-Channels, wo der Bot posten soll.

#### Discord-Entwicklermodus aktivieren

1. Discord öffnen → ⚙️ Einstellungen (unten links)
2. **„Erweitert"** im Menü
3. **„Entwicklermodus"** Toggle aktivieren

#### Channel-ID kopieren

1. **Rechtsklick** auf den Channel
2. **„ID kopieren"** ganz unten im Menü
3. Du hast eine 18-stellige Zahl in der Zwischenablage — etwa: `1515654327459381479`

### Channel-IDs im Tool eintragen

#### Pro Crew

1. Web-UI öffnen → **„+ Neue Gang"**
2. Felder ausfüllen:
   - **Auftrags-Channel-ID** → wo der Bot Aufträge postet
   - **Zusatzinfo-Channel-ID** → wo der Boss Klartext-Antworten schreibt (optional)
3. **Speichern**

#### Globale Channels (in Settings)

1. **Settings** öffnen
2. **🏆 Ranking — Tägliches Posting** → Daily- und Top-3-Channel-IDs eintragen
3. **🎭 Personal-Bedarf — Admin-Channel** → Spielleiter-Channel-ID eintragen
4. Jede Sektion einzeln **Speichern** klicken

### Erfolg!

Du bist fertig 🎉. Der Bot sollte jetzt:
- Aufträge in Crew-Channels posten
- Reaktionen tracken
- Boss-Feedback im Tool sichtbar machen
- Ranking-Embeds täglich posten (wenn aktiviert)
- Personal-Bedarf in Spielleiter-Channel posten

---

## 🚨 NOTFALL: Token wurde geleakt

Wenn du verdächtigen Discord-Bot-Verkehr siehst oder den Token irgendwo öffentlich gemacht hast:

### Sofortmaßnahmen (innerhalb 5 Minuten)

1. **Discord Developer Portal** öffnen → deine Application
2. **Bot**-Seite → **Token**-Sektion
3. **„Reset Token"** klicken → ALTER Token wird sofort ungültig
4. **NEUER Token** wird angezeigt → kopieren
5. **`.env`** öffnen → alten Token mit neuem überschreiben
6. **Bot neu starten:**
   ```powershell
   Restart-Service CrimeAutoBot
   ```
7. Verifikation: Bot wieder online (grüner Punkt)

### Nach-Bereinigung

1. **Discord-Audit-Log** prüfen:
   - Server-Einstellungen → Audit-Log
   - Verdächtige Aktionen vom Bot-User? (Channels gelöscht, Bans, etc.)
2. **Falls Schäden**: Channels wiederherstellen, Bans aufheben
3. **Server-Inhaber benachrichtigen** falls das nicht du selbst bist
4. **Quelle des Leaks finden**:
   - Versehentlich in Git committed? → Git-Historie checken, ggf. Repo neu aufsetzen
   - In Chat gepostet? → Nachricht löschen (auch wenn der Token schon ungültig ist)
   - Anderswo? → Auditieren

---

## Häufige Fehler + Lösungen

### „Bot zeigt grauen Punkt (offline) im Server"

**Mögliche Ursachen:**

1. **Crime-Automation-Bot-Prozess läuft nicht**
   ```powershell
   Get-Service CrimeAutoBot
   # Wenn "Stopped": Start-Service CrimeAutoBot
   ```

2. **Token in `.env` ist falsch oder leer**
   - `.env` öffnen, `DISCORD_BOT_TOKEN=` Wert prüfen
   - Falls leer/falsch: Schritt 5 + 6 wiederholen

3. **Token ist nicht ladbar (Encoding-Problem)**
   - `.env` wurde mit Word/LibreOffice gespeichert → Datei mit Notepad neu erstellen

### „Bot ready=false im Health-Check"

**Ursache:** Bot startet, aber kann sich nicht bei Discord anmelden

**Diagnose:**
```powershell
Get-Content logs\bot.err.log -Tail 30
```

**Häufige Log-Nachrichten:**

- `discord.errors.LoginFailure: Improper token has been passed` → **Token ist falsch** → Schritt 5+6 wiederholen
- `discord.errors.PrivilegedIntentsRequired` → **Message Content Intent nicht aktiviert** → zurück zu Schritt 4
- `WebSocket connection refused` → **Discord-API down** → <https://discordstatus.com> prüfen

### „Bot reagiert nicht auf Befehle / postet nichts"

**Mögliche Ursachen:**

1. **Falsche Channel-ID im Crew/Settings**
   - Discord-Entwicklermodus aktiv?
   - Rechtsklick → ID kopieren funktioniert?
   - ID hat 18 Ziffern (keine Buchstaben)?

2. **Bot-Permissions im Channel fehlen**
   - Schritt 10 wiederholen
   - Channel-Berechtigungen prüfen

3. **Bot ist nicht im Server**
   - Mitgliederliste prüfen
   - Falls weg: OAuth2-URL erneut nutzen (Schritt 7-8)

### „Reaktionen werden nicht erfasst"

**Ursache:** Bot hat **Manage Messages**-Permission nicht

→ Schritt 9-10 wiederholen, Permission ergänzen, Bot neu starten

### „Bot zeigt Embeds als reinen Text"

**Ursache:** Bot hat **Embed Links**-Permission nicht

→ Schritt 9-10 wiederholen

### „Boss-Feedback aus Info-Channel kommt nicht im Tool an"

**Mögliche Ursachen:**

1. **Message Content Intent** nicht aktiviert → Schritt 4 wiederholen, Bot neu starten
2. **Falsche Info-Channel-ID** in der Crew → prüfen, neu eintragen
3. **Bot hat keine Read Message History-Permission** im Info-Channel → Schritt 10

### „Authorize"-Button auf Einladungs-URL klappt nicht

**Mögliche Ursachen:**

1. **2FA nicht aktiv** auf deinem Account → aktivieren
2. **Du hast keine Admin-Rechte** auf dem Ziel-Server → anderen Server wählen oder Admin-Rechte beschaffen
3. **URL ist abgelaufen** → in Schritt 7 neue URL generieren

### „Discord zeigt: Application Bot user has been disabled"

**Ursache:** Discord hat den Bot temporär deaktiviert (Spam-Verdacht oder API-Abuse)

**Fix:**
1. Discord Developer Portal → Application
2. **Status prüfen** (oben)
3. Falls deaktiviert: Discord-Support kontaktieren

### Bot startet — aber im Log kommt sofort `aiohttp.ClientConnectorError`

**Ursache:** Backend hat Bot-Port `8001` belegt oder Bot kann nicht binden

**Diagnose:**
```powershell
netstat -ano | findstr 8001
```

Falls ein anderer Prozess Port 8001 belegt: stoppen oder Bot-Port in `.env` ändern:
```env
BOT_API_PORT=8011
```

(Backend-Code muss dann auch angepasst werden — fortgeschritten.)

### Alles funktioniert, aber Reaktionen sind langsam

**Normalverhalten:**
- Discord-Webhook-Delay: 100–500 ms
- Backend-Polling: alle 5 s
- Maximale Wartezeit: ~ 5 s zwischen Klick und Tool-Update

**Wenn länger:**
- Bot-Health-Check prüfen → `ready: true`?
- Discord-Status prüfen
- Backend-Log auf langsame DB-Queries durchsuchen

---

## 🎯 Schnell-Referenz

Die kürzeste Form, falls du alles schon mal gemacht hast:

### Bot erstellen
1. <https://discord.com/developers/applications> → New Application → Name → Create
2. Bot-Seite → **Message Content Intent ON** → Save
3. Bot-Seite → Reset Token → Copy

### Token eintragen
```env
# .env
DISCORD_BOT_TOKEN=<dein-token>
```

### Bot einladen
1. OAuth2 → URL Generator → Scopes: `bot` + `applications.commands`
2. Permissions: View, Send, Embed, Attach, Read History, Add Reactions, Manage Messages
3. Generated URL → Browser → Authorize

### Bot starten
```powershell
Restart-Service CrimeAutoBot
```

### Testen
<http://127.0.0.1:8001/health> → `{"ok": true, "ready": true}`

### Channel-IDs sammeln
Discord → Einstellungen → Erweitert → Entwicklermodus → Rechtsklick auf Channel → ID kopieren

### Im Tool eintragen
- Pro Crew: Auftrags- + Zusatzinfo-Channel-IDs im Crew-Detail
- Global: Ranking + Personal-Channel-IDs in Settings

---

## Weiterführende Doku

- **[INSTALLATION.md](INSTALLATION.md)** — komplettes Tool-Setup
- **[CONFIGURATION.md](CONFIGURATION.md)** — alle Settings im Detail
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — bei allgemeinen Problemen
- **[ADMIN_GUIDE.md](ADMIN_GUIDE.md)** — Spielleiter-Workflows

## Hilfreiche Discord-Links

- **Developer Portal**: <https://discord.com/developers/applications>
- **Discord-Status**: <https://discordstatus.com>
- **Developer Docs**: <https://discord.com/developers/docs>
- **Permissions-Rechner**: <https://discordapi.com/permissions.html>

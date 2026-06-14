# 🚀 Deployment auf Hostinger KVM 2

Komplette Anleitung um den SEKT6R-Bot-Stack auf einem Hostinger-VPS mit
Docker und Cloudflare zu deployen.

## Inhalt

1. [Architektur-Übersicht](#architektur-übersicht)
2. [Voraussetzungen](#voraussetzungen)
3. [Phase A — VPS vorbereiten](#phase-a--vps-vorbereiten)
4. [Phase B — Source-Code auf VPS kopieren](#phase-b--source-code-auf-vps-kopieren)
5. [Phase C — Stack starten](#phase-c--stack-starten)
6. [Phase D — State-Migration](#phase-d--state-migration)
7. [Phase E — Verifikation](#phase-e--verifikation)
8. [Wartung](#wartung)
9. [Troubleshooting](#troubleshooting)

## Architektur-Übersicht

```
Cloudflare DNS+Proxy (HTTPS, DDoS-Schutz)
        │
        ▼
72.62.63.148 (Hostinger KVM 2, Ubuntu 24.04)
        │
        ▼
Docker-Stack (docker-compose.yml)
├── caddy             ← HTTPS + Reverse-Proxy
├── kommandozentrale  ← Web-Dashboard für alle Bots
├── crime-backend     ← https://crime.bots.sektorrp.eu
├── crime-bot         ← Discord (intern)
├── liberty-relay     ← https://liberty.bots.sektorrp.eu
├── whitelist-bot     ← Discord (intern, → externe DB)
├── ticket-bot        ← https://ticket.bots.sektorrp.eu
└── countdown-bot     ← https://countdown.bots.sektorrp.eu
```

## Voraussetzungen

- ✅ **Hostinger KVM 2** mit Ubuntu 22.04+ (hier: 24.04, IP 72.62.63.148)
- ✅ **Cloudflare DNS** mit 5 A-Records (siehe vorhin angelegt)
- ✅ **SSH-Zugang** zum VPS (Hostinger Browser-Terminal oder eigener SSH-Client)
- ✅ **Discord-Bot-Tokens, API-Keys, DB-Credentials** in den lokalen `.env`-Files
- ✅ **Dev-PC** mit Git, Python (zum Vorbereiten der Sources)

## Phase A — VPS vorbereiten

### 1. SSH-Verbindung

**Option 1: Hostinger Browser-Terminal**
- hPanel → VPS → **„Browser-Terminal"**

**Option 2: Lokaler SSH-Client**
```bash
ssh root@72.62.63.148
# (Initial-Passwort aus hPanel oder dein SSH-Key)
```

### 2. System updaten

```bash
apt update && apt upgrade -y
apt install -y curl git ufw rsync nano
```

### 3. Docker installieren

```bash
# Docker via offizielles Convenience-Script
curl -fsSL https://get.docker.com | sh

# Docker Compose v2 ist bereits dabei. Verifizieren:
docker --version
docker compose version
```

### 4. Firewall (UFW)

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status
```

### 5. Non-Root-User (empfohlen)

```bash
# User anlegen
adduser sekt6r
usermod -aG docker sekt6r
usermod -aG sudo sekt6r

# SSH-Key für sekt6r-User kopieren (falls SSH-Login)
mkdir -p /home/sekt6r/.ssh
cp /root/.ssh/authorized_keys /home/sekt6r/.ssh/
chown -R sekt6r:sekt6r /home/sekt6r/.ssh
chmod 700 /home/sekt6r/.ssh
chmod 600 /home/sekt6r/.ssh/authorized_keys

# Ab jetzt: ssh sekt6r@72.62.63.148
exit
```

## Phase B — Source-Code auf VPS kopieren

### 1. Auf dem Dev-PC: Sources vorbereiten

In Git Bash (Windows):

```bash
cd /d/Crime-Automation
bash docker/migrate_sources.sh
```

Das Script kopiert:
- `D:\V2026_Kofi_Twitch_Script_sanitized` → `docker/liberty/src/`
- `D:\bot` → `docker/whitelist/src/`
- `D:\Ticket Tool` → `docker/ticket/src/`
- `D:\Countdown` → `docker/countdown/src/`

`.env`-Files werden **bewusst ausgeschlossen**.

### 2. Repo zum VPS pushen

Du hast zwei Optionen:

**Option A: Über Git (empfohlen)**
```bash
# Lokal:
cd /d/Crime-Automation
git add docker/
git commit -m "feat(docker): Stack-Setup für VPS-Deployment"
git push origin feat/personnel-bedarf-system

# Auf VPS:
ssh sekt6r@72.62.63.148
mkdir -p ~/sekt6r-stack && cd ~/sekt6r-stack
git clone https://github.com/RDanton21/CrimeJobs-Handler-Liberty-City.git .
git checkout feat/personnel-bedarf-system
cd docker
```

**Option B: Über SCP**
```bash
# Lokal:
cd /d/Crime-Automation
scp -r docker sekt6r@72.62.63.148:~/sekt6r-stack/

# Plus das Crime-Automation Repo selbst für Crime-Backend:
scp -r backend frontend docs requirements.txt sekt6r@72.62.63.148:~/sekt6r-stack/
```

### 3. `.env` befüllen

Auf dem VPS:

```bash
cd ~/sekt6r-stack/docker
cp .env.example .env
nano .env
```

Trage alle Werte ein:
- Discord-Bot-Tokens (1 pro Bot — auf [discord.com/developers](https://discord.com/developers) generieren)
- Anthropic + OpenAI API-Keys
- Twitch + Ko-fi Credentials für Liberty
- DB-Host/User/Pass für Whitelist (sektorrp.eu Webspace)
- Admin-Passwörter

Speichern: **Strg+O** → **Enter** → **Strg+X**

> 🔒 **Sicherheit:** Deine lokale `.env` wird durch `migrate_sources.sh` NICHT
> mitkopiert. Du trägst die Werte einmal hier ein, sie bleiben auf dem VPS.

## Phase C — Stack starten

```bash
cd ~/sekt6r-stack/docker

# Build + Start aller Services (erste Mal: ~ 15 Min wegen Ticket-Bot)
docker compose up -d --build

# Status anschauen
docker compose ps

# Logs aller Services
docker compose logs -f

# Logs eines einzelnen Services
docker compose logs -f crime-backend
docker compose logs -f ticket-bot
```

Erwartung beim ersten Build:
- caddy: schnell (~ 30s)
- crime-backend + crime-bot: ~ 2 Min
- liberty: ~ 1 Min
- whitelist: ~ 30s
- ticket: ~ 10-15 Min (torch + transformers + Modell-Download)
- countdown: ~ 30s
- kommandozentrale: ~ 1 Min

## Phase D — State-Migration

Falls du **bestehende Daten** (Crime-DB, Liberty-State, etc.) mitnehmen willst:

### 1. Lokal exportieren

```powershell
# Windows-PowerShell als Admin
Stop-Service CrimeAutoBackend, CrimeAutoBot, LibertyCityRelay

# Crime-DB
Copy-Item D:\Crime-Automation\data\crime.db crime-export.db

# Liberty JSON-State
Compress-Archive -Path D:\V2026_Kofi_Twitch_Script_sanitized\*.json `
                       -DestinationPath liberty-state.zip

# Countdown JSON-State
Compress-Archive -Path D:\Countdown\countdowns.json,D:\Countdown\state.json `
                       -DestinationPath countdown-state.zip

# Ticket-KB
Compress-Archive -Path "D:\Ticket Tool\kb" `
                       -DestinationPath ticket-kb.zip
```

### 2. Auf VPS hochladen

```bash
# Lokal:
scp crime-export.db sekt6r@72.62.63.148:~/migration/
scp liberty-state.zip sekt6r@72.62.63.148:~/migration/
scp countdown-state.zip sekt6r@72.62.63.148:~/migration/
scp ticket-kb.zip sekt6r@72.62.63.148:~/migration/
```

### 3. In Docker-Volumes importieren

Auf VPS:

```bash
cd ~/sekt6r-stack/docker

# Crime-DB in Volume kopieren
docker compose stop crime-backend crime-bot
docker run --rm -v sekt6r-stack_crime_data:/data \
    -v ~/migration:/import alpine \
    cp /import/crime-export.db /data/crime.db
docker compose start crime-backend crime-bot

# Liberty State
docker compose stop liberty-relay
docker run --rm -v sekt6r-stack_liberty_data:/data \
    -v ~/migration:/import alpine \
    sh -c "cd /data && unzip /import/liberty-state.zip"
docker compose start liberty-relay

# Countdown State
docker compose stop countdown-bot
docker run --rm -v sekt6r-stack_countdown_data:/data \
    -v ~/migration:/import alpine \
    sh -c "cd /data && unzip /import/countdown-state.zip"
docker compose start countdown-bot

# Ticket-KB
docker compose stop ticket-bot
docker run --rm -v sekt6r-stack_ticket_kb:/data \
    -v ~/migration:/import alpine \
    sh -c "cd /data && unzip /import/ticket-kb.zip"
docker compose start ticket-bot
```

## Phase E — Verifikation

### 1. Container-Status

```bash
docker compose ps
# Alle sollten "running" sein
```

### 2. Health-Checks

```bash
# Backend-API
curl https://crime.bots.sektorrp.eu/api/health
# {"ok":true}

curl https://bots.sektorrp.eu/api/health
# {"ok":true}
```

### 3. Discord-Bot online?

In deinem Discord-Server schauen:
- Il Padrino sollte grünen Punkt haben
- Whitelist-Bot, Ticket-Bot, Countdown-Bot ebenfalls
- Liberty postet im Donation-Channel (falls Ko-fi-Webhook konfiguriert)

### 4. Web-UIs

Im Browser öffnen:
- https://bots.sektorrp.eu → Kommandozentrale
- https://crime.bots.sektorrp.eu → Crime-Tool
- https://liberty.bots.sektorrp.eu → Liberty Admin
- https://ticket.bots.sektorrp.eu → Ticket-Panel
- https://countdown.bots.sektorrp.eu → Countdown-Manager

Alle sollten HTTPS-grünes-Schloss zeigen und Login-Prompt anzeigen.

### 5. Lokal abschalten

Nach erfolgreicher VPS-Verifikation auf dem Windows-PC:

```powershell
# Als Admin
Stop-Service CrimeAutoBackend, CrimeAutoBot, LibertyCityRelay, S6-WLH-Bot

# Optional: Auto-Start deaktivieren
Set-Service CrimeAutoBackend -StartupType Disabled
Set-Service CrimeAutoBot -StartupType Disabled
Set-Service LibertyCityRelay -StartupType Disabled
```

## Wartung

### Updates ausrollen

```bash
ssh sekt6r@72.62.63.148
cd ~/sekt6r-stack
git pull
cd docker
docker compose up -d --build
```

### Container restarten

```bash
docker compose restart crime-backend     # einzeln
docker compose restart                    # alle
```

### Logs

```bash
docker compose logs -f --tail 100 crime-backend
docker compose logs -f --tail 50 ticket-bot
```

Logs aus dem Kommandozentrale-Dashboard sind genauso live verfügbar.

### Backups

```bash
# Volume-Snapshot (DB + State)
docker run --rm \
    -v sekt6r-stack_crime_data:/source:ro \
    -v ~/backups:/backup \
    alpine tar czf /backup/crime-$(date +%F).tar.gz -C /source .

# Cronjob für täglich um 04:00
crontab -e
# Zeile eintragen:
0 4 * * * docker run --rm -v sekt6r-stack_crime_data:/source:ro -v /home/sekt6r/backups:/backup alpine tar czf /backup/crime-$(date +\%F).tar.gz -C /source .
```

### Hostinger-Snapshots

Bequemer: im hPanel → VPS → Snapshots → manuell oder automatisch (1,30 €/Monat).

## Troubleshooting

### Container startet nicht — Logs anschauen

```bash
docker compose logs crime-backend --tail 50
```

### Caddy holt kein Zertifikat

Cloudflare Proxy interferiert mit Let's Encrypt HTTP-01-Challenge.

**Lösung:** Cloudflare → SSL/TLS → **Origin Server** → eigenes Cert generieren ODER Cloudflare-Mode auf **„Full"** statt **„Full (strict)"** umstellen.

### Discord-Bot offline

```bash
# Logs prüfen
docker compose logs crime-bot --tail 30

# Token in .env korrekt?
docker compose exec crime-bot env | grep DISCORD
```

### Whitelist-DB nicht erreichbar

Der externe DB-Hoster muss Verbindungen von **72.62.63.148** erlauben.

Bei sektorrp.eu Webspace:
- DB-Verwaltung → MySQL-Settings → Remote Access → IP `72.62.63.148` eintragen

### Stack komplett zurücksetzen (DELETE ALL)

```bash
docker compose down -v   # ⚠️ löscht alle Volumes inkl. DBs!
docker compose up -d --build
```

### Bestimmten Service neu bauen

```bash
docker compose build --no-cache ticket-bot
docker compose up -d ticket-bot
```

## Was als Nächstes?

- **Cloudflare-Tunnel** statt offener Ports 80/443 — extra Sicherheit
- **Redis** im Stack für Cross-Bot-Events (Twitch-Donations → Crime-Bonus etc.)
- **Zentrale User-DB** für Unified-Profile über alle Bots
- **Monitoring** mit Grafana + Prometheus

Siehe ROADMAP.md im Hauptrepo für die geplanten Phasen 2+3.

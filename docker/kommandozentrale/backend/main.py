"""
SEKT6R Kommandozentrale — Backend

Web-Dashboard zum Steuern + Monitoren aller Bot-Container im VPS-Stack.
Kommuniziert mit Docker-Engine über /var/run/docker.sock.

Features:
- Status aller Container (Running/Stopped/Health)
- Restart/Start/Stop pro Container
- Live-Logs (Tail-N)
- System-Stats (CPU, RAM, Disk vom Host)
- Quick-Links zu allen Bot-UIs
"""
from __future__ import annotations

import asyncio
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

import docker
import psutil
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

if not ADMIN_PASSWORD:
    raise RuntimeError(
        "ADMIN_PASSWORD muss gesetzt sein! "
        "Bitte in .env beim Service kommandozentrale eintragen."
    )

# Bot-Service-Namen aus docker-compose.yml (mit Container-Prefix "sekt6r-")
BOT_SERVICES = {
    "crime-backend": {
        "container": "sekt6r-crime-backend",
        "label": "Il Padrino",
        "icon": "🎭",
        "ui_url": "https://crime.bots.sektorrp.eu",
        "kind": "web",
    },
    "crime-bot": {
        "container": "sekt6r-crime-bot",
        "label": "Il Padrino Discord-Bot",
        "icon": "🤖",
        "ui_url": None,
        "kind": "discord",
    },
    # ------------------------------------------------------------------
    # ACHTUNG — liberty-relay ist hier bewusst AUSGEBLENDET (18.07.2026).
    # Liberty laeuft nativ auf dem Dedicated (NSSM-Service LibertyCityRelay).
    # Wird der Docker-Container zusaetzlich gestartet, laufen zwei Instanzen
    # parallel: doppeltes Tebex-Polling, doppelte Ko-Fi-Verarbeitung und
    # doppelte Discord-Posts. Erst den Dedicated-Service stoppen, dann hier
    # wieder einkommentieren.
    # ------------------------------------------------------------------
    # "liberty-relay": {
    #     "container": "sekt6r-liberty",
    #     "label": "Du bist Liberty",
    #     "icon": "🗽",
    #     "ui_url": "https://liberty.bots.sektorrp.eu/admin/",
    #     "kind": "web",
    # },
    "jobs-dashboard": {
        "container": "sekt6r-jobs",
        "label": "Personal-Boerse",
        "icon": "📋",
        "ui_url": "https://jobs.bots.sektorrp.eu",
        "kind": "web",
    },
    "whitelist-bot": {
        "container": "sekt6r-whitelist",
        "label": "Whitelist-Sync",
        "icon": "✅",
        "ui_url": None,
        "kind": "discord",
    },
    "ticket-bot": {
        "container": "sekt6r-ticket",
        "label": "Ticket-System",
        "icon": "🎫",
        "ui_url": None,
        "kind": "discord",
    },
    "countdown-bot": {
        "container": "sekt6r-countdown",
        "label": "Countdown",
        "icon": "⏰",
        "ui_url": None,
        "kind": "discord",
    },
}


# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    correct_user = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_pass = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# -----------------------------------------------------------------------------
# Docker-Client
# -----------------------------------------------------------------------------
docker_client = docker.from_env()


def get_container_status(service_name: str) -> dict[str, Any]:
    """Aktueller Status eines Bot-Containers."""
    svc = BOT_SERVICES.get(service_name)
    if not svc:
        return {"error": "unknown service"}
    try:
        c = docker_client.containers.get(svc["container"])
        attrs = c.attrs or {}
        state = attrs.get("State", {})
        # Health
        health = state.get("Health", {}).get("Status") if state.get("Health") else None
        # Uptime
        started_at = state.get("StartedAt", "")
        # CPU + RAM (snapshot, kein Streaming)
        stats = None
        try:
            stats = c.stats(stream=False)
        except Exception:
            pass
        cpu_pct = 0.0
        mem_used = 0
        mem_limit = 0
        if stats:
            cpu_pct = _calc_cpu_pct(stats)
            mem_used = stats.get("memory_stats", {}).get("usage", 0)
            mem_limit = stats.get("memory_stats", {}).get("limit", 0)
        return {
            "service": service_name,
            "container": svc["container"],
            "label": svc["label"],
            "icon": svc["icon"],
            "kind": svc["kind"],
            "ui_url": svc["ui_url"],
            "status": c.status,
            "health": health,
            "started_at": started_at,
            "image": (attrs.get("Config", {}) or {}).get("Image", ""),
            "cpu_percent": round(cpu_pct, 1),
            "mem_used_mb": round(mem_used / (1024 * 1024), 1),
            "mem_limit_mb": round(mem_limit / (1024 * 1024), 1) if mem_limit else None,
        }
    except docker.errors.NotFound:
        return {
            "service": service_name,
            "container": svc["container"],
            "label": svc["label"],
            "icon": svc["icon"],
            "kind": svc["kind"],
            "ui_url": svc["ui_url"],
            "status": "not_found",
            "health": None,
            "started_at": None,
            "image": None,
            "cpu_percent": 0,
            "mem_used_mb": 0,
            "mem_limit_mb": None,
        }
    except Exception as exc:
        return {
            "service": service_name,
            "container": svc["container"],
            "label": svc["label"],
            "icon": svc["icon"],
            "status": "error",
            "error": str(exc),
        }


def _calc_cpu_pct(stats: dict[str, Any]) -> float:
    """Docker-Stats-Antwort hat Delta-Werte — wir berechnen daraus den CPU-Prozentsatz."""
    try:
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        sys_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        cpus = stats["cpu_stats"].get("online_cpus", 1) or 1
        if sys_delta > 0 and cpu_delta > 0:
            return (cpu_delta / sys_delta) * cpus * 100.0
    except (KeyError, ZeroDivisionError, TypeError):
        pass
    return 0.0


# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------
app = FastAPI(title="SEKT6R Kommandozentrale", version="2.0")


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/services")
async def list_services(_user: str = Depends(require_admin)):
    """Status aller Bot-Container."""
    return [get_container_status(name) for name in BOT_SERVICES.keys()]


@app.get("/api/services/{service}/status")
async def service_status(service: str, _user: str = Depends(require_admin)):
    return get_container_status(service)


def _do_restart(container_name: str) -> None:
    """Sync-Wrapper für docker.restart — wird über asyncio.to_thread im Pool ausgeführt,
    damit der Event-Loop nicht blockiert während der Container neu startet."""
    c = docker_client.containers.get(container_name)
    c.restart(timeout=10)


def _do_start(container_name: str) -> None:
    c = docker_client.containers.get(container_name)
    c.start()


def _do_stop(container_name: str) -> None:
    c = docker_client.containers.get(container_name)
    c.stop(timeout=10)


@app.post("/api/services/{service}/restart")
async def restart_service(service: str, _user: str = Depends(require_admin)):
    svc = BOT_SERVICES.get(service)
    if not svc:
        raise HTTPException(404, "Unknown service")
    try:
        # In Threadpool ausführen damit der FastAPI-Event-Loop nicht blockiert,
        # während Docker den Container neu startet (kann 5-30 Sek dauern).
        await asyncio.to_thread(_do_restart, svc["container"])
        return {"ok": True, "service": service, "action": "restarted"}
    except docker.errors.NotFound:
        raise HTTPException(404, f"Container {svc['container']} nicht gefunden")
    except Exception as exc:
        raise HTTPException(500, f"Restart fehlgeschlagen: {exc}")


@app.post("/api/services/{service}/start")
async def start_service(service: str, _user: str = Depends(require_admin)):
    svc = BOT_SERVICES.get(service)
    if not svc:
        raise HTTPException(404, "Unknown service")
    try:
        await asyncio.to_thread(_do_start, svc["container"])
        return {"ok": True, "service": service, "action": "started"}
    except docker.errors.NotFound:
        raise HTTPException(404, f"Container {svc['container']} nicht gefunden")
    except Exception as exc:
        raise HTTPException(500, f"Start fehlgeschlagen: {exc}")


@app.post("/api/services/{service}/stop")
async def stop_service(service: str, _user: str = Depends(require_admin)):
    svc = BOT_SERVICES.get(service)
    if not svc:
        raise HTTPException(404, "Unknown service")
    try:
        await asyncio.to_thread(_do_stop, svc["container"])
        return {"ok": True, "service": service, "action": "stopped"}
    except docker.errors.NotFound:
        raise HTTPException(404, f"Container {svc['container']} nicht gefunden")
    except Exception as exc:
        raise HTTPException(500, f"Stop fehlgeschlagen: {exc}")


@app.get("/api/services/{service}/logs")
async def service_logs(
    service: str,
    tail: int = 200,
    _user: str = Depends(require_admin),
):
    """Letzte N Log-Zeilen eines Containers."""
    svc = BOT_SERVICES.get(service)
    if not svc:
        raise HTTPException(404, "Unknown service")
    try:
        c = docker_client.containers.get(svc["container"])
        logs = c.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        return {"service": service, "logs": logs}
    except docker.errors.NotFound:
        raise HTTPException(404, f"Container {svc['container']} nicht gefunden")
    except Exception as exc:
        raise HTTPException(500, f"Logs fehlgeschlagen: {exc}")


@app.get("/api/system")
async def system_stats(_user: str = Depends(require_admin)):
    """VPS-System-Stats: CPU, RAM, Disk, Uptime."""
    cpu_pct = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime_seconds = (datetime.now() - boot_time).total_seconds()
    return {
        "cpu_percent": cpu_pct,
        "cpu_count": psutil.cpu_count(),
        "memory": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "percent": disk.percent,
        },
        "uptime_seconds": int(uptime_seconds),
        "now": datetime.now().isoformat(),
    }


# -----------------------------------------------------------------------------
# Frontend serving
# -----------------------------------------------------------------------------
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def index(_user: str = Depends(require_admin)):
    return FileResponse(str(FRONTEND_DIR / "index.html"))

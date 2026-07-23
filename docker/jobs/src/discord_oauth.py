# -*- coding: utf-8 -*-
"""Discord-OAuth2-Hilfsfunktionen (authorize, Token-Tausch, User + Guild-Member).

Scopes: identify (User-Basisdaten) + guilds.members.read (Rollen-Check in der Guild).
"""
import urllib.parse

import httpx

from . import config

DISCORD_API_BASE = "https://discord.com/api/v10"
AUTHORIZE_ENDPOINT = "https://discord.com/oauth2/authorize"
TOKEN_ENDPOINT = f"{DISCORD_API_BASE}/oauth2/token"
OAUTH_SCOPES = "identify guilds.members.read"

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class DiscordOAuthError(Exception):
    """Fehler bei der Discord-API — status hilft dem Caller beim Unterscheiden."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def authorize_url(state: str) -> str:
    """Discord-Authorize-URL mit CSRF-State bauen."""
    params = urllib.parse.urlencode(
        {
            "client_id": config.DISCORD_CLIENT_ID,
            "redirect_uri": config.DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": OAUTH_SCOPES,
            "state": state,
            "prompt": "none",
        }
    )
    return f"{AUTHORIZE_ENDPOINT}?{params}"


async def exchange_code(code: str) -> dict:
    """Authorization-Code gegen Access-Token tauschen."""
    data = {
        "client_id": config.DISCORD_CLIENT_ID,
        "client_secret": config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                TOKEN_ENDPOINT,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise DiscordOAuthError(f"Discord nicht erreichbar: {exc}") from exc
    if resp.status_code != 200:
        raise DiscordOAuthError(
            f"Token-Tausch fehlgeschlagen (HTTP {resp.status_code})", resp.status_code
        )
    return resp.json()


async def _get_json(path: str, access_token: str) -> dict:
    """GET auf die Discord-API mit Bearer-Token."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{DISCORD_API_BASE}{path}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        raise DiscordOAuthError(f"Discord nicht erreichbar: {exc}") from exc
    if resp.status_code != 200:
        raise DiscordOAuthError(
            f"Discord-API-Fehler auf {path} (HTTP {resp.status_code})", resp.status_code
        )
    return resp.json()


async def fetch_user(access_token: str) -> dict:
    """Eingeloggten User holen (/users/@me)."""
    return await _get_json("/users/@me", access_token)


async def fetch_member(access_token: str, guild_id: str) -> dict:
    """Guild-Member inkl. Rollen holen — 404 heisst: nicht auf dem Server."""
    return await _get_json(f"/users/@me/guilds/{guild_id}/member", access_token)


async def fetch_member_bot(guild_id: str, user_id: str) -> dict:
    """Guild-Member per BOT-Token holen (Rollen-Recheck waehrend der Session,
    ohne User-Access-Token zu speichern). 404 heisst: nicht (mehr) auf dem
    Server — DiscordOAuthError.status transportiert das zum Caller."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
                headers={"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"},
            )
    except httpx.HTTPError as exc:
        raise DiscordOAuthError(f"Discord nicht erreichbar: {exc}") from exc
    if resp.status_code != 200:
        raise DiscordOAuthError(
            f"Member-Lookup fehlgeschlagen (HTTP {resp.status_code})", resp.status_code
        )
    return resp.json()


def avatar_url(user: dict) -> str:
    """CDN-Avatar-URL bauen (Fallback auf Discord-Default-Avatar)."""
    user_id = user.get("id", "")
    avatar_hash = user.get("avatar")
    if user_id and avatar_hash:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=64"
    try:
        idx = (int(user_id) >> 22) % 6
    except (TypeError, ValueError):
        idx = 0
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"


def display_name(user: dict, member: dict) -> str:
    """Anzeigename: Guild-Nickname > globaler Anzeigename > Username."""
    return (
        (member.get("nick") or "").strip()
        or (user.get("global_name") or "").strip()
        or user.get("username", "Unbekannt")
    )

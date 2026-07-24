"""
Discord Ticket-Bot mit RAG-Autoreply via Claude.

Button-basierter Flow:
- /panel       -> postet User-Panel (Ticket oeffnen + Direkte Frage)
- /adminpanel  -> postet Admin-Panel (KB-Stats + Reindex)
- Ticket-Channel enthaelt "Schliessen"-Button
Slash-Commands sind nur Bootstrap zum einmaligen Posten der Panels.
"""
import io
import json
import os
import logging
import asyncio
import subprocess
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import re as _re_mod

from rag import answer as rag_answer
import messages as msg_store
import ticket_categories as tc_store
import team_areas as team_areas_store

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0") or 0)
MOD_ROLE_ID = int(os.getenv("MOD_ROLE_ID", "0") or 0)
TICKET_ACCESS_ROLE_ID = int(os.getenv("TICKET_ACCESS_ROLE_ID", "0") or 0)
TICKET_CHANNEL_ID = int(os.getenv("TICKET_CHANNEL_ID", "0") or 0)

PANEL_RESEND_FLAG = ROOT / "data" / "panel_resend.flag"
SILENT_MENTIONS = os.getenv("SILENT_MENTIONS", "false").lower() in ("1", "true", "yes")

# Kategorie-Slugs mit eigenem Channel-Prefix (slug-NNNN-user statt lc-NNNN-slug-user)
_CUSTOM_PREFIX_SLUGS = {"crime", "gewerbe", "staatlich", "als-questgeber-bewerben", "team-bewerbung"}

# Kurz-Prefix fuer Channel-Namen statt langem Slug (Channel: prefix-NNNN-user)
_CHANNEL_PREFIX = {"als-questgeber-bewerben": "qg"}


def _slug_prefix(slug: str) -> str:
    """Channel-Prefix fuer einen Slug (Kurzform falls definiert, sonst Slug selbst)."""
    return _CHANNEL_PREFIX.get(slug, slug)

# Channels wo die KI aufgegeben hat (needs_human=True) → wartet auf Mod-Übernahme
_ai_handed_off: set[int] = set()
# Channels wo ein Mod manuell geantwortet hat → KI bleibt dauerhaft stumm
_ai_silenced: set[int] = set()


def _is_ticket_channel(name: str) -> bool:
    """Gibt True zurück wenn der Channel-Name zu einem Ticket gehört."""
    if name.startswith("lc-"):
        return True
    for slug in _CUSTOM_PREFIX_SLUGS:
        if name.startswith(f"{slug}-") or name.startswith(f"{_slug_prefix(slug)}-"):
            return True
    return False


def _is_ai_ticket_channel(name: str, topic: str = "") -> bool:
    """Gibt True zurück wenn die KI in diesem Channel antworten soll.
    Reihenfolge:
    1. Channel-Topic  → ticket:{slug}  (neue Tickets)
    2. Channel-Name   → slug im Namen  (alte Tickets ohne Topic)
    3. Fallback       → lc-* = True, andere Prefixe = False"""
    def _ai_for_slug(slug: str) -> bool:
        cat = tc_store.get(slug)
        result = bool(cat.get("ai_enabled", True)) if cat else True
        log.debug("_ai_for_slug(%r): cat=%r → %s", slug, cat, result)
        return result

    # 1. Topic-basiert (neue Tickets)
    if topic and topic.startswith("ticket:"):
        slug = topic[len("ticket:"):]
        if slug:
            result = _ai_for_slug(slug)
            log.debug("_is_ai_ticket_channel(%r) via topic=%r → %s", name, topic, result)
            return result

    # 2. Slug aus Channel-Namen lesen (Format: lc-NNNN-{slug}-{user} oder {slug}-NNNN-{user})
    all_cats = sorted(tc_store.list_all(), key=lambda c: -len(c["id"]))
    if name.startswith("lc-"):
        parts = name.split("-", 2)
        rest = parts[2] if len(parts) > 2 else ""
        log.debug("_is_ai_ticket_channel(%r): topic=%r rest=%r", name, topic, rest)
        for cat in all_cats:
            s = cat["id"]
            if rest.startswith(s + "-") or rest == s:
                result = _ai_for_slug(s)
                log.debug("_is_ai_ticket_channel(%r) via name-slug=%r → %s", name, s, result)
                return result
        log.debug("_is_ai_ticket_channel(%r): kein Slug gefunden → True (generic)", name)
        return True  # Generisches Ticket ohne Kategorie → KI AN
    for cat in all_cats:
        pfx = _slug_prefix(cat["id"])
        if name.startswith(cat["id"] + "-") or name.startswith(pfx + "-"):
            result = _ai_for_slug(cat["id"])
            log.debug("_is_ai_ticket_channel(%r) via prefix=%r → %s", name, pfx, result)
            return result

    log.debug("_is_ai_ticket_channel(%r): kein Match → False", name)
    return False

# Kein @-Ping wenn SILENT_MENTIONS=true
_NO_MENTIONS = discord.AllowedMentions.none()

import re as _re
_IMG_RE = _re.compile(r"\[\[img:([^\]]+)\]\]")
_SNIPPET_IMG_DIR = ROOT / "data" / "snippet_images"


def _extract_images(text: str):
    files = []
    for fname in _IMG_RE.findall(text):
        p = _SNIPPET_IMG_DIR / fname
        if p.exists():
            files.append(discord.File(str(p), filename=fname))
    clean = _IMG_RE.sub("", text).strip()
    return clean, files
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0") or 0)
TICKET_ARCHIVE_CHANNEL_ID = int(os.getenv("TICKET_ARCHIVE_CHANNEL_ID", "0") or 0)

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# --- Ticket-Zähler (persistent) ---
_COUNTER_FILE = ROOT / "data" / "ticket_counter.json"
_counter_lock = asyncio.Lock()


def _read_counter() -> int:
    try:
        return int(json.loads(_COUNTER_FILE.read_text(encoding="utf-8")).get("count", 0))
    except Exception:
        return 0


def _write_counter(n: int):
    _COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _COUNTER_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"count": n}), encoding="utf-8")
    os.replace(tmp, _COUNTER_FILE)


async def _next_ticket_number() -> int:
    """Atomisch inkrementieren, thread-safe."""
    async with _counter_lock:
        n = _read_counter() + 1
        _write_counter(n)
        return n
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ticket-bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- Modals ----------

class AskModal(discord.ui.Modal):
    frage = discord.ui.TextInput(
        label="Deine Frage",
        style=discord.TextStyle.paragraph,
        placeholder="z.B. Wie bewerbe ich mich?",
        required=True,
        max_length=1000,
    )

    def __init__(self):
        msgs = msg_store.get_all()
        super().__init__(title=msgs.get("modal_title", "Frage an die Wissensbasis"))
        self.frage.label = msgs.get("modal_label", "Deine Frage")
        self.frage.placeholder = msgs.get("modal_placeholder", "z.B. Wie bewerbe ich mich?")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, rag_answer, str(self.frage))
        except Exception as e:
            log.exception("AskModal RAG-Error")
            await interaction.followup.send(f"Fehler: `{e}`", ephemeral=True)
            return
        body, imgs = _extract_images(result['answer'])
        body = f"**Frage:** {self.frage}\n\n{body}"
        if len(body) > 2000:
            body = body[:1990] + "..."
        await interaction.followup.send(body, files=imgs or discord.utils.MISSING, ephemeral=True)


# ---------- Ticket-Öffnungs-Logik (geteilt von allen Buttons) ----------

async def _open_ticket(interaction: discord.Interaction, category_slug: str = None):
    """Generischer Ticket-Flow (ohne Sonderformular). Wird von FallbackButton + nicht-crime Kategorien genutzt."""
    await interaction.response.defer()  # Typ 6: stille Bestaetigung, keine sichtbare Meldung
    ch = await _create_ticket_channel(interaction, category_slug)
    if not ch:
        return

    cat       = tc_store.get(category_slug) if category_slug else None
    cat_label = cat["label"] if cat else None
    cat_emoji = cat.get("emoji", "🎫") if cat else "🎫"

    _msgs = msg_store.get_all()
    title = _msgs.get("ticket_title", "🎫 Ticket geöffnet")
    if cat_label:
        title = f"{cat_emoji} {cat_label} — Ticket"
    embed = discord.Embed(
        title=title,
        description=_msgs.get(
            "ticket_description",
            "Hi {mention}! Beschreib dein Anliegen.\n\nIch beantworte Fragen automatisch aus der Wissensbasis. Bei Unklarheiten meldet sich ein Mod."
        ).replace("{mention}", interaction.user.mention),
        color=0xD42070,
    )
    am = _NO_MENTIONS if SILENT_MENTIONS else discord.AllowedMentions(users=True)
    await ch.send(embed=embed, view=TicketActions(), allowed_mentions=am)
    log.info("Ticket geöffnet: %s von %s (%s) [Kategorie: %s]",
             ch.id, interaction.user, interaction.user.id, category_slug or "–")


# ---------- Crime-Formular ----------

async def _create_ticket_channel(interaction: discord.Interaction, category_slug: str):
    """Erstellt den Ticket-Channel und gibt ihn zurück (None bei Fehler/Duplikat)."""
    guild = interaction.guild
    user  = interaction.user
    cat   = tc_store.get(category_slug) if category_slug else None

    safe_name = user.name.lower().replace(" ", "-")
    open_tickets = [
        c for c in guild.text_channels
        if c.name.endswith(f"-{safe_name}") and _is_ticket_channel(c.name)
    ]
    if len(open_tickets) >= 2:
        mentions = " ".join(c.mention for c in open_tickets[:2])
        await interaction.followup.send(
            f"Du hast bereits 2 offene Tickets: {mentions}\nBitte schließe ein Ticket, bevor du ein neues eröffnest.",
            ephemeral=True,
        )
        return None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True,
            read_message_history=True, manage_channels=True,
        ),
    }
    if TICKET_ACCESS_ROLE_ID:
        role = guild.get_role(TICKET_ACCESS_ROLE_ID)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

    guild_category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
    num = await _next_ticket_number()
    if category_slug and category_slug in _CUSTOM_PREFIX_SLUGS:
        ticket_name = f"{_slug_prefix(category_slug)}-{num:04d}-{safe_name}"[:100]
    elif category_slug:
        ticket_name = f"lc-{num:04d}-{category_slug}-{safe_name}"[:100]
    else:
        ticket_name = f"lc-{num:04d}-{safe_name}"[:100]

    try:
        ch = await guild.create_text_channel(
            ticket_name,
            overwrites=overwrites,
            category=guild_category,
            topic=f"ticket:{category_slug or ''}",
            reason=f"Ticket von {user}" + (f" [{cat['label']}]" if cat else ""),
        )
        return ch
    except discord.Forbidden:
        await interaction.followup.send(
            "Keine Berechtigung Channels zu erstellen. Bot braucht `Manage Channels`.",
            ephemeral=True,
        )
    except Exception as e:
        log.exception("Channel-Erstellung fehlgeschlagen")
        await interaction.followup.send(f"Fehler: {e}", ephemeral=True)
    return None


class CrimeFormModal(discord.ui.Modal):
    """Eingabemaske für Crime-Tickets (An-/Abmeldung)."""

    name_gruppe = discord.ui.TextInput(
        label="Name der Gruppierung",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    name_leader = discord.ui.TextInput(
        label="Name des Leaders",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    mitglieder = discord.ui.TextInput(
        label="Mitgliedsnamen (Discord)",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
        placeholder="Ein Name pro Zeile",
    )
    sonstiges = discord.ui.TextInput(
        label="Sonstiges",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
        placeholder="Weitere Informationen (optional)...",
    )

    def __init__(self, crime_type: str):
        key   = f"crime_modal_{crime_type}"
        title = msg_store.get(key) or f"Crime {crime_type.title()}"
        super().__init__(title=title)
        self.crime_type = crime_type

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()  # Typ 6: stille Bestaetigung, keine sichtbare Meldung
        ch = await _create_ticket_channel(interaction, "crime")
        if not ch:
            return

        cat = tc_store.get("crime")
        emoji = cat.get("emoji", "🔫") if cat else "🔫"

        embed_title = msg_store.get("crime_embed_title").replace("{typ}", self.crime_type.title()) \
                      or f"{emoji} Crime {self.crime_type.title()} — Ticket"
        embed = discord.Embed(
            title=embed_title,
            color=0xD42070,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Bewerber",                  value=interaction.user.mention,  inline=False)
        embed.add_field(name="Typ",                       value=self.crime_type.title(),   inline=True)
        embed.add_field(name="Name der Gruppierung",      value=str(self.name_gruppe),     inline=True)
        embed.add_field(name="Name des Leaders",          value=str(self.name_leader),     inline=True)
        embed.add_field(name="Mitgliedsnamen (Discord)",  value=str(self.mitglieder),      inline=False)
        if str(self.sonstiges).strip():
            embed.add_field(name="Sonstiges",             value=str(self.sonstiges),       inline=False)

        am = _NO_MENTIONS if SILENT_MENTIONS else discord.AllowedMentions(users=True)
        await ch.send(embed=embed, view=TicketActions(), allowed_mentions=am)
        log.info("Crime-Ticket geöffnet: %s von %s (%s) [%s]",
                 ch.id, interaction.user, interaction.user.id, self.crime_type)


class CrimeTypeView(discord.ui.View):
    """Ephemere Auswahl: Crime anmelden / abmelden."""

    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Crime anmelden", emoji="✅", style=discord.ButtonStyle.success)
    async def anmelden(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.label = msg_store.get("crime_btn_anmelden") or "Crime anmelden"
        await interaction.response.send_modal(CrimeFormModal("anmelden"))

    @discord.ui.button(label="Crime abmelden", emoji="🚪", style=discord.ButtonStyle.danger)
    async def abmelden(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.label = msg_store.get("crime_btn_abmelden") or "Crime abmelden"
        await interaction.response.send_modal(CrimeFormModal("abmelden"))


class GewerbeFormModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title=msg_store.get("gewerbe_modal_title") or "Gewerbe Bewerbung")
    """Eingabemaske für Gewerbe-Tickets."""

    name_gewerbe = discord.ui.TextInput(
        label="Name des Gewerbes",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    name_gf = discord.ui.TextInput(
        label="DC Name des Geschäftsführers",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    mitarbeiter = discord.ui.TextInput(
        label="Weitere Mitarbeiter (Discord)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
        placeholder="Ein Name pro Zeile (optional)",
    )
    sonstiges = discord.ui.TextInput(
        label="Sonstiges",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
        placeholder="Weitere Informationen (optional)...",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()  # Typ 6: stille Bestaetigung, keine sichtbare Meldung
        ch = await _create_ticket_channel(interaction, "gewerbe")
        if not ch:
            return

        cat   = tc_store.get("gewerbe")
        emoji = cat.get("emoji", "🏪") if cat else "🏪"

        embed = discord.Embed(
            title=msg_store.get("gewerbe_embed_title") or f"{emoji} Gewerbe Bewerbung — Ticket",
            color=0xD42070,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Bewerber",                     value=interaction.user.mention, inline=False)
        embed.add_field(name="Name des Gewerbes",            value=str(self.name_gewerbe), inline=True)
        embed.add_field(name="DC Name des Geschäftsführers", value=str(self.name_gf),      inline=True)
        if str(self.mitarbeiter).strip():
            embed.add_field(name="Weitere Mitarbeiter (Discord)", value=str(self.mitarbeiter), inline=False)
        if str(self.sonstiges).strip():
            embed.add_field(name="Sonstiges",                value=str(self.sonstiges),    inline=False)

        am = _NO_MENTIONS if SILENT_MENTIONS else discord.AllowedMentions(users=True)
        await ch.send(embed=embed, view=TicketActions(), allowed_mentions=am)
        log.info("Gewerbe-Ticket geöffnet: %s von %s (%s)", ch.id, interaction.user, interaction.user.id)


class TeamBewerbungModal(discord.ui.Modal):
    """Eingabemaske für Team-Bewerbungs-Tickets (Bereich kommt vorausgefüllt aus der Auswahl)."""

    def __init__(self, bereich: str = ""):
        super().__init__(title=msg_store.get("team_modal_title") or "Team Bewerbung")
        self.bereich_input = discord.ui.TextInput(
            label="In welchem Bereich willst du unterstützen?",
            style=discord.TextStyle.short,
            required=True,
            max_length=200,
            default=bereich,
        )
        self.erfahrung = discord.ui.TextInput(
            label="Hast du Erfahrungen in dem genannten Bereich?",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
            placeholder="Ja / Nein",
        )
        self.andere_projekte = discord.ui.TextInput(
            label="Bist du aktuell in anderen Projekten tätig?",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
            placeholder="Ja / Nein",
        )
        self.sonstiges_input = discord.ui.TextInput(
            label="Willst du uns noch etwas mitteilen?",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
            placeholder="Weitere Informationen (optional)...",
        )
        self.add_item(self.bereich_input)
        self.add_item(self.erfahrung)
        self.add_item(self.andere_projekte)
        self.add_item(self.sonstiges_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()  # Typ 6: stille Bestaetigung, keine sichtbare Meldung
        ch = await _create_ticket_channel(interaction, "team-bewerbung")
        if not ch:
            return

        cat   = tc_store.get("team-bewerbung")
        emoji = cat.get("emoji", "👥") if cat else "👥"

        embed = discord.Embed(
            title=msg_store.get("team_embed_title") or f"{emoji} Team Bewerbung — Ticket",
            color=0xD42070,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Bewerber",                           value=interaction.user.mention,  inline=False)
        embed.add_field(name="Unterstützungsbereich",              value=str(self.bereich_input),   inline=False)
        embed.add_field(name="Erfahrungen im genannten Bereich",   value=str(self.erfahrung),       inline=True)
        embed.add_field(name="Aktuell in anderen Projekten tätig", value=str(self.andere_projekte), inline=True)
        if str(self.sonstiges_input).strip():
            embed.add_field(name="Sonstiges",                      value=str(self.sonstiges_input), inline=False)

        am = _NO_MENTIONS if SILENT_MENTIONS else discord.AllowedMentions(users=True)
        await ch.send(embed=embed, view=TicketActions(), allowed_mentions=am)
        log.info("Team-Ticket geöffnet: %s von %s (%s)", ch.id, interaction.user, interaction.user.id)


class TeamBewerbungAreaSelect(discord.ui.View):
    """Bereichs-Auswahl vor dem Team-Bewerbungs-Modal — Optionen aus team_areas.json."""

    def __init__(self):
        super().__init__(timeout=120)
        areas = team_areas_store.list_all()
        if not areas:
            areas = [{"label": "Allgemein", "emoji": "🎯"}]
        options = [
            discord.SelectOption(label=a["label"], emoji=a.get("emoji") or None)
            for a in areas[:25]  # Discord-Limit: max. 25 Optionen
        ]
        self._sel = discord.ui.Select(
            placeholder="Wähle deinen Bereich (Mehrfachauswahl möglich)",
            min_values=1,
            max_values=len(options),
            options=options,
        )
        self._sel.callback = self._on_select
        self.add_item(self._sel)

    async def _on_select(self, interaction: discord.Interaction):
        bereich = ", ".join(self._sel.values)
        await interaction.response.send_modal(TeamBewerbungModal(bereich=bereich))


# Slug → spezielle Form-Klasse.
# Wert ist entweder ein discord.ui.View (zeigt Zwischenschritt) oder
# ein discord.ui.Modal (öffnet direkt die Eingabemaske).
class StaatlichFormModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title=msg_store.get("staatlich_modal_title") or "Staatliche Fraktion Bewerbung")
    """Eingabemaske für Staatlich-Tickets."""

    name_fraktion = discord.ui.TextInput(
        label="Name der Fraktion",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    name_leiter = discord.ui.TextInput(
        label="DC Name des Leiters",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    mitarbeiter = discord.ui.TextInput(
        label="Weitere Mitarbeiter (Discord)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
        placeholder="Ein Name pro Zeile (optional)",
    )
    sonstiges = discord.ui.TextInput(
        label="Sonstiges",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
        placeholder="Weitere Informationen (optional)...",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()  # Typ 6: stille Bestaetigung, keine sichtbare Meldung
        ch = await _create_ticket_channel(interaction, "staatlich")
        if not ch:
            return

        cat   = tc_store.get("staatlich")
        emoji = cat.get("emoji", "🏛") if cat else "🏛"

        embed = discord.Embed(
            title=msg_store.get("staatlich_embed_title") or f"{emoji} Staatliche Fraktion Bewerbung — Ticket",
            color=0xD42070,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Bewerber",                     value=interaction.user.mention, inline=False)
        embed.add_field(name="Name der Fraktion",            value=str(self.name_fraktion), inline=True)
        embed.add_field(name="DC Name des Leiters",          value=str(self.name_leiter),   inline=True)
        if str(self.mitarbeiter).strip():
            embed.add_field(name="Weitere Mitarbeiter (Discord)", value=str(self.mitarbeiter), inline=False)
        if str(self.sonstiges).strip():
            embed.add_field(name="Sonstiges",                value=str(self.sonstiges),     inline=False)

        am = _NO_MENTIONS if SILENT_MENTIONS else discord.AllowedMentions(users=True)
        await ch.send(embed=embed, view=TicketActions(), allowed_mentions=am)
        log.info("Staatlich-Ticket geöffnet: %s von %s (%s)", ch.id, interaction.user, interaction.user.id)


class QuestgeberFormModal(discord.ui.Modal):
    """Eingabemaske für Questgeber-Bewerbungen."""

    def __init__(self):
        super().__init__(title=msg_store.get("questgeber_modal_title") or "Questgeber Bewerbung")
        self.gespielt = discord.ui.TextInput(
            label="Hast du schon auf Sektor gespielt?",
            style=discord.TextStyle.short,
            required=True,
            max_length=10,
            placeholder="Ja / Nein",
        )
        self.jahre = discord.ui.TextInput(
            label="Falls ja, wie viele Jahre ungefähr?",
            style=discord.TextStyle.short,
            required=False,
            max_length=20,
            placeholder="z.B. 2 Jahre",
        )
        self.letzter_char = discord.ui.TextInput(
            label="Letzter Char & Bereich auf Sektor",
            style=discord.TextStyle.short,
            required=True,
            max_length=100,
            placeholder="z.B. Max Mustermann – Gangster / Staatlich",
        )
        self.sonstiges = discord.ui.TextInput(
            label="Sonstiges",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
            placeholder="Weitere Informationen (optional)...",
        )
        self.hinweis = discord.ui.TextInput(
            label="📋 Hinweis — Bitte zur Kenntnis nehmen",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=200,
            default="Mit dem Absenden bestätigst du, dass du das Wissen über andere Gruppierungen nicht zu deinem Vorteil nutzt.",
        )
        self.add_item(self.gespielt)
        self.add_item(self.jahre)
        self.add_item(self.letzter_char)
        self.add_item(self.sonstiges)
        self.add_item(self.hinweis)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()  # Typ 6: stille Bestaetigung, keine sichtbare Meldung
        ch = await _create_ticket_channel(interaction, "als-questgeber-bewerben")
        if not ch:
            return

        cat   = tc_store.get("als-questgeber-bewerben")
        emoji = cat.get("emoji", "🎯") if cat else "🎯"

        embed = discord.Embed(
            title=msg_store.get("questgeber_embed_title") or f"{emoji} Questgeber Bewerbung — Ticket",
            color=0xD42070,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Bewerber",                         value=interaction.user.mention, inline=False)
        embed.add_field(name="Schon auf Sektor gespielt?",       value=str(self.gespielt),     inline=True)
        embed.add_field(name="Wie viele Jahre ungefähr?",        value=str(self.jahre) or "—", inline=True)
        embed.add_field(name="Letzter Char & Bereich auf Sektor", value=str(self.letzter_char), inline=False)
        if str(self.sonstiges).strip():
            embed.add_field(name="Sonstiges",                    value=str(self.sonstiges),    inline=False)
        embed.set_footer(text="Wir gucken uns deine Questgeber-Bewerbung an und melden uns")

        am = _NO_MENTIONS if SILENT_MENTIONS else discord.AllowedMentions(users=True)
        await ch.send(embed=embed, view=TicketActions(), allowed_mentions=am)
        log.info("Questgeber-Ticket geöffnet: %s von %s (%s)", ch.id, interaction.user, interaction.user.id)


_CATEGORY_FORMS: dict = {
    "crime":                   CrimeTypeView,
    "gewerbe":                 GewerbeFormModal,
    "staatlich":               StaatlichFormModal,
    "team-bewerbung":          TeamBewerbungAreaSelect,
    "als-questgeber-bewerben": QuestgeberFormModal,
}


# ---------- Persistent Views ----------

class CategoryButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=_re_mod.compile(r"ticket:cat:(?P<slug>[a-z0-9_-]+)"),
):
    """Dynamischer Button für eine Ticket-Kategorie (z.B. Crime, Gewerbe)."""

    def __init__(self, slug: str, label: str, emoji: str = "🎫"):
        super().__init__(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.primary,
                custom_id=f"ticket:cat:{slug}",
            )
        )
        self.slug = slug

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: _re_mod.Match,
    ):
        slug = match.group("slug")
        cat  = tc_store.get(slug)
        if cat:
            return cls(slug=slug, label=cat["label"], emoji=cat.get("emoji", "🎫"))
        return cls(slug=slug, label=slug.replace("-", " ").title(), emoji="🎫")

    async def callback(self, interaction: discord.Interaction):
        form_cls = _CATEGORY_FORMS.get(self.slug)
        if form_cls is None:
            await _open_ticket(interaction, category_slug=self.slug)
        elif issubclass(form_cls, discord.ui.Modal):
            # Direkt das Modal öffnen (z.B. Gewerbe)
            await interaction.response.send_modal(form_cls())
        else:
            # Zwischenschritt mit View (z.B. Crime: anmelden/abmelden)
            cat = tc_store.get(self.slug)
            label = cat["label"] if cat else self.slug.title()
            await interaction.response.send_message(
                f"Wähle den Typ für dein **{label}**-Ticket:",
                view=form_cls(),
                ephemeral=True,
            )


class _FallbackOpenButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=_re_mod.compile(r"ticket:open"),
):
    """Fallback-Button 'Ticket eröffnen' – aktiv wenn keine Kategorien konfiguriert."""

    def __init__(self):
        super().__init__(
            discord.ui.Button(
                label="Ticket eröffnen",
                emoji="🎫",
                style=discord.ButtonStyle.primary,
                custom_id="ticket:open",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await _open_ticket(interaction, category_slug=None)


class _AskButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=_re_mod.compile(r"ticket:ask"),
):
    """'Direkte Frage' Button."""

    def __init__(self):
        super().__init__(
            discord.ui.Button(
                label=msg_store.get("ask_btn_label") or "Direkte Frage ohne ein Ticket zu eröffnen - nur du kannst es lesen",
                emoji=discord.PartialEmoji(name="5EKTORLoad", id=1432317234474389637, animated=True),
                style=discord.ButtonStyle.success,
                custom_id="ticket:ask",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AskModal())


class TicketPanel(discord.ui.View):
    """User-Panel: Ticket eröffnen + Direkte Frage (immer zuerst), dann Kategorien.

    Reihenfolge:
      1. 🎫 Ticket eröffnen  (immer Position 1)
      2. ❓ Direkte Frage    (immer Position 2)
      3. Kategorie-Buttons   (aus ticket_categories.json, max. 23)
    """
    def __init__(self):
        super().__init__(timeout=None)
        import features as _ff
        # Zeile 0: nur "Direkte Frage"
        if _ff.get().get("ask_btn_enabled", True):
            ask_btn = _AskButton()
            ask_btn.row = 0
            self.add_item(ask_btn)
        # Zeile 1: "Ticket eröffnen" + erste 4 Kategorien
        # Zeilen 2-4: je 5 Kategorien → max. 19 Kategorien gesamt
        if _ff.get().get("ticket_open_enabled", True):
            open_btn = _FallbackOpenButton()
            open_btn.row = 1
            self.add_item(open_btn)
        for i, cat in enumerate(tc_store.list_enabled()[:19]):
            btn = CategoryButton(
                slug=cat["id"],
                label=cat["label"],
                emoji=cat.get("emoji", "🎫"),
            )
            btn.row = 1 + ((i + 1) // 5)
            self.add_item(btn)


class TicketActions(discord.ui.View):
    """Innerhalb eines Ticket-Channels: Schliessen-Button."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket schließen", emoji="🔒",
                       style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        # Unterstützt sowohl neue TextChannel-Tickets als auch alte Thread-Tickets
        is_ticket_channel = isinstance(ch, discord.TextChannel) and _is_ticket_channel(ch.name)
        is_ticket_thread  = isinstance(ch, discord.Thread)      and _is_ticket_channel(ch.name)
        if not (is_ticket_channel or is_ticket_thread):
            await interaction.response.send_message(
                "Nur in Ticket-Channels nutzbar.", ephemeral=True
            )
            return
        await interaction.response.send_message("Ticket wird archiviert & geschlossen.")
        await asyncio.sleep(1)

        # Transkript in Archiv-Channel speichern
        if TICKET_ARCHIVE_CHANNEL_ID:
            archive_ch = interaction.guild.get_channel(TICKET_ARCHIVE_CHANNEL_ID)
            if archive_ch:
                try:
                    lines = []
                    async for msg in ch.history(limit=500, oldest_first=True):
                        if msg.author.bot and msg.embeds and not msg.content:
                            continue  # Eingangs-Embed überspringen
                        ts = msg.created_at.strftime("%d.%m %H:%M")
                        lines.append(f"[{ts}] {msg.author.display_name}: {msg.content or '[Embed]'}")
                    transcript = "\n".join(lines) or "(keine Nachrichten)"

                    embed = discord.Embed(
                        title=f"📁 {ch.name}",
                        description=f"Geschlossen von {interaction.user.mention}",
                        color=0x4a4a6a,
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.set_footer(text=f"Channel-ID: {ch.id}")

                    if len(transcript) <= 3900:
                        embed.add_field(
                            name="Verlauf",
                            value=f"```\n{transcript[:3900]}\n```",
                            inline=False,
                        )
                        await archive_ch.send(embed=embed)
                    else:
                        await archive_ch.send(
                            embed=embed,
                            file=discord.File(
                                io.BytesIO(transcript.encode("utf-8")),
                                filename=f"{ch.name}.txt",
                            ),
                        )
                    log.info("Transkript archiviert: %s -> %s", ch.id, archive_ch.id)
                except Exception:
                    log.exception("Archiv-Error")

        try:
            await ch.delete(reason="Ticket geschlossen")
            log.info("Ticket gelöscht: %s", ch.id)
        except Exception:
            log.exception("Delete-Error")


class AdminPanel(discord.ui.View):
    """Admin-Panel: KB-Stats + Reindex."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="KB-Stats", emoji="📚",
                       style=discord.ButtonStyle.secondary, custom_id="admin:kbstats")
    async def kbstats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            from ingest import get_client
            _, col = get_client()
            n = col.count()
            await interaction.response.send_message(
                f"📚 Wissensbasis: **{n}** indexierte Chunks", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"Fehler: {e}", ephemeral=True)

    @discord.ui.button(label="Reindex", emoji="♻️",
                       style=discord.ButtonStyle.danger, custom_id="admin:reindex")
    async def reindex_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Nur Admins.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            loop = asyncio.get_running_loop()
            def _run():
                return subprocess.run(
                    [sys.executable, str(ROOT / "src" / "ingest.py"), "--reset"],
                    capture_output=True, text=True, cwd=str(ROOT), timeout=300,
                )
            proc = await loop.run_in_executor(None, _run)
            out = (proc.stdout or "") + (proc.stderr or "")
            out = out[-1800:]
            await interaction.followup.send(f"```\n{out}\n```", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Reindex-Fehler: `{e}`", ephemeral=True)


# ---------- Events ----------

# on_ready feuert bei jedem Reconnect erneut. Ohne diesen Schutz wuerden die
# persistenten Views mehrfach registriert -> jeder Button-Klick erzeugt
# mehrere Channels. (Symptom: 2 Tickets pro Klick + "Interaction already
# acknowledged"-Fehler im Log.)
_views_registered = False


@tasks.loop(seconds=10)
async def _check_panel_resend():
    """Prüft auf Flag-Datei vom Admin-Panel und postet das Support-Panel neu."""
    if not PANEL_RESEND_FLAG.exists():
        return
    try:
        raw = PANEL_RESEND_FLAG.read_text(encoding="utf-8").strip()
        channel_id = int(raw) if raw.isdigit() else (TICKET_CHANNEL_ID or 0)
        PANEL_RESEND_FLAG.unlink(missing_ok=True)
    except Exception:
        try:
            PANEL_RESEND_FLAG.unlink(missing_ok=True)
        except Exception:
            pass
        return

    if not channel_id:
        log.warning("Panel-Resend: keine Channel-ID konfiguriert (TICKET_CHANNEL_ID fehlt).")
        return

    channel = bot.get_channel(channel_id)
    if channel is None:
        log.warning("Panel-Resend: Channel %s nicht gefunden.", channel_id)
        return

    try:
        _msgs = msg_store.get_all()
        embed = discord.Embed(
            title=_msgs.get("panel_title", "🎫 Support"),
            description=_msgs.get(
                "panel_description",
                "**Ticket eröffnen** — Privater Channel, KI antwortet auf Fragen.\n**Direkte Frage** — Schnelle Antwort ohne Ticket (nur du siehst sie)."
            ),
            color=0xD42070,
        )
        await channel.send(embed=embed, view=TicketPanel())
        log.info("Panel-Resend: Panel in Channel %s gepostet.", channel_id)
    except Exception:
        log.exception("Panel-Resend: Fehler beim Posten.")


@bot.event
async def on_ready():
    global _views_registered
    log.info("Bot eingeloggt als %s (id: %s)", bot.user, bot.user.id)
    if not _views_registered:
        # DynamicItems registrieren (handlen alle ticket:cat:*, ticket:open, ticket:ask)
        bot.add_dynamic_items(CategoryButton, _FallbackOpenButton, _AskButton)
        bot.add_view(TicketActions())
        bot.add_view(AdminPanel())
        tc_store.init_defaults()
        team_areas_store.init_defaults()
        _views_registered = True
        log.info("Persistente Views + DynamicItems registriert.")
    else:
        log.info("Reconnect: Views bleiben aus erster Registrierung aktiv.")
    if not _check_panel_resend.is_running():
        _check_panel_resend.start()
        log.info("Panel-Resend-Task gestartet.")
    # Slash-Command-Sync nur wenn sich die Commands geaendert haben.
    # Sync bei JEDEM Start fuehrt zu Discord-Rate-Limits; discord.py wartet
    # diese im gemeinsamen HTTP-Client ab -> auch send_modal() verzoegert sich
    # ueber die 3-Sekunden-Frist -> "10062 Unknown interaction".
    try:
        cmd_names = sorted(c.name for c in bot.tree.get_commands(
            guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
        ))
        signature = f"{GUILD_ID}:" + ",".join(cmd_names)
        sig_file = ROOT / "data" / "commands_sig.txt"
        old_sig = ""
        try:
            old_sig = sig_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

        if old_sig == signature and os.getenv("FORCE_SYNC", "").lower() not in ("1", "true", "yes"):
            log.info("Slash-Commands unveraendert (%s) - Sync uebersprungen.", len(cmd_names))
        else:
            if GUILD_ID:
                synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            else:
                synced = await bot.tree.sync()
            sig_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = sig_file.with_suffix(".tmp")
            tmp.write_text(signature, encoding="utf-8")
            os.replace(tmp, sig_file)
            log.info("Slash-Commands synchronisiert: %s", len(synced))
    except Exception as e:
        log.exception("Sync-Error: %s", e)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    # Direkte KI-Blockade: Kategorie-ai_enabled prüfen (Topic + Name)
    if isinstance(message.channel, discord.TextChannel):
        _slug_to_check: str | None = None
        _topic = message.channel.topic or ""
        if _topic.startswith("ticket:"):
            _s = _topic[len("ticket:"):]
            if _s:
                _slug_to_check = _s
        if _slug_to_check is None:
            # Fallback: Slug aus Channel-Name extrahieren (lc-NNNN-{slug}-{user})
            _cname = message.channel.name
            if _cname.startswith("lc-"):
                _parts = _cname.split("-", 2)
                _rest = _parts[2] if len(_parts) > 2 else ""
                for _c in sorted(tc_store.list_all(), key=lambda c: -len(c["id"])):
                    _s = _c["id"]
                    if _rest.startswith(_s + "-") or _rest == _s:
                        _slug_to_check = _s
                        break
        if _slug_to_check:
            _cat = tc_store.get(_slug_to_check)
            if _cat and not _cat.get("ai_enabled", True):
                log.debug("KI blockiert (ai_enabled=False) für %r slug=%r", message.channel.name, _slug_to_check)
                await bot.process_commands(message)
                return
    if isinstance(message.channel, discord.TextChannel) and _is_ai_ticket_channel(message.channel.name, message.channel.topic or ""):
        ch_id = message.channel.id
        import features as _ff
        if not _ff.get().get("rag_enabled", True):
            await bot.process_commands(message)
            return

        # Wenn Mod bereits übernommen hat → KI schweigt dauerhaft
        if ch_id in _ai_silenced:
            await bot.process_commands(message)
            return

        # Wenn KI aufgegeben hatte und jetzt ein Mod/Supporter antwortet → Übernahme merken
        if ch_id in _ai_handed_off:
            member_roles = {r.id for r in getattr(message.author, "roles", [])}
            is_staff = (
                (MOD_ROLE_ID and MOD_ROLE_ID in member_roles)
                or (TICKET_ACCESS_ROLE_ID and TICKET_ACCESS_ROLE_ID in member_roles)
            )
            if is_staff:
                _ai_silenced.add(ch_id)
                _ai_handed_off.discard(ch_id)
                log.info("Mod-Übernahme in Channel %s — KI stumm geschaltet.", message.channel.name)
                await bot.process_commands(message)
                return

        async with message.channel.typing():
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, rag_answer, message.content)
            except Exception as e:
                log.exception("RAG-Error")
                await message.reply(f"Fehler bei Antwort-Generierung: `{e}`")
                await bot.process_commands(message)
                return
            if result.get("needs_human"):
                _ai_handed_off.add(ch_id)
            body, imgs = _extract_images(result["answer"])
            footer = ""
            if result.get("needs_human") and MOD_ROLE_ID:
                if SILENT_MENTIONS:
                    footer = f"\n\n📌 Ein Mod sollte sich dieses Ticket ansehen."
                else:
                    footer = f"\n\n<@&{MOD_ROLE_ID}> bitte übernehmen."
            full = body + footer
            reply_mentions = _NO_MENTIONS if SILENT_MENTIONS else discord.AllowedMentions(roles=True)
            send_kw = {"files": imgs, "allowed_mentions": reply_mentions} if imgs else {"allowed_mentions": reply_mentions}
            if len(full) <= 2000:
                await message.reply(full, **send_kw)
            else:
                chunks = [full[i:i+1990] for i in range(0, len(full), 1990)]
                for i, ch in enumerate(chunks):
                    kw = send_kw if i == 0 else {}
                    if i == 0:
                        await message.reply(ch, **kw)
                    else:
                        await message.channel.send(ch)
    await bot.process_commands(message)


# ---------- Bootstrap Slash-Commands (nur zum Posten der Panels) ----------

def _guild_obj():
    return discord.Object(id=GUILD_ID) if GUILD_ID else None


@bot.tree.command(name="panel", description="Postet das User-Ticket-Panel (Admin)", guild=_guild_obj())
async def panel_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("Nur Admins/Mods.", ephemeral=True)
        return
    _msgs = msg_store.get_all()
    embed = discord.Embed(
        title=_msgs.get("panel_title", "🎫 Support"),
        description=_msgs.get(
            "panel_description",
            "**Ticket öffnen** — Privater Channel, KI antwortet auf Fragen.\n**Direkte Frage** — Schnelle Antwort ohne Ticket (nur du siehst sie)."
        ),
        color=0xD42070,
    )
    await interaction.channel.send(embed=embed, view=TicketPanel())
    await interaction.response.send_message("Panel gepostet.", ephemeral=True)


@bot.tree.command(name="adminpanel", description="Postet das Admin-Panel (Admin)", guild=_guild_obj())
async def adminpanel_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("Nur Admins.", ephemeral=True)
        return
    embed = discord.Embed(
        title="⚙️ Admin-Panel",
        description="**KB-Stats** zeigt Chunk-Count. **Reindex** baut die Wissensbasis neu.",
        color=0x0FB8C9,
    )
    await interaction.channel.send(embed=embed, view=AdminPanel())
    await interaction.response.send_message("Admin-Panel gepostet.", ephemeral=True)


@bot.tree.command(name="ticket-add", description="Fügt einen User zum aktuellen Ticket hinzu", guild=_guild_obj())
@app_commands.describe(user="Der Discord-User der hinzugefügt werden soll")
async def ticket_add_cmd(interaction: discord.Interaction, user: discord.Member):
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel) or not _is_ticket_channel(ch.name):
        await interaction.response.send_message("Dieser Command funktioniert nur in Ticket-Channels.", ephemeral=True)
        return
    member_roles = {r.id for r in getattr(interaction.user, "roles", [])}
    is_staff = (
        interaction.user.guild_permissions.manage_channels
        or (MOD_ROLE_ID and MOD_ROLE_ID in member_roles)
        or (TICKET_ACCESS_ROLE_ID and TICKET_ACCESS_ROLE_ID in member_roles)
    )
    if not is_staff:
        await interaction.response.send_message("Nur Mods/Supporter können User hinzufügen.", ephemeral=True)
        return
    await ch.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
    await interaction.response.send_message(f"✅ {user.mention} wurde zum Ticket hinzugefügt.", ephemeral=False)


@bot.tree.command(name="ticket-remove", description="Entfernt einen User aus dem aktuellen Ticket", guild=_guild_obj())
@app_commands.describe(user="Der Discord-User der entfernt werden soll")
async def ticket_remove_cmd(interaction: discord.Interaction, user: discord.Member):
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel) or not _is_ticket_channel(ch.name):
        await interaction.response.send_message("Dieser Command funktioniert nur in Ticket-Channels.", ephemeral=True)
        return
    member_roles = {r.id for r in getattr(interaction.user, "roles", [])}
    is_staff = (
        interaction.user.guild_permissions.manage_channels
        or (MOD_ROLE_ID and MOD_ROLE_ID in member_roles)
        or (TICKET_ACCESS_ROLE_ID and TICKET_ACCESS_ROLE_ID in member_roles)
    )
    if not is_staff:
        await interaction.response.send_message("Nur Mods/Supporter können User entfernen.", ephemeral=True)
        return
    await ch.set_permissions(user, overwrite=None)
    await interaction.response.send_message(f"✅ {user.mention} wurde aus dem Ticket entfernt.", ephemeral=False)


# ---------- Singleton-Lock ----------
# Wenn der Bot 2x mit demselben Token laeuft, beantwortet jede Instanz die
# Nachricht unabhaengig -> doppelte Antworten in Discord. Wir nehmen einen
# atomic-create Lock auf data/bot.lock; die zweite Instanz exit'tet sofort.
import atexit
BOT_LOCK_FILE = ROOT / "data" / "bot.lock"


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in r.stdout
    except Exception:
        return False


def _release_singleton():
    try:
        if BOT_LOCK_FILE.exists():
            try:
                owner = int(BOT_LOCK_FILE.read_text().strip())
            except Exception:
                owner = 0
            if owner == os.getpid():
                BOT_LOCK_FILE.unlink()
    except Exception:
        pass


def _acquire_singleton():
    BOT_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(BOT_LOCK_FILE),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        atexit.register(_release_singleton)
        log.info("Singleton-Lock akquiriert (PID %s).", os.getpid())
        return
    except FileExistsError:
        pass

    # Lock existiert - pruefen ob der haltende Prozess noch laeuft.
    try:
        old_pid = int(BOT_LOCK_FILE.read_text().strip())
    except Exception:
        old_pid = 0
    if old_pid and _pid_alive(old_pid) and old_pid != os.getpid():
        log.error(
            "Bot laeuft bereits als PID %s - beende diese Instanz, sonst "
            "gibt's doppelte Antworten in Discord.", old_pid)
        sys.exit(1)

    # Stale lock (Prozess tot oder eigener PID) - aufraeumen und neu greifen.
    try:
        BOT_LOCK_FILE.unlink()
    except Exception:
        pass
    fd = os.open(str(BOT_LOCK_FILE),
                 os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    atexit.register(_release_singleton)
    log.info("Singleton-Lock akquiriert nach Stale-Cleanup (PID %s).", os.getpid())


# ---------- Entry ----------

def main():
    if not TOKEN:
        print("FEHLER: DISCORD_TOKEN fehlt in .env")
        sys.exit(1)
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("FEHLER: ANTHROPIC_API_KEY fehlt in .env")
        sys.exit(1)
    _acquire_singleton()
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()

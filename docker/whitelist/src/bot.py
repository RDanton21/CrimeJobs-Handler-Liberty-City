"""
Sektor 6 — Discord Whitelist Bot
Watches for role changes in the guild.
When Whitelist role is added/removed → updates whitelist_status in web DB.

Requirements:
    pip install discord.py mysql-connector-python python-dotenv

.env file (same directory) — see .env.example for format.
    BOT_TOKEN=your_bot_token_here
    DB_HOST=your_db_host
    DB_NAME=your_db_name
    DB_USER=your_db_user
    DB_PASS=your_db_password
    GUILD_ID=your_guild_id
    WHITELIST_ROLE_ID=your_whitelist_role_id
"""

import os
import asyncio
import logging
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('SektorBot')

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN         = os.getenv('BOT_TOKEN', '')
GUILD_ID          = int(os.getenv('GUILD_ID', '1429130066905792633'))
WHITELIST_ROLE_ID = int(os.getenv('WHITELIST_ROLE_ID', '1501498761795604500'))

DB_CONFIG = {
    'host':     os.getenv('DB_HOST', 'l8iy.your-database.de'),
    'database': os.getenv('DB_NAME', 'a64ksy_db0'),
    'user':     os.getenv('DB_USER', 'a64ksy_0'),
    'password': os.getenv('DB_PASS', ''),
    'charset':  'utf8mb4',
    'autocommit': True,
    'connection_timeout': 10,
}

# ── DB helper ─────────────────────────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def update_whitelist(discord_id: str, approved: bool) -> bool:
    """Update whitelist_status + discord_synced_at for a discord_id. Returns True if row updated."""
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE users
               SET whitelist_status = %s,
                   discord_synced_at = NOW()
               WHERE discord_id = %s""",
            ('approved' if approved else 'pending', discord_id)
        )
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        return affected > 0
    except mysql.connector.Error as e:
        log.error(f'DB error: {e}')
        return False

def sync_all_members(guild: discord.Guild) -> tuple[int, int]:
    """Bulk-sync all guild members' whitelist status. Returns (approved, pending) counts."""
    whitelist_role = guild.get_role(WHITELIST_ROLE_ID)
    if not whitelist_role:
        log.warning('Whitelist role not found in guild.')
        return 0, 0

    approved_ids = {str(m.id) for m in whitelist_role.members}

    try:
        conn   = get_db()
        cursor = conn.cursor()

        # Fetch all registered discord_ids
        cursor.execute('SELECT discord_id, whitelist_status FROM users WHERE discord_id IS NOT NULL')
        rows = cursor.fetchall()

        approved_count = pending_count = 0
        for (discord_id, current_status) in rows:
            new_status = 'approved' if discord_id in approved_ids else 'pending'
            if new_status != current_status:
                cursor.execute(
                    'UPDATE users SET whitelist_status=%s, discord_synced_at=NOW() WHERE discord_id=%s',
                    (new_status, discord_id)
                )
                log.info(f'Synced {discord_id}: {current_status} → {new_status}')
            if new_status == 'approved':
                approved_count += 1
            else:
                pending_count += 1

        cursor.close()
        conn.close()
        return approved_count, pending_count
    except mysql.connector.Error as e:
        log.error(f'Bulk sync DB error: {e}')
        return 0, 0

# ── Bot ───────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True   # Privileged intent — must be enabled in Dev Portal

bot = commands.Bot(command_prefix='!s6wl ', intents=intents)

@bot.event
async def on_ready():
    log.info(f'Bot online: {bot.user} (ID: {bot.user.id})')
    guild = bot.get_guild(GUILD_ID)
    if guild:
        ok, pend = sync_all_members(guild)
        log.info(f'Startup sync complete — approved: {ok}, pending: {pend}')
    periodic_sync.start()

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Fires when a member's roles change."""
    if after.guild.id != GUILD_ID:
        return

    before_roles = {r.id for r in before.roles}
    after_roles  = {r.id for r in after.roles}

    wl_added   = WHITELIST_ROLE_ID in after_roles  and WHITELIST_ROLE_ID not in before_roles
    wl_removed = WHITELIST_ROLE_ID in before_roles and WHITELIST_ROLE_ID not in after_roles

    if not wl_added and not wl_removed:
        return

    discord_id = str(after.id)
    approved   = wl_added

    updated = update_whitelist(discord_id, approved)
    action  = 'APPROVED' if approved else 'REMOVED'
    if updated:
        log.info(f'Whitelist {action}: {after.name} ({discord_id}) — DB updated.')
    else:
        log.warning(f'Whitelist {action}: {after.name} ({discord_id}) — no DB row found (not registered?).')

@bot.event
async def on_member_remove(member: discord.Member):
    """Member left server — set whitelist to pending."""
    if member.guild.id != GUILD_ID:
        return
    discord_id = str(member.id)
    update_whitelist(discord_id, False)
    log.info(f'Member left: {member.name} ({discord_id}) — whitelist set to pending.')

# ── Periodic sync (every 30 min) as safety net ────────────────────────────────
@tasks.loop(minutes=30)
async def periodic_sync():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    ok, pend = await asyncio.to_thread(sync_all_members, guild)
    log.info(f'Periodic sync — approved: {ok}, pending: {pend}')

@periodic_sync.before_loop
async def before_sync():
    await bot.wait_until_ready()

# ── Admin commands ─────────────────────────────────────────────────────────────
@bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def cmd_sync(ctx):
    """!s6wl sync — Force full whitelist sync."""
    guild = ctx.guild
    if guild.id != GUILD_ID:
        return
    ok, pend = await asyncio.to_thread(sync_all_members, guild)
    await ctx.reply(f'✅ Sync abgeschlossen — Approved: **{ok}**, Pending: **{pend}**', mention_author=False)

@bot.command(name='check')
@commands.has_permissions(administrator=True)
async def cmd_check(ctx, member: discord.Member):
    """!s6wl check @user — Check whitelist status from DB."""
    try:
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            'SELECT username, whitelist_status, fivem_license FROM users WHERE discord_id = %s',
            (str(member.id),)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
    except Exception as e:
        await ctx.reply(f'DB Fehler: {e}', mention_author=False)
        return

    if not row:
        await ctx.reply(f'❌ {member.mention} — Kein Account registriert.', mention_author=False)
        return

    status_emoji = '✅' if row['whitelist_status'] == 'approved' else '⏳'
    lic = row['fivem_license'] or 'noch nicht verknüpft'
    await ctx.reply(
        f'{status_emoji} **{row["username"]}** — Status: `{row["whitelist_status"]}` | FiveM: `{lic}`',
        mention_author=False
    )

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if not BOT_TOKEN:
        log.error('BOT_TOKEN nicht gesetzt! .env Datei prüfen.')
        exit(1)
    bot.run(BOT_TOKEN)

"""
Entry point — loads cogs, syncs slash commands, and runs the bot.
"""

from __future__ import annotations

import logging
import sys

import discord
from discord.ext import commands

from config import BOT_OWNER_ID, DEV_GUILD_ID, DISCORD_TOKEN

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("lofi-bot.log", encoding="utf-8"),
    ],
)
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("yt_dlp").setLevel(logging.WARNING)

log = logging.getLogger("bot")

# ── Intents ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True


class LofiBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=intents,
            owner_id=BOT_OWNER_ID,
        )

    async def setup_hook(self) -> None:
        cogs = ["cogs.stream", "cogs.debug"]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception as exc:
                log.exception("Failed to load cog %s: %s", cog, exc)

        if DEV_GUILD_ID:
            guild = discord.Object(id=DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to dev guild %d (instant).", DEV_GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally (may take up to 1 hour).")

    async def on_ready(self) -> None:
        log.info("Bot ready — logged in as %s (ID: %d)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening, name="lofi hip hop 🎵"
            )
        )

    async def on_error(self, event: str, *args, **kwargs) -> None:
        log.exception("Unhandled error in event '%s'., event")

def main() -> None:
    if not DISCORD_TOKEN:
        log.critical("DISCORD_TOKEN is not set. Check your .env file.")
        sys.exit(1)
    if not BOT_OWNER_ID:
        log.critical("BOT_OWNER_ID is not set. Check your .env file.")
        sys.exit(1)

    bot = LofiBot()
    bot.run(DISCORD_TOKEN, log_handler=None)

if __name__ == "__main__":
    main()
"""
Debug cog — owner-only slash commands to simulate every failure state.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import BOT_OWNER_ID

log = logging.getLogger(__name__)


def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message(
                "❌ Owner only.", ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)


class DebugCog(commands.Cog, name="Debug"):
    """Owner-only debug commands for testing failure states."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _manager(self):
        cog = self.bot.cogs.get("Stream")
        if cog is None:
            raise RuntimeError("StreamCog not loaded.")
        return cog.manager

    debug_group = app_commands.Group(name="debug", description="Debug commands (owner only).")

    @debug_group.command(name="kill_ffmpeg", description="Kill the ffmpeg process to simulate a crash.")
    @is_owner()
    async def kill_ffmpeg(self, interaction: discord.Interaction) -> None:
        self._manager().debug_kill_ffmpeg()
        await interaction.response.send_message(
            "💀 ffmpeg process killed. Watchdog should detect and restart.", ephemeral=True
        )

    @debug_group.command(name="pause_producer", description="Pause the PCM producer thread (drains buffer).")
    @is_owner()
    async def pause_producer(self, interaction: discord.Interaction) -> None:
        m = self._manager()
        m.debug_pause_producer()
        frames = m.buffer.length
        secs = frames * 20 / 1000
        await interaction.response.send_message(
            f"⏸️ Producer paused. Buffer has **{frames} frames** (~{secs:.0f}s of audio). "
            "Watch the watchdog kick in as it drains.",
            ephemeral=True,
        )

    @debug_group.command(name="resume_producer", description="Resume the PCM producer thread.")
    @is_owner()
    async def resume_producer(self, interaction: discord.Interaction) -> None:
        self._manager().debug_resume_producer()
        await interaction.response.send_message("▶️ Producer resumed.", ephemeral=True)

    @debug_group.command(name="drain_buffer", description="Instantly empty the ring buffer.")
    @is_owner()
    async def drain_buffer(self, interaction: discord.Interaction) -> None:
        self._manager().debug_drain_buffer()
        await interaction.response.send_message(
            "🪣 Buffer drained instantly. Silence frames will be issued until restart completes.",
            ephemeral=True,
        )

    @debug_group.command(name="force_restart", description="Manually trigger a full stream restart.")
    @is_owner()
    async def force_restart(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🔄 Restart triggered…", ephemeral=True)
        await self._manager().restart(reason="manual debug force_restart")
        await interaction.followup.send("✅ Restart complete.", ephemeral=True)

    @debug_group.command(name="bad_url", description="Toggle using an invalid URL on next restart.")
    @app_commands.describe(enabled="Enable or disable bad URL injection")
    @is_owner()
    async def bad_url(self, interaction: discord.Interaction, enabled: bool) -> None:
        self._manager().debug_set_bad_url(enabled)
        state = "ON 💣" if enabled else "OFF ✅"
        await interaction.response.send_message(
            f"Bad URL injection: **{state}**\nRun `/debug force_restart` to trigger a restart with the bad URL.",
            ephemeral=True,
        )

    @debug_group.command(name="set_interval", description="Set the proactive restart interval in seconds.")
    @app_commands.describe(seconds="Interval in seconds (30 for testing, 2100 for production)")
    @is_owner()
    async def set_interval(self, interaction: discord.Interaction, seconds: int) -> None:
        if seconds < 10:
            await interaction.response.send_message(
                "❌ Minimum interval is 10 seconds.", ephemeral=True
            )
            return
        self._manager().debug_set_restart_interval(seconds)
        await interaction.response.send_message(
            f"⏱️ Restart interval set to **{seconds}s**. Scheduler restarted.",
            ephemeral=True,
        )

    @debug_group.command(name="buffer_status", description="Show detailed buffer and stream manager diagnostics.")
    @is_owner()
    async def buffer_status(self, interaction: discord.Interaction) -> None:
        m = self._manager()
        stats = m.buffer.stats()
        ffmpeg_pid = m._ffmpeg_proc.pid if m._ffmpeg_proc else "None"
        producer_alive = m._producer_thread.is_alive() if m._producer_thread else False
        producer_paused = m._producer_paused.is_set()

        embed = discord.Embed(title="🔬 Debug: Stream Manager Status", color=discord.Color.orange())
        embed.add_field(
            name="Buffer",
            value=(
                f"Frames: `{stats['length']}/{stats['capacity']}` ({stats['fill_pct']}%)\n"
                f"Pushed: `{stats['total_pushed']}` | Popped: `{stats['total_popped']}` | Silence: `{stats['total_silence']}`"
            ),
            inline=False,
        )
        embed.add_field(name="ffmpeg PID", value=f"`{ffmpeg_pid}`", inline=True)
        embed.add_field(
            name="Producer thread",
            value=f"{'✅ alive' if producer_alive else '❌ dead'} {'(PAUSED)' if producer_paused else ''}",
            inline=True,
        )
        embed.add_field(name="Restart interval", value=f"`{m.restart_interval_minutes * 60:.0f}s`", inline=True)
        embed.add_field(name="Bad URL injection", value="💣 ON" if m._force_bad_url else "✅ OFF", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DebugCog(bot))

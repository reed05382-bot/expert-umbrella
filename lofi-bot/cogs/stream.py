"""
Stream cog — public-facing slash commands for the lofi stream bot.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.audio_source import BufferedPCMSource
from core.buffer import PCMRingBuffer
from core.stream_manager import StreamManager
from config import LOFI_STREAM_URL

log = logging.getLogger(__name__)


class StreamCog(commands.Cog, name="Stream"):
    """Controls the lofi stream."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.buffer = PCMRingBuffer()
        self.manager = StreamManager(self.buffer, stream_url=LOFI_STREAM_URL)
        self._source: BufferedPCMSource | None = None

    async def cog_load(self) -> None:
        await self.manager.start()
        log.info("StreamCog loaded — StreamManager started.")

    async def cog_unload(self) -> None:
        await self.manager.stop()
        log.info("StreamCog unloaded — StreamManager stopped.")

    def _make_source(self) -> BufferedPCMSource:
        self._source = BufferedPCMSource(self.buffer)
        return self._source

    @app_commands.command(name="join", description="Join your voice channel and start the lofi stream.")
    async def join(self, interaction: discord.Interaction) -> None:
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ You need to be in a voice channel first.", ephemeral=True
            )
            return

        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client

        await interaction.response.defer(ephemeral=True)

        if vc and vc.is_connected():
            await vc.move_to(channel)
        else:
            vc = await channel.connect()

        if not vc.is_playing():
            vc.play(
                self._make_source(),
                after=lambda err: self._on_playback_end(err, vc),
            )

        await interaction.followup.send(
            f"🎵 Streaming lofi in **{channel.name}**!", ephemeral=True
        )
        log.info("Joined voice channel: %s", channel.name)

    @app_commands.command(name="leave", description="Stop the stream and leave the voice channel.")
    async def leave(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if not vc or not vc.is_connected():
            await interaction.response.send_message(
                "❌ I'm not in a voice channel.", ephemeral=True
            )
            return
        await vc.disconnect()
        await interaction.response.send_message("👋 Left the voice channel.", ephemeral=True)
        log.info("Left voice channel.")

    @app_commands.command(name="status", description="Show stream and buffer status.")
    async def status(self, interaction: discord.Interaction) -> None:
        stats = self.buffer.stats()
        vc = interaction.guild.voice_client
        playing = vc.is_playing() if vc else False

        embed = discord.Embed(title="📊 Lofi Stream Status", color=discord.Color.blurple())
        embed.add_field(
            name="Buffer",
            value=(
                f"`{stats['length']}/{stats['capacity']}` frames "
                f"({stats['fill_pct']}%)"
            ),
            inline=False,
        )
        embed.add_field(name="Playing", value="✅ Yes" if playing else "❌ No", inline=True)
        embed.add_field(
            name="Silence frames issued", value=str(stats["total_silence"]), inline=True
        )
        embed.add_field(
            name="Frames pushed/popped",
            value=f"{stats['total_pushed']} / {stats['total_popped']}"
            , inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _on_playback_end(self, error: Exception | None, vc: discord.VoiceClient) -> None:
        if error:
            log.error("Playback ended with error: %s", error)
        else:
            log.info("Playback ended cleanly — restarting playback loop.")

        if vc.is_connected():
            vc.play(
                self._make_source(),
                after=lambda err: self._on_playback_end(err, vc),
            )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.id != self.bot.user.id:
            return
        if before.channel is not None and after.channel is None:
            log.warning(
                "Bot was disconnected from voice channel '%s' — attempting reconnect.",
                before.channel.name,
            )
            await asyncio.sleep(3)
            try:
                vc = await before.channel.connect()
                vc.play(
                    self._make_source(),
                    after=lambda err: self._on_playback_end(err, vc),
                )
                log.info("Auto-reconnected to '%s'.", before.channel.name)
            except Exception as exc:
                log.error("Auto-reconnect failed: %s", exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StreamCog(bot))

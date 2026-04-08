"""
Custom discord.AudioSource that reads from the PCMRingBuffer.
discord.py calls read() every 20ms on its internal audio thread.
"""

from __future__ import annotations

import discord
from core.buffer import PCMRingBuffer


class BufferedPCMSource(discord.AudioSource):
    """
    Reads one 3840-byte PCM frame per call from the ring buffer.
    Returns silence on underrun — never raises, never returns empty bytes
    (which would signal discord.py to stop playback).
    """

    def __init__(self, buffer: PCMRingBuffer) -> None:
        self._buffer = buffer

    def read(self) -> bytes:
        return self._buffer.pop()

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        # Buffer lifetime is managed by StreamManager, not here
        pass

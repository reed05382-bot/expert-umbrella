"""
Ring buffer for PCM audio frames.

Thread safety:
    collections.deque is safe for a single producer calling .append()
    and a single consumer calling .popleft() concurrently under CPython's
    GIL. We add an explicit threading.Lock for correctness and to protect
    the frame-count stats.
"""

from __future__ import annotations

import threading
from collections import deque

from config import BUFFER_MAX_FRAMES, FRAME_SIZE

import logging

log = logging.getLogger(__name__)


class PCMRingBuffer:
    """Fixed-capacity deque of raw PCM frames (bytes objects)."""

    def __init__(self, maxframes: int = BUFFER_MAX_FRAMES) -> None:
        self._maxframes = maxframes
        self._buf: deque[bytes] = deque(maxlen=maxframes)
        self._lock = threading.Lock()

        self._total_pushed: int = 0
        self._total_popped: int = 0
        self._total_silence: int = 0

    def push(self, frame: bytes) -> None:
        """Append one PCM frame. Oldest frame is silently dropped when full."""
        with self._lock:
            self._buf.append(frame)
            self._total_pushed += 1

    def pop(self) -> bytes:
        """
        Return the next PCM frame.
        Returns silence (all-zero bytes) if the buffer is empty so that
        Discord's audio loop keeps running without raising an exception.
        """
        with self._lock:
            if self._buf:
                self._total_popped += 1
                return self._buf.popleft()
            self._total_silence += 1
            if self._total_silence == 1 or self._total_silence % 50 == 0:
                log.warning(
                    "Buffer underrun #%d — returning silence frame",
                    self._total_silence,
                )
            return b"\x00" * FRAME_SIZE

    @property
    def length(self) -> int:
        with self._lock:
            return len(self._buf)

    @property
    def capacity(self) -> int:
        return self._maxframes

    @property
    def fill_percent(self) -> float:
        return (self.length / self._maxframes) * 100

    def stats(self) -> dict:
        with self._lock:
            return {
                "length": len(self._buf),
                "capacity": self._maxframes,
                "fill_pct": round(self.length / self._maxframes * 100, 1),
                "total_pushed": self._total_pushed,
                "total_popped": self._total_popped,
                "total_silence": self._total_silence,
            }

    def clear(self) -> None:
        """Drain all frames (used during testing or hard reset)."""
        with self._lock:
            self._buf.clear()
            log.info("Buffer cleared manually.")
"""
StreamManager — the heart of the bot.

Responsibilities:
1. Extract a fresh stream URL via yt-dlp (run in executor to avoid blocking the event loop).
2. Spawn an ffmpeg subprocess that decodes the stream to raw PCM and pipes it to stdout.
3. Run a producer thread that reads ffmpeg stdout and pushes frames into the PCMRingBuffer.
4. Monitor ffmpeg stderr for fatal errors via FFmpegMonitor.
5. Expose a restart() coroutine protected by asyncio.Lock to prevent concurrent restarts.
6. Proactively schedule restarts every PROACTIVE_RESTART_MINUTES.
7. Run a watchdog task that checks buffer level every WATCHDOG_INTERVAL_SECONDS.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from typing import Optional

import yt_dlp

from config import (
    BUFFER_CRITICAL_THRESHOLD,
    BUFFER_READY_THRESHOLD,
    BUFFER_WARN_THRESHOLD,
    FFMPEG_BEFORE_OPTIONS,
    FRAME_SIZE,
    LOFI_STREAM_URL,
    PROACTIVE_RESTART_MINUTES,
    WATCHDOG_INTERVAL_SECONDS,
    YTDLP_MAX_RETRIES,
    YTDLP_RETRY_BASE_DELAY,
)
from core.buffer import PCMRingBuffer
from core.ffmpeg_monitor import FFmpegMonitor

import logging

log = logging.getLogger(__name__)

_YTDLP_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
}


class StreamManager:
    """Manages the yt-dlp → ffmpeg → PCMRingBuffer pipeline."""

    def __init__(self, buffer: PCMRingBuffer, stream_url: str = LOFI_STREAM_URL) -> None:
        self.buffer = buffer
        self.stream_url = stream_url

        self._restart_lock = asyncio.Lock()
        self._running = False

        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._monitor: Optional[FFmpegMonitor] = None
        self._producer_thread: Optional[threading.Thread] = None
        self._producer_stop = threading.Event()

        # Debug overrides
        self._producer_paused = threading.Event()
        self._force_bad_url: bool = False

        self._watchdog_task: Optional[asyncio.Task] = None
        self._scheduler_task: Optional[asyncio.Task] = None

        self.restart_interval_minutes: float = PROACTIVE_RESTART_MINUTES

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        log.info("StreamManager starting.")
        self._running = True
        await self._do_restart(reason="initial start")
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name="stream-watchdog"
        )
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(), name="stream-scheduler"
        )

    async def stop(self) -> None:
        log.info("StreamManager stopping.")
        self._running = False
        if self._watchdog_task:
            self._watchdog_task.cancel()
        if self._scheduler_task:
            self._scheduler_task.cancel()
        self._kill_ffmpeg()

    async def restart(self, reason: str = "manual") -> None:
        async with self._restart_lock:
            if not self._running:
                return
            await self._do_restart(reason=reason)

    # ── yt-dlp ─────────────────────────────���─────────────────────────────────

    async def _extract_url(self) -> str:
        url = "INVALID://force-error" if self._force_bad_url else self.stream_url
        loop = asyncio.get_running_loop()

        for attempt in range(1, YTDLP_MAX_RETRIES + 1):
            try:
                log.info("yt-dlp extraction attempt %d/%d …", attempt, YTDLP_MAX_RETRIES)
                stream_url: str = await loop.run_in_executor(
                    None, self._blocking_extract, url
                )
                log.info("yt-dlp extracted URL successfully.")
                return stream_url
            except Exception as exc:
                delay = YTDLP_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning(
                    "yt-dlp attempt %d failed: %s — retrying in %.1fs",
                    attempt, exc, delay,
                )
                if attempt < YTDLP_MAX_RETRIES:
                    await asyncio.sleep(delay)

        raise RuntimeError(
            f"yt-dlp failed after {YTDLP_MAX_RETRIES} attempts for {url}"
        )

    @staticmethod
    def _blocking_extract(url: str) -> str:
        with yt_dlp.YoutubeDL(_YTDLP_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ValueError("yt-dlp returned no info.")
            return info.get("url") or info["formats"][-1]["url"]

    # ── ffmpeg ────────────────────────────────────────────────────────────────

    def _spawn_ffmpeg(self, audio_url: str) -> subprocess.Popen:
        before_opts = FFMPEG_BEFORE_OPTIONS.split()
        cmd = [
            "ffmpeg",
            *before_opts,
            "-i", audio_url,
            "-vn",
            "-f", "s16le",
            "-ar", "48000",
            "-ac", "2",
            "pipe:1",
        ]
        log.info("Spawning ffmpeg: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        log.info("ffmpeg spawned with PID %d.", proc.pid)
        return proc

    def _kill_ffmpeg(self) -> None:
        if self._monitor:
            self._monitor.stop()
            self._monitor = None

        if self._producer_thread and self._producer_thread.is_alive():
            self._producer_stop.set()

        if self._ffmpeg_proc:
            try:
                self._ffmpeg_proc.terminate()
                self._ffmpeg_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._ffmpeg_proc.kill()
            except Exception as exc:
                log.warning("Error terminating ffmpeg: %s", exc)
            finally:
                log.info("ffmpeg PID %d terminated.", self._ffmpeg_proc.pid)
                self._ffmpeg_proc = None

    # ── Producer thread ───────────────────────────────────────────────────────

    def _start_producer(self, proc: subprocess.Popen, stop_event: threading.Event) -> threading.Thread:
        def _run() -> None:
            log.debug("Producer thread started.")
            stdout = proc.stdout
            while not stop_event.is_set():
                if self._producer_paused.is_set():
                    time.sleep(0.05)
                    continue

                try:
                    data = stdout.read(FRAME_SIZE)
                except Exception as exc:
                    log.warning("Producer read error: %s", exc)
                    break

                if not data:
                    log.info("Producer: ffmpeg stdout EOF — process likely died.")
                    break

                if len(data) < FRAME_SIZE:
                    data = data + b"\x00" * (FRAME_SIZE - len(data))

                self.buffer.push(data)

            log.debug("Producer thread exiting.")

        t = threading.Thread(target=_run, name="pcm-producer", daemon=True)
        t.start()
        return t

    # ── Core restart sequence ─────────────────────────────────────────────────

    async def _do_restart(self, reason: str) -> None:
        log.info("=== Restart triggered: %s ===", reason)
        start_time = time.monotonic()

        try:
            audio_url = await self._extract_url()
        except RuntimeError as exc:
            log.error("Cannot restart — URL extraction failed: %s", exc)
            return

        new_proc = self._spawn_ffmpeg(audio_url)
        new_stop = threading.Event()
        new_producer = self._start_producer(new_proc, new_stop)

        loop = asyncio.get_running_loop()

        def _on_fatal() -> None:
            log.error("ffmpeg monitor detected fatal error — scheduling restart.")
            asyncio.run_coroutine_threadsafe(
                self.restart(reason="ffmpeg fatal error"), loop
            )

        new_monitor = FFmpegMonitor(new_proc, on_fatal_error=_on_fatal)
        new_monitor.start()

        log.info(
            "Waiting for buffer to reach ready threshold (%d frames) …",
            BUFFER_READY_THRESHOLD,
        )
        timeout = 30.0
        deadline = time.monotonic() + timeout
        while self.buffer.length < BUFFER_READY_THRESHOLD:
            if time.monotonic() > deadline:
                log.error(
                    "Buffer did not reach ready threshold in %.0fs — proceeding anyway.",
                    timeout,
                )
                break
            await asyncio.sleep(0.2)

        self._kill_ffmpeg()

        self._ffmpeg_proc = new_proc
        self._producer_stop = new_stop
        self._producer_thread = new_producer
        self._monitor = new_monitor

        elapsed = time.monotonic() - start_time
        log.info(
            "=== Restart complete in %.2fs | buffer: %d/%d frames (%.1f%%) ===",
            elapsed,
            self.buffer.length,
            self.buffer.capacity,
            self.buffer.fill_percent,
        )

    # ── Background tasks ──────────────────────────────────────────────────────

    async def _watchdog_loop(self) -> None:
        log.info("Watchdog started (interval: %ds).", WATCHDOG_INTERVAL_SECONDS)
        try:
            while self._running:
                await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
                length = self.buffer.length

                if length == 0:
                    log.error("WATCHDOG: Buffer empty! Emergency restart.")
                    await self.restart(reason="watchdog — buffer empty")
                elif length <= BUFFER_CRITICAL_THRESHOLD:
                    log.warning(
                        "WATCHDOG: Buffer critical (%d frames / %.1f%%) — emergency restart.",
                        length, self.buffer.fill_percent,
                    )
                    await self.restart(reason="watchdog — buffer critical")
                elif length <= BUFFER_WARN_THRESHOLD:
                    log.warning(
                        "WATCHDOG: Buffer low (%d frames / %.1f%%).",
                        length, self.buffer.fill_percent,
                    )
                else:
                    log.debug(
                        "WATCHDOG: Buffer healthy (%d frames / %.1f%%).",
                        length, self.buffer.fill_percent,
                    )
        except asyncio.CancelledError:
            log.info("Watchdog task cancelled.")

    async def _scheduler_loop(self) -> None:
        log.info(
            "Scheduler started (interval: %.0f min).", self.restart_interval_minutes
        )
        try:
            while self._running:
                await asyncio.sleep(self.restart_interval_minutes * 60)
                log.info("Scheduler: proactive restart triggered.")
                await self.restart(reason="scheduled proactive restart")
        except asyncio.CancelledError:
            log.info("Scheduler task cancelled.")

    # ── Debug helpers ─────────────────────────────────────────────────────────

    def debug_pause_producer(self) -> None:
        self._producer_paused.set()
        log.warning("[DEBUG] Producer paused.")

    def debug_resume_producer(self) -> None:
        self._producer_paused.clear()
        log.info("[DEBUG] Producer resumed.")

    def debug_kill_ffmpeg(self) -> None:
        log.warning("[DEBUG] Manually killing ffmpeg process.")
        if self._ffmpeg_proc:
            self._ffmpeg_proc.kill()

    def debug_drain_buffer(self) -> None:
        log.warning("[DEBUG] Manually draining buffer.")
        self.buffer.clear()

    def debug_set_bad_url(self, enabled: bool) -> None:
        self._force_bad_url = enabled
        log.warning("[DEBUG] Force bad URL: %s", enabled)

    def debug_set_restart_interval(self, seconds: int) -> None:
        self.restart_interval_minutes = seconds / 60
        log.info("[DEBUG] Restart interval set to %ds.", seconds)
        if self._scheduler_task:
            self._scheduler_task.cancel()
            loop = asyncio.get_running_loop()
            self._scheduler_task = loop.create_task(
                self._scheduler_loop(), name="stream-scheduler"
            )

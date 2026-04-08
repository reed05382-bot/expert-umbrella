from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ── Bot ───────────────────────────────────────────────────────────────────────
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
BOT_OWNER_ID: int = int(os.getenv("BOT_OWNER_ID", "0"))
DEV_GUILD_ID: int | None = (
    int(os.getenv("DEV_GUILD_ID")) if os.getenv("DEV_GUILD_ID") else None
)

# ── Stream ────────────────────────────────────────────────────────────────────
LOFI_STREAM_URL: str = os.getenv(
    "LOFI_STREAM_URL", "https://www.youtube.com/watch?v=jfKfPfyJRdk"
)

# ── Audio ─────────────────────────────────────────────────────────────────────
SAMPLE_RATE: int = 48_000          # Hz  — Discord requirement
CHANNELS: int = 2                  # Stereo
SAMPLE_WIDTH: int = 2              # Bytes per sample (s16le)
FRAME_DURATION_MS: int = 20        # Discord reads every 20 ms
FRAME_SIZE: int = (
    SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * FRAME_DURATION_MS // 1000
)                                  # = 3840 bytes

# ── Buffer ────────────────────────────────────────────────────────────────────
BUFFER_DURATION_SECONDS: int = 30
BUFFER_MAX_FRAMES: int = (
    BUFFER_DURATION_SECONDS * 1000 // FRAME_DURATION_MS
)                                  # = 1500 frames

BUFFER_READY_THRESHOLD: int = 150  # 3 seconds — min frames before source is "ready"
BUFFER_WARN_THRESHOLD: int = 450   # 9 seconds — log warning
BUFFER_CRITICAL_THRESHOLD: int = 75  # 1.5 seconds — trigger emergency restart

# ── Restart / Scheduling ──────────────────────────────────────────────────────
PROACTIVE_RESTART_MINUTES: int = 35
WATCHDOG_INTERVAL_SECONDS: int = 5

# ── yt-dlp ────────────────────────────────────────────────────────────────────
YTDLP_MAX_RETRIES: int = 5
YTDLP_RETRY_BASE_DELAY: float = 2.0

# ── ffmpeg ────────────────────────────────────────────────────────────────────
FFMPEG_BEFORE_OPTIONS: str = (
    "-reconnect 1 "
    "-reconnect_streamed 1 "
    "-reconnect_delay_max 5 "
    "-reconnect_at_eof 1"
)

FFMPEG_FATAL_PATTERNS: list[str] = [
    "Connection refused",
    "Network is unreachable",
    "No route to host",
    "404 Not Found",
    "403 Forbidden",
    "End of file",
    "Invalid data found",
    "moov atom not found",
]
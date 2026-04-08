# 🎵 Lofi Hip Hop Discord Bot

A production-quality Discord bot that re-streams a YouTube lofi hip hop live stream into a Discord voice channel with **zero perceived interruptions**, using a PCM ring buffer architecture.

---

## Why the Ring Buffer?

Naive implementations pipe YouTube audio directly through ffmpeg into Discord. When ffmpeg hiccups (network blip, HLS segment gap, URL expiry), audio stops — sometimes permanently until the bot is restarted.

This bot solves that with a **30-second PCM ring buffer** sitting between ffmpeg and Discord:

- ffmpeg fills the buffer continuously
- Discord reads from the buffer continuously
- When ffmpeg needs to restart, the buffer keeps Discord fed during the gap
- Restarts complete in ~5-10 seconds, well within the 30-second buffer window
- Users hear **nothing** — no gap, no stutter

---

## Architecture Overview

```
YouTube Live Stream
        ↓
      yt-dlp          (extracts best audio URL, run in thread executor)
        ↓
      ffmpeg          (decodes HLS → raw PCM s16le 48kHz stereo)
        ↓
  Producer Thread     (reads ffmpeg stdout, pushes 3840-byte frames)
        ↓
  PCM Ring Buffer     (deque of 1500 frames = 30 seconds)
        ↓
  BufferedPCMSource   (discord.AudioSource subclass, pops frames every 20ms)
        ↓
  Discord Voice Channel

Background tasks:
  • FFmpegMonitor    — watches ffmpeg stderr for fatal error patterns
  • Watchdog         — checks buffer level every 5s, triggers restart if critical
  • Scheduler        — proactively restarts every 35 minutes to prevent URL expiry
  • Restart Lock     — asyncio.Lock prevents concurrent restarts racing each other
```

---

## Prerequisites

- Python 3.10 or newer
- ffmpeg installed and on your PATH
- A Discord bot token

### Install ffmpeg

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html and add to PATH.

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/reed05382-bot/expert-umbrella.git
cd expert-umbrella/lofi-bot

# 2. (Recommended) Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up your environment file
cp .env.example .env
nano .env   # fill in your values (see below)

# 5. Run the bot
python bot.py
```

> ⚠️ The bot must be run from inside the `lofi-bot/` directory.

---

## Environment Variables

Edit `.env` with the following values:

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | ✅ Yes | Your bot token from the Discord Developer Portal |
| `BOT_OWNER_ID` | ✅ Yes | Your Discord user ID (right-click your name → Copy User ID) |
| `LOFI_STREAM_URL` | No | YouTube URL to stream (defaults to lofi girl) |
| `DEV_GUILD_ID` | No | Server ID for instant slash command sync during development |

### How to get your Discord bot token
1. Go to https://discord.com/developers/applications
2. Create a New Application
3. Go to Bot → Reset Token → copy it
4. Under Privileged Gateway Intents, enable **Server Members Intent** and **Voice** permissions
5. Go to OAuth2 → URL Generator → select `bot` + `applications.commands`
6. Under Bot Permissions select: `Connect`, `Speak`, `View Channels`
7. Use the generated URL to invite the bot to your server

### How to get your BOT_OWNER_ID
1. In Discord, go to Settings → Advanced → Enable Developer Mode
2. Right-click your username → Copy User ID

---

## Slash Commands

| Command | Description |
|---|---|
| `/join` | Join your current voice channel and start streaming |
| `/leave` | Stop the stream and leave the voice channel |
| `/status` | Show buffer fill level, playback state, and frame stats |

---

## Debug Commands (Owner Only)

All debug commands are under the `/debug` group and are only usable by the `BOT_OWNER_ID`.

| Command | What it tests |
|---|---|
| `/debug kill_ffmpeg` | Kills the ffmpeg process — tests watchdog crash recovery |
| `/debug pause_producer` | Pauses the producer thread — tests buffer drain detection |
| `/debug resume_producer` | Resumes the producer thread |
| `/debug drain_buffer` | Instantly empties the buffer — tests silence fallback + emergency restart |
| `/debug force_restart` | Manually triggers a full restart — tests the restart coordinator |
| `/debug bad_url true/false` | Injects an invalid URL on next restart — tests exponential backoff |
| `/debug set_interval <seconds>` | Changes the scheduled restart interval (use 30 for testing) |
| `/debug buffer_status` | Shows ffmpeg PID, producer thread state, buffer stats, interval |

---

## Testing Sequence

Run these in order to validate every failure mode:

```
Step 1  — /status                          Confirm buffer is filling to 100%
Step 2  — /join                            Join voice, confirm audio plays
Step 3  — /debug buffer_status             Confirm all green, ffmpeg PID present
Step 4  — /debug set_interval 30           Set scheduler to 30s for fast testing
Step 5  — wait 30 seconds                  Observe proactive restart in logs, no audio gap heard
Step 6  — /debug pause_producer            Buffer starts draining (watch logs every 5s)
Step 7  — /debug buffer_status (repeat)    Watch fill % drop toward 0
Step 8  — watchdog triggers at ~3s left    Observe emergency restart in logs, audio continues
Step 9  — /debug resume_producer           Clean up
Step 10 — /debug drain_buffer              Instant empty → silence frames → restart
Step 11 — /debug kill_ffmpeg               Simulate process crash → observe recovery
Step 12 — /debug bad_url true              Then /debug force_restart → observe backoff retries in logs
Step 13 — /debug bad_url false             Restore good URL
Step 14 — Manually kick bot from channel   Observe on_voice_state_update + auto-reconnect
```

---

## Keeping the Bot Running

To run the bot persistently on Linux:

```bash
# Using screen
screen -S lofi-bot
cd expert-umbrella/lofi-bot
python bot.py
# Ctrl+A then D to detach

# Using systemd (recommended for production)
# Create /etc/systemd/system/lofi-bot.service
```

---

## Updating yt-dlp

If the bot stops working due to a YouTube change:
```bash
pip install -U yt-dlp
```
This is the most common fix for sudden stream failures.

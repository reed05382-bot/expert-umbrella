"""
Monitors ffmpeg's stderr stream in a daemon thread.
Calls on_fatal_error callback when a fatal error pattern is detected.
"""

from __future__ import annotations

import re
import threading
from subprocess import Popen
from typing import Callable

from config import FFMPEG_FATAL_PATTERNS

import logging

log = logging.getLogger(__name__)

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FFMPEG_FATAL_PATTERNS]


class FFmpegMonitor:
    """
    Reads ffmpeg stderr line-by-line in a daemon thread.
    Calls `on_fatal_error` (thread-safe callback) when a fatal line is found.
    """

    def __init__(self,
        process: Popen,
        on_fatal_error: Callable[[], None],
    ) -> None:
        self._process = process
        self._on_fatal_error = on_fatal_error
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="ffmpeg-stderr-monitor", daemon=True
        )

    def start(self) -> None:
        self._thread.start()
        log.debug("ffmpeg stderr monitor started.")

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        try:
            stderr = self._process.stderr
            if stderr is None:
                return
            for raw_line in iter(stderr.readline, b""):
                if self._stop_event.is_set():
                    break
                try:
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    continue

                log.debug("[ffmpeg] %s", line)

                for pattern in _COMPILED_PATTERNS:
                    if pattern.search(line):
                        log.warning(
                            "ffmpeg fatal pattern matched: %r — line: %s",
                            pattern.pattern,
                            line,
                        )
                        self._on_fatal_error()
                        return
        except ValueError:
            pass
        except Exception as exc:
            log.exception("Unexpected error in ffmpeg monitor: %s", exc)
        finally:
            log.debug("ffmpeg stderr monitor exiting.")
# Changes

- Replace deprecated `asyncio.get_event_loop()` with `asyncio.get_running_loop()` in `debug_set_restart_interval`.

## Description

This change addresses the issue with the deprecated call that raises a DeprecationWarning in Python 3.10+ and can raise a RuntimeError when called from a context with no running loop. It ensures compatibility with the latest Python versions.

## Timestamp

This change was made on 2026-04-09 00:10:22 (UTC).
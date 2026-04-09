# Fix: replace deprecated asyncio.get_event_loop() with asyncio.get_running_loop()

Replaces the deprecated `asyncio.get_event_loop()` call in `debug_set_restart_interval` with `asyncio.get_running_loop()`. This fixes a DeprecationWarning in Python 3.10+ and prevents a potential RuntimeError when there is no current event loop.
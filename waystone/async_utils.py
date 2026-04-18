"""
Background asyncio event loop for non-GTK work (network, DB).

GTK is single-threaded.  All coroutines here run in a dedicated daemon
thread.  To touch GTK from a coroutine, wrap the call in GLib.idle_add().
"""

import asyncio
import threading
from typing import Coroutine

_loop: asyncio.AbstractEventLoop | None = None


def start() -> None:
    """Start the background event loop.  Call once before app.run()."""
    global _loop
    _loop = asyncio.new_event_loop()
    t = threading.Thread(target=_run_loop, daemon=True, name="waystone-async")
    t.start()


def _run_loop() -> None:
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def stop() -> None:
    """Signal the background loop to stop.  Call on app shutdown."""
    if _loop and _loop.is_running():
        _loop.call_soon_threadsafe(_loop.stop)


def run(coro: Coroutine) -> "concurrent.futures.Future":
    """
    Schedule *coro* on the background loop.
    Returns a concurrent.futures.Future (not asyncio.Future).
    Safe to call from the GTK main thread.
    """
    if _loop is None:
        raise RuntimeError("async_utils.start() was not called")
    return asyncio.run_coroutine_threadsafe(coro, _loop)


def get_loop() -> asyncio.AbstractEventLoop:
    if _loop is None:
        raise RuntimeError("async_utils.start() was not called")
    return _loop

"""Keep a long foreground benchmark awake without changing persistent power settings."""

import ctypes
import sys
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def prevent_idle_sleep() -> Iterator[bool]:
    if sys.platform != "win32":
        yield False
        return
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    change = kernel.SetThreadExecutionState
    change.argtypes = [wintypes.DWORD]
    change.restype = wintypes.DWORD
    enabled = bool(change(0x80000001))  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED; display may sleep.
    try:
        yield enabled
    finally:
        if enabled:
            change(0x80000000)

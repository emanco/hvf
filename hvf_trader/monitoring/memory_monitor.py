"""System memory monitor.

Reads physical memory via Windows ctypes (avoids adding psutil as a
dependency on the VPS). Used by the main scanner loop to log memory in
the heartbeat and send a Telegram alert when free memory drops below
a configurable threshold.

Falls back gracefully on non-Windows hosts (returns None) so local
backtests / dev environments don't break.
"""
import ctypes
import logging
import platform
from typing import Optional

logger = logging.getLogger(__name__)


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def read_memory_mb() -> Optional[dict]:
    """Return dict with total_mb, avail_mb, percent_used. None if not Windows."""
    if platform.system() != "Windows":
        return None
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return {
            "total_mb": stat.ullTotalPhys / (1024 * 1024),
            "avail_mb": stat.ullAvailPhys / (1024 * 1024),
            "percent_used": int(stat.dwMemoryLoad),
        }
    except Exception as e:  # pragma: no cover
        logger.warning("Memory read failed: %s", e)
        return None

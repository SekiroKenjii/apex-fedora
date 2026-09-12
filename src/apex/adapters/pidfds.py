"""A file descriptor that names one process, on any Linux interpreter.

Some interpreter builds omit `os.pidfd_open` although the kernel provides the call, and a
kill that falls back to a bare process number would reopen the reuse window the descriptor
exists to close. The two system calls are made directly when the module does not expose
them; their numbers are the same on every Linux architecture.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys

from apex.kernel import errors, refusals

LINUX = "linux"
SYS_PIDFD_SEND_SIGNAL = 424
SYS_PIDFD_OPEN = 434


def available() -> bool:
    return sys.platform == LINUX


def open_process(process: int) -> int:
    """A descriptor for the process, or `OSError` if it is gone."""
    _require_linux()
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(process)
    return _syscall(SYS_PIDFD_OPEN, process, 0)


def send_signal(descriptor: int, signal_number: int) -> None:
    _require_linux()
    if hasattr(os, "pidfd_open"):
        import signal  # noqa: PLC0415

        signal.pidfd_send_signal(descriptor, signal_number)
        return
    _syscall(SYS_PIDFD_SEND_SIGNAL, descriptor, signal_number, None, 0)


def _require_linux() -> None:
    if not available():
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.MACHINE_IDENTITY_UNCHECKABLE,
            subject=f"{sys.platform} has no process descriptors",
        )


def _syscall(number: int, *arguments: object) -> int:
    library = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    result = int(library.syscall(ctypes.c_long(number), *arguments))
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return result

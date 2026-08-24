"""Linux credential-handoff and process-hardening controls."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def read_handoff_fd(fd: int, *, label: str) -> str:
    """Read one bounded anonymous descriptor and close it before tools run."""
    if not isinstance(fd, int) or fd < 3:
        raise RuntimeError(f"{label} file descriptor is invalid")
    chunks: list[bytes] = []
    total = 0
    try:
        while chunk := os.read(fd, 4096):
            total += len(chunk)
            if total > 16_384:
                raise RuntimeError(f"{label} handoff is too large")
            chunks.append(chunk)
    finally:
        os.close(fd)
    value = b"".join(chunks)
    if value.endswith(b"\n"):
        value = value[:-1]
    if not value or b"\x00" in value:
        raise RuntimeError(f"{label} handoff is invalid")
    return value.decode("utf-8")


def harden_linux_model_loop_parent() -> dict[str, Any]:
    """Disable dumpability and reject Linux processes with CAP_SYS_PTRACE."""
    if sys.platform != "linux" or not Path("/proc/self/status").is_file():
        raise RuntimeError("credential isolation requires Linux procfs")
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    pr_set_dumpable = 4
    pr_get_dumpable = 3
    if prctl(pr_set_dumpable, 0, 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        raise RuntimeError(f"could not disable process dumpability: errno {errno}")
    dumpable = prctl(pr_get_dumpable, 0, 0, 0, 0)
    if dumpable != 0:
        raise RuntimeError(f"model-loop parent remains dumpable: {dumpable}")
    status = Path("/proc/self/status").read_text(encoding="utf-8")
    cap_eff_line = next((line for line in status.splitlines() if line.startswith("CapEff:")), None)
    if cap_eff_line is None:
        raise RuntimeError("Linux process status omitted CapEff")
    cap_eff = int(cap_eff_line.split(":", 1)[1].strip(), 16)
    cap_sys_ptrace = bool(cap_eff & (1 << 19))
    if cap_sys_ptrace:
        raise RuntimeError("credential isolation requires CAP_SYS_PTRACE to be absent")
    return {
        "platform": "linux",
        "procfs": True,
        "dumpable": dumpable,
        "cap_eff_hex": f"{cap_eff:x}",
        "cap_sys_ptrace": False,
    }

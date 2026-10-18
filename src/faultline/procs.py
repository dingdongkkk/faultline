"""Supervised child processes.

Each child gets its own session/process group. On deadline or cancellation
the whole group gets SIGTERM, then SIGKILL after a grace period, and the
leader is reaped. After a normal exit, surviving group members (background
processes a test left behind) are killed too. This is cleanup, not a
sandbox: a grandchild that calls setsid() escapes the group.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ChildResult:
    returncode: int | None
    timed_out: bool
    cancelled: bool
    duration_ms: int
    stdout_tail: str
    stderr_tail: str
    pgid: int


def _tail(f, limit: int) -> str:
    f.flush()
    size = f.seek(0, os.SEEK_END)
    f.seek(max(0, size - limit))
    data = f.read()
    text = data.decode("utf-8", "replace")
    return ("[...truncated...]\n" + text) if size > limit else text


def _signal_group(pgid: int, sig: int) -> bool:
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def terminate_group(proc: subprocess.Popen, pgid: int, grace_s: float) -> None:
    _signal_group(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        pass
    _signal_group(pgid, signal.SIGKILL)
    proc.wait()  # reap the leader


def run_child(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout_s: float,
    grace_s: float = 2.0,
    tail_bytes: int = 16 * 1024,
    cancel: threading.Event | None = None,
) -> ChildResult:
    start = time.monotonic()
    deadline = start + max(0.0, timeout_s)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        pgid = proc.pid  # session leader: pgid == pid
        timed_out = cancelled = False
        while True:
            try:
                proc.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancel is not None and cancel.is_set():
                cancelled = True
            elif time.monotonic() >= deadline:
                timed_out = True
            if timed_out or cancelled:
                terminate_group(proc, pgid, grace_s)
                break
        # Kill anything the test left running in its group.
        _signal_group(pgid, signal.SIGKILL)
        return ChildResult(
            returncode=None if (timed_out or cancelled) else proc.returncode,
            timed_out=timed_out,
            cancelled=cancelled,
            duration_ms=int((time.monotonic() - start) * 1000),
            stdout_tail=_tail(out, tail_bytes),
            stderr_tail=_tail(err, tail_bytes),
            pgid=pgid,
        )

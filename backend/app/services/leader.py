"""Postgres advisory-lock based leader election for scheduler jobs.

Each scheduled job acquires a session-level advisory lock keyed by job name.
Only one replica holds the lock at a time; others see `acquired=False` and
skip silently. The lock is released when the connection closes — so a crash
does not strand the lock.
"""
from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from typing import Iterator

from app.models.database import engine

logger = logging.getLogger(__name__)


def _lock_key(name: str) -> int:
    """Deterministic signed bigint within positive 63-bit range."""
    h = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    val = int.from_bytes(h, "big", signed=True)
    return val & 0x7FFF_FFFF_FFFF_FFFF


@contextmanager
def leader_lock(name: str) -> Iterator[bool]:
    """Yield True if this caller owns the advisory lock for `name`, else False.

    Failures during acquisition (DB unreachable, etc.) yield False rather than
    raising — schedulers should skip a tick rather than crash.
    """
    key = _lock_key(name)
    try:
        conn = engine.connect()
    except Exception:
        logger.exception("leader_lock(%s): could not connect", name)
        yield False
        return

    try:
        try:
            acquired = bool(conn.exec_driver_sql(
                "SELECT pg_try_advisory_lock(%s)", (key,)
            ).scalar())
        except Exception:
            logger.exception("leader_lock(%s): pg_try_advisory_lock failed", name)
            yield False
            return

        if not acquired:
            yield False
            return

        try:
            yield True
        finally:
            try:
                conn.exec_driver_sql("SELECT pg_advisory_unlock(%s)", (key,))
            except Exception:
                logger.exception("leader_lock(%s): unlock failed (lock will release on close)", name)
    finally:
        conn.close()

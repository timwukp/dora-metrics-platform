"""Test fixtures.

We use SQLite in-memory for unit tests — fast, hermetic, and good enough for
the SQL we actually exercise (basic SELECT/INSERT, no Postgres-specific
features in the model layer). Anything that needs Postgres semantics
(advisory locks, ON CONFLICT) belongs in `tests/integration/` and runs
against a real Postgres in CI.
"""
from __future__ import annotations

import os

# Settings reads env at import time, and the project's default DB URL is
# Postgres-flavoured. Force a SQLite URL *before* importing anything from
# `app.*` so settings validation passes in the test env.
os.environ.setdefault("DORA_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DORA_API_KEY", "test-key")
os.environ.setdefault("DORA_GITHUB_REPOS", "octo/repo")
os.environ.setdefault("DORA_GITHUB_WEBHOOK_SECRET", "test-secret")

import pytest  # noqa: E402
from sqlalchemy import BigInteger, create_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models.database import Base  # noqa: E402


# SQLite only supports AUTOINCREMENT on INTEGER PRIMARY KEY; production uses
# BigInteger to avoid 32-bit row-count exhaustion. Compile BigInteger to
# INTEGER on the sqlite dialect so primary keys auto-assign in tests.
@compiles(BigInteger, "sqlite")
def _bigint_to_int(element, compiler, **kw):  # pragma: no cover
    return "INTEGER"


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()

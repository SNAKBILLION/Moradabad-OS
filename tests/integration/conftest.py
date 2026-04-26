"""Integration test fixtures.

Tests in this directory require a live Postgres. If the database is not
reachable, they SKIP with a clear message — they never silently pass and
they never hang trying to connect.

The fixture uses a savepoint-rollback pattern so tests are isolated without
needing to drop and recreate the schema between runs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mos.db import make_engine, make_session_factory


def _database_url() -> str:
    return os.environ.get(
        "MOS_TEST_DATABASE_URL",
        "postgresql+psycopg://mos:mos_dev@localhost:5432/mos",
    )


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = _database_url()
    eng = make_engine(url)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover - environmental
        pytest.skip(
            f"Postgres not reachable at {url}: {e}. "
            "Run `docker compose up -d postgres` or set MOS_TEST_DATABASE_URL."
        )
    # Ensure migrations are applied. We don't run them from the test — that
    # is the developer's responsibility (see README). We just check one table.
    with eng.connect() as conn:
        try:
            conn.execute(text("SELECT 1 FROM jobs LIMIT 0"))
        except Exception as e:  # pragma: no cover - environmental
            pytest.skip(
                f"`jobs` table not present ({e}). "
                "Run `alembic upgrade head` first."
            )
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Wraps every test in an outer transaction that is rolled back at teardown.

    This keeps tests fast (no drop/create) and isolated (no state leaks).
    Requires SQLAlchemy's 'SAVEPOINT' support via nested transactions.
    """
    connection = engine.connect()
    outer_txn = connection.begin()

    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        future=True,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield factory
    finally:
        outer_txn.rollback()
        connection.close()

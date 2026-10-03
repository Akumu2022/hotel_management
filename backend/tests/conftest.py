"""Tests run against a real PostgreSQL database (DECISIONS D2).

Each test gets a session inside an outer transaction that is rolled back afterwards; the app's
`session.commit()` only releases a savepoint. Tests that need real commits across connections
(concurrency) use the `committed` fixture, which truncates the tables afterwards.
"""

import os

os.environ.setdefault("RUN_JOBS", "0")  # tests call jobs directly
import subprocess
import sys
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_config
from app.core.db import get_session
from app.core.ratelimit import limiter
from app.main import app
from app.models import Base, Setting
from app.services import settings as settings_service

TEST_URL = os.environ.get("TEST_DATABASE_URL") or get_config().test_database_url


def _alembic(*args: str) -> None:
    env = {**os.environ, "ALEMBIC_DATABASE_URL": TEST_URL}
    subprocess.run([sys.executable, "-m", "alembic", *args], check=True, env=env)


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")


@pytest.fixture(scope="session")
async def engine(migrated_db):
    eng = create_async_engine(TEST_URL, pool_size=30, max_overflow=10)
    yield eng
    await eng.dispose()


@pytest.fixture
async def conn(engine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as connection:
        outer = await connection.begin()
        try:
            yield connection
        finally:
            await outer.rollback()


def _session_on(connection: AsyncConnection) -> AsyncSession:
    return AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
async def db(conn) -> AsyncIterator[AsyncSession]:
    session = _session_on(conn)
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
async def client(conn, db) -> AsyncIterator[AsyncClient]:
    """Each request gets its own session (as in production) on the test connection, so it sees
    the test's data and its writes roll back with the test."""

    async def _session():
        await db.flush()
        session = _session_on(conn)
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


_SKIP = {"settings", "alembic_version"}


@pytest.fixture
async def committed(engine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory whose commits are real. Data is wiped afterwards (and the seeded
    settings restored), bypassing the append-only triggers for cleanup only."""
    yield async_sessionmaker(engine, expire_on_commit=False)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables if t.name not in _SKIP)
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        # CASCADE also empties `settings` (it references users), so restore the seed.
        await conn.execute(text(f"TRUNCATE {tables}, settings CASCADE"))
        await conn.execute(insert(Setting), settings_service.seed_rows())


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    limiter.reset()


@pytest.fixture(autouse=True)
def _no_network_routing(monkeypatch):
    """Tests never call the routing server: road distance falls back to straight line."""
    from app.services import routing

    async def _offline(*_args):
        return None

    monkeypatch.setattr(routing, "_osrm", _offline)
    routing._cache.clear()

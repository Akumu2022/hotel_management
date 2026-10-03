import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import get_config
from app.models import Base

target_metadata = Base.metadata


def _url() -> str:
    # Tests point migrations at the test database via ALEMBIC_DATABASE_URL.
    return os.environ.get("ALEMBIC_DATABASE_URL") or get_config().database_url


def _do_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())

from __future__ import annotations

from gitforce.app.config.settings import get_settings


async def create_checkpointer():
    """Create a LangGraph checkpointer for durable workflow state.

    - PostgreSQL (AsyncPostgresSaver) when DATABASE_URL is postgres. Setup
      (DDL) is applied on creation.
    - In-memory MemorySaver for sqlite/dev/tests.

    Note: PostgreSQL is the production target (Requirement section 35); the
    in-memory saver is intentionally the dev/test fallback so the app runs
    without external services.
    """
    settings = get_settings()
    url = settings.database_url

    if url.startswith("postgres"):
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool

            dsn = url.replace("postgresql+asyncpg://", "postgresql://")
            pool = AsyncConnectionPool(conninfo=dsn, max_size=10)
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            return saver
        except ImportError:
            pass

    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()
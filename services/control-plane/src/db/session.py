"""
Database Session and Engine Configuration for Software Capsule Platform
"""
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

# Primary async database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://capsule_user:capsule_dev_password@localhost:5432/capsule_control"
)

# Synchronous database URL (used for migrations and synchronous maintenance tools)
SYNC_DATABASE_URL = os.getenv(
    "SYNC_DATABASE_URL",
    DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
)

# Async engine for application runtime & API queries.
# NullPool avoids cross-loop connection reuse issues on Windows / pytest-asyncio.
async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Sync engine for synchronous tasks (e.g. Alembic / direct scripts)
sync_engine = create_engine(
    SYNC_DATABASE_URL,
    echo=False,
    poolclass=NullPool,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async generator providing a transactional database session for FastAPI."""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def db_context() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager providing a transactional database session for scripts/tests."""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


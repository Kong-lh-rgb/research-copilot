from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from typing import AsyncGenerator

_engine = None
_session_factory = None


def init_db(database_url: str) -> None:
    """Initialize async SQLAlchemy engine and session factory."""
    global _engine, _session_factory

    url = database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    _engine = create_async_engine(url, echo=False, pool_size=5, max_overflow=10)
    _session_factory = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )


async def create_tables() -> None:
    """Create all tables in the database (idempotent)."""
    from app.db.models import Base

    assert _engine is not None, "DB not initialised – call init_db() first"
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session per request."""
    assert _session_factory is not None, "DB not initialised"
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_session_factory():
    """Return the raw session factory (for use outside of request context)."""
    return _session_factory

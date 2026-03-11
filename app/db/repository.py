import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Thread, User


# ─── User ──────────────────────────────────────────────────────────────────────

async def create_user(
    session: AsyncSession, username: str, password_hash: str
) -> User:
    user = User(username=username, password_hash=password_hash)
    session.add(user)
    await session.flush()
    return user


async def get_user_by_username(
    session: AsyncSession, username: str
) -> Optional[User]:
    result = await session.execute(
        select(User).where(User.username == username)
    )
    return result.scalar_one_or_none()


async def get_user_by_id(
    session: AsyncSession, user_id: uuid.UUID
) -> Optional[User]:
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


# ─── Thread ────────────────────────────────────────────────────────────────────

async def get_or_create_thread(
    session: AsyncSession,
    thread_id: str,
    user_id: uuid.UUID,
    title: str = "新对话",
) -> Thread:
    result = await session.execute(
        select(Thread).where(Thread.id == thread_id)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        thread = Thread(id=thread_id, user_id=user_id, title=title)
        session.add(thread)
        await session.flush()
    return thread


async def list_threads(
    session: AsyncSession, user_id: uuid.UUID
) -> list[Thread]:
    result = await session.execute(
        select(Thread)
        .where(Thread.user_id == user_id)
        .order_by(Thread.updated_at.desc())
    )
    return list(result.scalars().all())


async def update_thread_title(
    session: AsyncSession, thread_id: str, title: str
) -> None:
    await session.execute(
        update(Thread)
        .where(Thread.id == thread_id)
        .values(title=title, updated_at=datetime.now(timezone.utc))
    )


async def touch_thread(session: AsyncSession, thread_id: str) -> None:
    """Bump updated_at to now."""
    await session.execute(
        update(Thread)
        .where(Thread.id == thread_id)
        .values(updated_at=datetime.now(timezone.utc))
    )


async def delete_thread(
    session: AsyncSession, thread_id: str, user_id: uuid.UUID
) -> None:
    result = await session.execute(
        select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    )
    thread = result.scalar_one_or_none()
    if thread:
        await session.delete(thread)


# ─── Message ───────────────────────────────────────────────────────────────────

async def add_message(
    session: AsyncSession,
    thread_id: str,
    role: str,
    content: str,
    meta: Optional[dict] = None,
) -> Message:
    message = Message(thread_id=thread_id, role=role, content=content, meta=meta)
    session.add(message)
    await session.flush()
    return message


async def get_thread_messages(
    session: AsyncSession, thread_id: str
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.created_at.asc())
    )
    return list(result.scalars().all())


async def get_message_count(
    session: AsyncSession, thread_id: str
) -> int:
    """返回指定 thread 的消息总数。"""
    from sqlalchemy import func
    result = await session.execute(
        select(func.count()).select_from(Message).where(Message.thread_id == thread_id)
    )
    return result.scalar() or 0


# ─── Thread Summary Cache ──────────────────────────────────────────────────────

async def get_thread_summary(
    session: AsyncSession, thread_id: str
) -> tuple[Optional[str], Optional[int]]:
    """返回 (cached_summary, summary_msg_count)。未缓存时都为 None。"""
    result = await session.execute(
        select(Thread.summary, Thread.summary_msg_count)
        .where(Thread.id == thread_id)
    )
    row = result.one_or_none()
    if row is None:
        return None, None
    return row.summary, row.summary_msg_count


async def update_thread_summary(
    session: AsyncSession,
    thread_id: str,
    summary: str,
    msg_count: int,
) -> None:
    """将 LLM 生成的摘要缓存回 Thread 表。"""
    await session.execute(
        update(Thread)
        .where(Thread.id == thread_id)
        .values(summary=summary, summary_msg_count=msg_count)
    )


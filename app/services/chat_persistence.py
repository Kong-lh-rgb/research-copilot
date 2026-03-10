import uuid as _uuid
from typing import Optional


async def load_thread_history(
    thread_id: str,
    limit: int = 20,
) -> list[dict]:
    """从数据库加载指定 thread 的最近 N 条消息，返回 OpenAI 格式的 list。
    若数据库不可用或 thread 不存在，安全地返回空列表。
    """
    try:
        from app.db.session import get_session_factory
        from app.db import repository

        factory = get_session_factory()
        if factory is None:
            return []

        async with factory() as session:
            messages = await repository.get_thread_messages(session, thread_id)

        # 只取最近 limit 条，保留时间顺序
        recent = messages[-limit:] if len(messages) > limit else messages
        return [{"role": m.role, "content": m.content} for m in recent]
    except Exception:
        return []


def extract_user_id_from_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        from jose import jwt
        from app.api.auth import SECRET_KEY, ALGORITHM

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        return user_id_str if isinstance(user_id_str, str) else None
    except Exception:
        return None


async def save_turn_to_db(
    token: str,
    thread_id: str,
    user_query: str,
    assistant_reply: str,
) -> None:
    """Persist a user/assistant message pair to PostgreSQL after stream ends."""
    from jose import jwt
    from app.api.auth import SECRET_KEY, ALGORITHM
    from app.db.session import get_session_factory
    from app.db import repository

    factory = get_session_factory()
    if factory is None:
        return

    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        return

    user_id = _uuid.UUID(user_id_str)
    title = user_query[:30] if user_query else "新对话"

    async with factory() as session:
        await repository.get_or_create_thread(session, thread_id, user_id, title)
        await repository.add_message(session, thread_id, "user", user_query)
        if assistant_reply:
            await repository.add_message(session, thread_id, "assistant", assistant_reply)
        await repository.touch_thread(session, thread_id)
        await session.commit()

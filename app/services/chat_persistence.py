import logging
import uuid as _uuid
from typing import Optional

logger = logging.getLogger(__name__)

# ── 历史压缩策略常量 ───────────────────────────────────────────────────────────
# 始终逐字保留最近 N 条消息（user+assistant 各算一条）
_KEEP_RECENT = 6
# 从 DB 最多取多少条历史（再往前的直接丢弃，不值得摘要）
_DB_FETCH_LIMIT = 40


async def _summarize_messages(messages: list[dict]) -> str:
    """调用 LLM 将一段旧对话压缩为简短摘要。失败时返回空字符串。"""
    try:
        from app.llm.wrapper import call_llm

        text_parts = []
        for m in messages:
            role_label = "用户" if m["role"] == "user" else "助手"
            # 每条最多取前 400 字，避免摘要输入本身就爆长
            text_parts.append(f"{role_label}：{m['content'][:400]}")
        dialogue = "\n".join(text_parts)

        prompt = (
            "下面是一段对话历史，请用 200 字以内的简洁中文总结其核心内容、"
            "用户目的以及已达成的结论，供后续对话参考。\n\n"
            f"{dialogue}"
        )
        result = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            role="simple_chat",
        )
        summary = (result.get("content") or "").strip()
        return summary
    except Exception as e:
        logger.warning(f"[HistoryCompressor] 摘要生成失败，跳过: {e}")
        return ""


async def load_thread_history(thread_id: str) -> list[dict]:
    """从数据库加载对话历史并智能压缩，返回 OpenAI 格式消息列表。

    策略：
    - 始终逐字保留最近 _KEEP_RECENT 条消息（保证近期上下文完整）
    - 超出部分调用 LLM 压缩为一条 system 摘要注入到列表最前面
    - 数据库不可用时安全返回空列表
    """
    try:
        from app.db.session import get_session_factory
        from app.db import repository

        factory = get_session_factory()
        if factory is None:
            return []

        async with factory() as session:
            all_db = await repository.get_thread_messages(session, thread_id)

        # 从 DB 只取最近 _DB_FETCH_LIMIT 条（再早的历史价值低）
        if len(all_db) > _DB_FETCH_LIMIT:
            all_db = all_db[-_DB_FETCH_LIMIT:]

        all_msgs = [{"role": m.role, "content": m.content} for m in all_db]

        if len(all_msgs) <= _KEEP_RECENT:
            # 消息不多，直接返回
            return all_msgs

        # 分成「旧消息」和「近期消息」
        older = all_msgs[:-_KEEP_RECENT]
        recent = all_msgs[-_KEEP_RECENT:]

        summary_text = await _summarize_messages(older)
        if summary_text:
            summary_msg = {
                "role": "system",
                "content": f"【早期对话摘要】{summary_text}",
            }
            return [summary_msg] + recent
        else:
            # 摘要失败，退化为只保留近期消息
            return recent

    except Exception as e:
        logger.warning(f"[load_thread_history] 加载失败: {e}")
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

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db import repository
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/threads", tags=["threads"])


# ─── Pydantic schemas ──────────────────────────────────────────────────────────

class ThreadResponse(BaseModel):
    id: str
    title: str
    updated_at: str
    created_at: str


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    meta: dict | None
    created_at: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ThreadResponse])
async def list_threads(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    threads = await repository.list_threads(session, user.id)
    return [
        ThreadResponse(
            id=t.id,
            title=t.title,
            updated_at=t.updated_at.isoformat(),
            created_at=t.created_at.isoformat(),
        )
        for t in threads
    ]


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await repository.delete_thread(session, thread_id, user.id)


@router.get("/{thread_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    thread_id: str,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Ensure the thread belongs to this user
    threads = await repository.list_threads(session, user.id)
    if not any(t.id == thread_id for t in threads):
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = await repository.get_thread_messages(session, thread_id)
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            meta=m.meta,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]

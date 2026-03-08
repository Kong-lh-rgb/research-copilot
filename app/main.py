import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("httpx").setLevel(logging.WARNING)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.api.chat import router as chat_router
from app.api.auth import router as auth_router
from app.api.threads import router as threads_router
from app.infrastructure.setup import tool_registry
from app.graph.build_graph import build_graph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from contextlib import asynccontextmanager
import os

@asynccontextmanager
async def lifespan(app: FastAPI):

    await tool_registry.initialize()

    pg_url = os.environ["DATABASE_URL"]  # e.g. postgresql://user:pass@host:5432/dbname

    # Initialise business-logic DB (users / threads / messages)
    from app.db.session import init_db, create_tables
    init_db(pg_url)
    await create_tables()

    async with AsyncPostgresSaver.from_conn_string(pg_url) as checkpointer:
        await checkpointer.setup()  # 自动创建 checkpoints 表（幂等）
        app.state.compiled_graph = build_graph().compile(checkpointer=checkpointer)
        app.state.checkpointer = checkpointer

        app.state.stream_queues = {}
        yield


    await tool_registry.cleanup()


app = FastAPI(
    title="深度研究 Agent API",
    description="企业级AI投研Agent的API接口，支持流式聊天和执行过程展示",
    version="1.0.0",
    lifespan=lifespan
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(threads_router)
app.include_router(chat_router)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    chat_file = Path(__file__).parent / "static" / "chat.html"
    if chat_file.exists():
        return FileResponse(chat_file)
    return {
        "message": "深度研究 Agent API",
        "ui": "/static/chat.html",
        "docs": "/docs",
        "endpoints": {
            "stream_chat": "POST /chat/stream",
            "health": "GET /chat/health",
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("httpx").setLevel(logging.WARNING)

from typing import Any
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

    # LangSmith observability startup diagnostics
    ls_enabled = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
    ls_api_key = os.getenv("LANGSMITH_API_KEY")
    ls_project = os.getenv("LANGSMITH_PROJECT", "")
    if ls_enabled:
        if ls_api_key and ls_project:
            logging.info("LangSmith tracing enabled (project=%s)", ls_project)
        else:
            logging.warning(
                "LangSmith tracing enabled but API key/project missing; tracing may be ineffective"
            )
    else:
        logging.info("LangSmith tracing disabled")

    pg_url = os.environ["DATABASE_URL"]  # e.g. postgresql://user:pass@host:5432/dbname

    # Initialise business-logic DB (users / threads / messages)
    from app.db.session import init_db, create_tables
    init_db(pg_url)
    db_auto_create_tables = os.getenv("DB_AUTO_CREATE_TABLES", "1") == "1"
    if db_auto_create_tables:
        await create_tables()
        logging.info("DB_AUTO_CREATE_TABLES=1 -> auto create_tables enabled")
    else:
        logging.info("DB_AUTO_CREATE_TABLES=0 -> skip create_tables (use Alembic manually)")

    async with AsyncPostgresSaver.from_conn_string(pg_url) as checkpointer:
        await checkpointer.setup()
        app.state.compiled_graph = build_graph().compile(checkpointer=checkpointer)
        app.state.checkpointer = checkpointer
        app.state.stream_queues = {}
        app.state.hitl_pending = {}
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

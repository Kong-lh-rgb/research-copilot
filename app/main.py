import logging
import sys


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
from app.infrastructure.setup import tool_registry
from app.graph.build_graph import build_graph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 启动所有 MCP 服务（长驻进程）
    await tool_registry.initialize()

    # 2. 预编译 LangGraph（避免每次请求都重新 build + compile）
    async with AsyncSqliteSaver.from_conn_string("memory.db") as checkpointer:
        app.state.compiled_graph = build_graph().compile(checkpointer=checkpointer)
        app.state.checkpointer = checkpointer
        # 3. 初始化流式 token 传递队列（key: thread_id）
        app.state.stream_queues: dict = {}
        yield

    # 4. 清理所有 MCP 服务
    await tool_registry.cleanup()


# 创建 FastAPI 应用
app = FastAPI(
    title="深度研究 Agent API",
    description="企业级AI投研Agent的API接口，支持流式聊天和执行过程展示",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(chat_router)


# 挂载静态文件（chat.html）
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 根路由
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

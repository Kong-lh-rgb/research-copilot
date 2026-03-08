# 后端架构学习指导

## 一、项目整体架构图

```
用户请求 (POST /chat/stream)
        │
        ▼
  FastAPI 应用 (app/main.py)
        │  lifespan 启动时：初始化 MCP 工具 + 编译 LangGraph
        │
        ▼
  chat.py (app/api/chat.py)
  StreamingResponse + asyncio.Queue
        │
        ├─── asyncio.create_task(_run_graph())  ← 异步跑图，事件入队
        │
        └─── async for _drain():               ← 消费队列，立即 yield SSE
                        │
                        ▼
              LangGraph 状态机 (app/graph/)
              controller → planner → worker(s) → reviewer
                                  → simple_chat
```

---

## 二、必读文件清单（按理解顺序）

| 优先级 | 文件 | 核心内容 |
|:---:|---|---|
| ★★★ | `app/main.py` | 应用入口、lifespan 生命周期、图的编译 |
| ★★★ | `app/api/chat.py` | 流式接口实现，SSE 格式封装，Queue 机制 |
| ★★★ | `app/graph/build_graph.py` | LangGraph 状态机拓扑，节点路由逻辑 |
| ★★☆ | `app/graph/state.py` | 全局状态结构 `AgentState`，Reducer 函数 |
| ★★☆ | `app/graph/nodes/simple_chat.py` | 流式 token 推入 Queue 的典型实现 |
| ★★☆ | `app/graph/nodes/controller.py` | 意图分类，决定走简单对话还是复杂调研 |
| ★☆☆ | `app/graph/nodes/worker.py` | 工具调用（MCP）循环，任务执行 |
| ★☆☆ | `app/graph/nodes/planner.py` | 任务拆解，生成 TaskNode 列表 |
| ★☆☆ | `app/graph/nodes/reviewer.py` | 汇总所有 worker 结果，生成最终报告 |
| ★☆☆ | `app/llm/wrapper.py` | `call_llm` / `call_llm_stream` 封装 |
| ★☆☆ | `app/llm/client.py` | `AsyncOpenAI` 客户端，普通调用 + 流式调用 |
| ★☆☆ | `app/infrastructure/setup.py` | MCP 工具注册表，服务进程管理 |

---

## 三、后端如何启动

### 1. lifespan 生命周期（`app/main.py`）

FastAPI 使用 `@asynccontextmanager` 定义 `lifespan`，在应用启动/关闭时执行初始化和清理：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ① 启动所有 MCP 服务进程（工具调用的长驻子进程）
    await tool_registry.initialize()

    # ② 预编译 LangGraph（只编译一次，复用 SQLite checkpointer）
    async with AsyncSqliteSaver.from_conn_string("memory.db") as checkpointer:
        app.state.compiled_graph = build_graph().compile(checkpointer=checkpointer)

        # ③ 初始化流式队列字典（key: thread_id → asyncio.Queue）
        app.state.stream_queues = {}
        yield   # ← 应用正常运行

    # ④ 关闭时清理 MCP 子进程
    await tool_registry.cleanup()
```

**关键点：**
- `compiled_graph` 挂在 `app.state` 上，每次请求复用，避免重复编译开销
- `stream_queues` 是线程安全的字典，key 是 `thread_id`，value 是 `asyncio.Queue`
- MCP 工具以子进程形式运行（stdio 通信），应用关闭时统一回收

### 2. 实际启动命令

```bash
# 开发模式（推荐，支持热重载）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 或直接运行模块
python -m app.main
```

---

## 四、流式输出实现原理

这是本项目最核心的设计，涉及三个层次：

### 层次 1：HTTP 层 — SSE（Server-Sent Events）

所有流式响应使用标准 SSE 格式（`text/event-stream`）：

```
data: {"type":"start","query":"...","thread_id":"..."}\n\n
data: {"type":"log","message":"🤔 解析用户意图...","level":"info"}\n\n
data: {"type":"content_token","delta":"你好"}\n\n
data: {"type":"final","reply":"完整回复..."}\n\n
data: {"type":"end"}\n\n
```

FastAPI 侧实现（`app/api/chat.py`）：

```python
@router.post("/stream")
async def chat_stream(request: Request, body: ChatRequest):
    async def generate():
        async for message in _stream_chat_response(...):
            yield f"data: {message}\n\n"   # ← SSE 格式包装

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

### 层次 2：应用层 — asyncio.Queue 解耦图执行与 SSE 输出

核心设计：**LangGraph 图的执行** 和 **SSE 数据推送** 是两个并发的 async 任务，通过 `asyncio.Queue` 解耦：

```
┌─────────────────────────┐        asyncio.Queue        ┌──────────────────────┐
│     _run_graph()         │  ──── put_nowait(event) ──▶ │      _drain()         │
│  LangGraph.astream(...)  │                             │  get() → yield SSE   │
│  节点执行 → 更新状态      │                             │  有数据立即推送       │
└─────────────────────────┘                             └──────────────────────┘
```

```python
async def _stream_chat_response(...):
    queue = asyncio.Queue()
    request.app.state.stream_queues[thread_id] = queue

    graph_done = asyncio.Event()

    async def _run_graph():
        # 遍历 LangGraph 每个步骤，把事件写入 queue
        async for step in compiled_graph.astream(turn_state, config={...}):
            for node_name, node_output in step.items():
                queue.put_nowait({"type": "log", "message": "..."})
                # ... 不同节点 → 不同类型事件
        graph_done.set()   # ← 图执行完毕

    async def _drain():
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                if graph_done.is_set() and queue.empty():
                    break   # ← 图完成且队列清空，结束
                continue
            yield json.dumps(item)

    graph_task = asyncio.create_task(_run_graph())  # ← 并发执行图
    async for raw_json in _drain():
        yield raw_json   # ← 边执行边推送
    await graph_task
```

### 层次 3：LLM 层 — 流式 token 逐字推送

在 `simple_chat` 节点（和 `reviewer` 节点），LLM 的 token 逐个推入 Queue，实现打字机效果：

```python
# app/graph/nodes/simple_chat.py
async def simple_chat_node(state: AgentState, config: RunnableConfig) -> dict:
    queue = config.get("configurable", {}).get("stream_queue")  # ← 从 config 获取队列

    async for chunk in call_llm_stream(messages=messages, system=system):
        if chunk.get("done"):
            break
        c = chunk.get("content", "")
        if c:
            full_content += c
            if queue:
                queue.put_nowait({"type": "content_token", "delta": c})  # ← 逐 token 入队
```

LLM 客户端 (`app/llm/client.py`) 使用 `AsyncOpenAI` 的 stream 模式：

```python
async def chat_stream(self, messages, ...):
    stream = await self._client.chat.completions.create(
        ..., stream=True
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", "") or ""
        thinking = getattr(delta, "reasoning_content", "") or ""
        yield {"thinking": thinking, "content": content, "done": False}
    yield {"thinking": "", "content": "", "done": True}
```

---

## 五、LangGraph 状态机详解

### 节点拓扑

```
START
  │
  ▼
controller  ──► (next_action == "simple_chat")  ──► simple_chat ──► END
  │
  └──► (next_action == "complex_research") ──► planner
                                                  │
                                          distribute_tasks()
                                                  │
                                      ┌───────────┴──────────┐
                                      ▼           ▼          ▼
                                   worker      worker     worker   (并行)
                                      └───────────┬──────────┘
                                          distribute_tasks()
                                                  │
                                               reviewer ──► END
```

### distribute_tasks 调度器（`build_graph.py`）

这是并行 worker 的调度核心：

```python
def distribute_tasks(state):
    # 1. 检查是否有任务失败 → 立即返回 END
    # 2. 检查所有任务是否完成 → 进入 reviewer
    # 3. 找出依赖已完成、自身 pending 的任务 → Send("worker", {...}) 并行启动
    # 4. 还有 running 的任务但没有新任务 → 返回 [] 等待
```

`Send("worker", {...})` 是 LangGraph 的 **并行分发** 机制，每个 `Send` 对象启动一个独立的 worker 实例，互不阻塞。

### AgentState Reducer（`state.py`）

并行 worker 写回状态时需要合并，通过 `Annotated` + 自定义 Reducer 处理：

```python
class AgentState(TypedDict, total=False):
    tasks:        Annotated[Dict[str, TaskNode], merge_dicts]   # worker 并发写入，按 key 合并
    tool_history: Annotated[List[ToolCall], concat_lists]       # 追加，不覆盖
    current_task_id: Annotated[str, take_last]                  # 取最新值
```

---

## 六、事件类型速查表

| event type | 来源 | 描述 |
|---|---|---|
| `start` | chat.py | 请求开始 |
| `log` | chat.py / 各节点 | 执行日志（level: info/success/warning） |
| `task_start` | planner 节点输出 | 新任务创建 |
| `task_running` | worker 节点输出 | 任务开始执行 |
| `task_complete` | worker 节点输出 | 任务完成 |
| `task_failed` | worker 节点输出 | 任务失败 |
| `tool_call` | worker 节点输出 | 工具被调用（含参数） |
| `tool_result` | worker 节点输出 | 工具返回值（截断200字） |
| `thinking_token` | reviewer 节点 | LLM 思考过程 token（可选展示） |
| `content_token` | simple_chat/reviewer | LLM 正文 token（打字机效果） |
| `final` | chat.py | 完整最终回复（兜底） |
| `error` | chat.py | 错误信息 |
| `end` | chat.py | 流结束标志 |

---

## 七、MCP 工具调用流程

```
worker_node
    │
    ├─ call_llm(tools=openai_tools)       ← 非流式，带工具描述
    │        │
    │        └─ 模型返回 tool_calls
    │
    ├─ tool_registry.call_tool(name, args) ← 通过 stdio 调用 MCP 子进程
    │        │
    │        └─ 返回工具结果
    │
    ├─ 将工具结果追加到 messages，继续调用 LLM
    │
    └─ 循环直到 LLM 不再调用工具（最多 MAX_TOOL_ROUNDS=10 轮）
```

MCP 工具配置在 `mcp_servers.json`，由 `app/infrastructure/setup.py` 的 `MCPRegistry` 管理。

---

## 八、学习路径建议

1. **先跑起来**：`uvicorn app.main:app --reload`，访问 `/docs` 看 API 文档
2. **理解入口**：读 `app/main.py`，搞清 lifespan 做了什么
3. **理解流式**：读 `app/api/chat.py`，重点是 `_stream_chat_response` 的 Queue 机制
4. **理解状态机**：读 `app/graph/build_graph.py`，画出节点流转图
5. **理解状态**：读 `app/graph/state.py`，理解每个 Reducer 的作用
6. **理解节点**：按 controller → planner → worker → reviewer 顺序读各节点
7. **理解 LLM**：读 `app/llm/wrapper.py` 和 `app/llm/client.py`，了解流式 token 产生源头

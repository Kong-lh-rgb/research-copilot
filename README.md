# Deep Researcher

基于 **LangGraph 多智能体框架**的 AI 深度研究系统。用户以自然语言提出研究需求，系统自动将其拆解为并行子任务，调用多个外部工具完成数据采集与分析，最终生成结构化 Markdown 研报，全程实时流式推送到前端。

**技术栈**：Python 3.12 · FastAPI · LangGraph · MCP · Next.js 15 · PostgreSQL

---

## 功能介绍

### 智能任务规划与并行执行

- 输入一句话，Planner 节点自动生成带依赖关系的任务 DAG
- 使用 LangGraph `Send` API 将无依赖任务并行分发给多个 Worker，有依赖的任务在前置完成后自动解锁
- 任务执行全程可见：前端实时展示每个子任务的状态

### 多工具调用

每个 Worker 内置多轮工具调用循环，支持自定义：

| 工具 | 能力 |
|---|---|
| **finance-mcp**（本地） | A 股实时行情、K 线、利润表 / 资产负债表 / 现金流量表（Tushare Pro） |
| **amap-maps** | 高德地图 POI 搜索、路线规划 |
| **brave-search** | 网页搜索 |
| **send_email** | 将研报渲染为 HTML 邮件发送 |

工具通过 [MCP 协议](https://modelcontextprotocol.io)接入，新增工具只需在 `mcp_servers.json` 增加一条配置。

### Human-in-the-Loop（HITL）

发送邮件等**不可逆操作**执行前，系统暂停并向前端推送确认弹窗，用户点击"确认 / 取消"后继续或中止，超时 120 秒自动取消。

### 流式输出

全程 Server-Sent Events 推流，支持：
- 逐 token 打字机效果
- 模型思考链（`reasoning_content`）实时展示
- 工具调用参数与返回摘要可展开查看

### 多轮对话记忆

- LangGraph PostgreSQL checkpointer 持久化每轮图状态
- 支持跨轮次信息补充：第一轮忘提邮箱，第二轮补充后自动续跑，不丢失上一轮的分析结果

### 用户体系

- JWT 注册 / 登录，bcrypt 密码哈希
- 历史会话列表与消息记录查询
- LangSmith 链路追踪（可选）

## 快速开始

### 方式一：Docker Compose（推荐）

**前置要求**：安装 Docker Desktop

```bash
# 1. 复制配置文件
cp .env.example .env
cp mcp_servers.example.json mcp_servers.json

# 2. 编辑 .env（至少填写下方"必填配置"中的项）
#    注意：DATABASE_URL 的 host 必须写 postgres（服务名），不能写 localhost
#    DATABASE_URL=postgresql://postgres:yourpassword@postgres:5432/deep_researcher

# 3. 构建并启动
docker compose up -d

# 4. 查看后端日志
docker compose logs -f backend
```

访问 `http://localhost:3000`

停止服务：

```bash
docker compose down
```

---

### 方式二：本地开发

**前置要求**：Python 3.12+、Node.js 20+、PostgreSQL、[uv](https://github.com/astral-sh/uv)

```bash
# 1. 复制配置
cp .env.example .env
cp mcp_servers.example.json mcp_servers.json
# 编辑 .env，DATABASE_URL 写 localhost

# 2. 启动后端
uv sync --dev
uv run python -m app.main
# → http://localhost:8000

# 3. 启动前端（新终端）
cd static
npm ci
npm run dev
# → http://localhost:3000
```

---

## 配置说明

### `.env` 环境变量

**必填**

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | PostgreSQL 连接串|
| `OPENAI_API_KEY` | LLM API 密钥 |
| `OPENAI_BASE_URL` | 自定义端点，如 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `OPENAI_MODEL` | 默认模型名，如 `qwen-plus` |

**角色级模型（可选）**

可为每个 Agent 节点单独指定模型，留空则回退到 `OPENAI_MODEL`：

| 变量 | 对应节点 |
|---|---|
| `MODEL_CONTROLLER` | 意图路由 |
| `MODEL_PLANNER` | 任务规划 |
| `MODEL_WORKER` | 工具执行（建议用推理能力更强的模型） |
| `MODEL_REVIEWER` | 结果汇总 |
| `MODEL_SIMPLE_CHAT` | 普通对话 |

**其他可选项**

| 变量 | 说明 |
|---|---|
| `DB_AUTO_CREATE_TABLES` | `1`（默认）启动自动建表；`0` 仅用 Alembic |
| `SENDER_EMAIL` / `SENDER_PASSWORD` | 163 邮箱发送（需在邮箱设置中开启 SMTP 授权码） |
| `TUSHARE_TOKEN` | Tushare Pro 财务数据接口 |
| `AMAP_MAPS_API_KEY` | 高德地图 MCP |
| `BRAVE_API_KEY` | Brave Search MCP |
| `LANGSMITH_TRACING` | `true` 开启 LangSmith 链路追踪 |
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | LangSmith 配置 |

---

### `mcp_servers.json` 工具配置

从示例文件复制后按需修改：

```bash
cp mcp_servers.example.json mcp_servers.json
```

所有 `${VAR}` 占位符会自动从 `.env` 读取，**不需要**在 json 里写真实密钥。

新增工具示例（Node 包）：

```json
"my-tool": {
  "type": "node",
  "package": "@scope/my-mcp-server",
  "env": {
    "API_KEY": "${MY_API_KEY}"
  }
}
```

新增工具示例（Python 脚本）：

```json
"my-tool": {
  "type": "python",
  "script_or_package": "path/to/server.py"
}
```

---

## 测试

```bash
# 单元测试
uv run pytest

# 含集成测试（需真实配置）
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration
```

前端检查：

```bash
cd static
npm run lint && npm run typecheck && npm run build
```

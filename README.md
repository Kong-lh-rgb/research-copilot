# Deep Researcher

企业级多步骤研究助手（FastAPI + LangGraph + Next.js）。

- 后端：`app/`（API、图编排、工具集成、数据库）
- 前端：`static/`（Next.js 聊天界面）
- 数据库：PostgreSQL（用户、会话、消息持久化）

## 功能概览

- 流式聊天（SSE）
- 任务分解 / 执行 / 汇总
- 用户注册登录（JWT）
- 会话与消息持久化（`users` / `threads` / `messages`）

## 项目结构

```text
app/
  api/           # auth, chat, threads
  db/            # SQLAlchemy models/session/repository
  graph/         # LangGraph 节点与状态
  infrastructure/# MCP/tool 注册与客户端
  llm/           # 模型客户端封装
static/
  app/           # Next.js app router
  components/    # UI 组件
  hooks/         # chat/auth hooks
tests/           # pytest 单测 + 可选集成测试
alembic/         # DB migration
```

## 环境准备

- Python 3.12+
- Node.js 20+
- PostgreSQL 14+
- `uv`（Python 依赖管理）

复制环境变量：

```bash
cp .env.example .env
```

必填项至少包含：

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `JWT_SECRET_KEY`（生产环境必须自定义）

可选项：

- `DB_AUTO_CREATE_TABLES=1`（默认）启动时自动建表，适合单人快速迭代
- `DB_AUTO_CREATE_TABLES=0` 关闭自动建表，仅使用 Alembic 管理结构

## 本地启动

### 1) 后端

```bash
uv sync --dev
uv run python -m app.main
```

后端地址：`http://localhost:8000`

### 2) 前端

```bash
cd static
npm ci
npm run dev
```

前端地址：`http://localhost:3000`

## 数据库迁移（Alembic）

初始化迁移已包含：`20260309_0001_create_users_threads_messages`

执行升级：

```bash
alembic upgrade head
```

创建新迁移：

```bash
alembic revision -m "your message"
```

> 默认从 `DATABASE_URL` 读取连接串。

## 测试

运行单元测试（默认）：

```bash
uv run pytest
```

运行外部依赖的集成测试（需真实配置）：

```bash
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration
```

## 代码质量

前端：

```bash
cd static
npm run lint
npm run typecheck
npm run build
```

## CI

已配置 GitHub Actions：

- 后端：`uv sync --dev` + `pytest`
- 前端：`npm ci` + `lint` + `typecheck` + `build`

见：`.github/workflows/ci.yml`

## 已知建议

- 生产环境建议将 CORS 改为白名单
- 建议补充 API 集成测试（auth/threads/chat 端到端链路）
- 建议加入日志追踪 ID 与指标监控

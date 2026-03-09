# 数据库建立说明（PostgreSQL）

本文说明当前项目如何建立数据库、表结构关系、启动时的自动建表流程，以及如何验证是否成功。

## 1. 使用的技术栈

- 数据库：PostgreSQL
- ORM：SQLAlchemy 2.x（异步）
- 驱动：asyncpg
- 会话管理：`AsyncSession` + `async_sessionmaker`

项目中数据库相关核心文件：
- `app/db/models.py`
- `app/db/session.py`
- `app/main.py`

---

## 2. 表结构设计

在 `app/db/models.py` 中定义了 3 张业务表：

## 2.1 users（用户表）

- 主键：`id`（UUID）
- 字段：
  - `username`：唯一用户名（`unique=True`）
  - `password_hash`：密码哈希
  - `created_at`：创建时间（数据库默认 `now()`）

用途：存储登录账户。

## 2.2 threads（会话表）

- 主键：`id`（字符串，如 `web_xxx`）
- 外键：`user_id -> users.id`（`ondelete=CASCADE`）
- 字段：
  - `title`：会话标题
  - `created_at` / `updated_at`：时间戳

用途：区分每次新对话，会话归属到用户。

## 2.3 messages（聊天记录表）

- 主键：`id`（自增整数）
- 外键：`thread_id -> threads.id`（`ondelete=CASCADE`）
- 字段：
  - `role`：`user` / `assistant`
  - `content`：消息正文
  - `meta`：JSON 扩展字段（思考链、工具调用、任务信息等）
  - `created_at`：创建时间

用途：保存每条聊天消息。

---

## 3. 关系与级联删除

关系如下：

- 一个 `User` 对应多个 `Thread`
- 一个 `Thread` 对应多条 `Message`

并且两级都启用了级联删除：

- 删除用户 -> 自动删除该用户所有会话与消息
- 删除会话 -> 自动删除该会话所有消息

这样可以避免孤儿数据。

---

## 4. 启动时如何自动建表

在 `app/main.py` 的 `lifespan` 中：

1. 读取环境变量 `DATABASE_URL`
2. 调用 `init_db(pg_url)` 初始化 SQLAlchemy 异步引擎
3. 调用 `create_tables()` 执行 `Base.metadata.create_all`

`create_all` 是幂等的：
- 表不存在 -> 创建
- 表已存在 -> 跳过

所以服务每次启动都会确保基础表存在。

---

## 5. 连接串处理规则

`app/db/session.py` 中做了协议转换：

- `postgresql://...` -> `postgresql+asyncpg://...`
- `postgres://...` -> `postgresql+asyncpg://...`

也就是说你在环境变量里用常见 PostgreSQL URL 即可，代码会自动适配异步驱动格式。

---

## 6. FastAPI 中的事务与提交

`get_session()` 依赖逻辑：

- 请求进入时创建 session
- 正常结束：自动 `commit`
- 抛异常：自动 `rollback`

优点：
- 路由代码更干净
- 事务边界统一
- 出错不污染数据

---

## 7. 数据写入时机（聊天）

在流式聊天接口 `app/api/chat.py`：

- 流式输出完成后，若请求带 `Bearer Token`
- 会解析用户身份
- 将本轮 user/assistant 消息写入 `messages`
- 必要时自动创建 `threads` 并刷新 `updated_at`

这样登录用户就能在下次进入时从后端恢复历史会话。

---

## 8. 环境变量示例

```bash
export DATABASE_URL="postgresql://postgres:password@127.0.0.1:5432/deep_researcher"
export JWT_SECRET_KEY="your-secret-key"
```

然后启动后端：

```bash
uv run python -m app.main
```

---

## 9. 如何验证建表成功

可在 PostgreSQL 执行：

```sql
\dt
```

应至少看到：
- `users`
- `threads`
- `messages`

再测试接口：
1. `POST /auth/register` 创建账号
2. 登录后发送一条聊天
3. `GET /threads` 查看会话
4. `GET /threads/{thread_id}/messages` 查看消息

---

## 10. 常见注意点

1. **这是自动建表，不是迁移系统**  
   如果后续改字段，建议引入 Alembic 做版本迁移。

2. **生产环境需强密码策略**  
   当前最小长度校验为 6，建议按业务提高。

3. **`JWT_SECRET_KEY` 必须在生产环境替换**  
   不要使用默认值。

4. **连接池参数可按并发调整**  
   当前 `pool_size=5, max_overflow=10`，高并发可加大。

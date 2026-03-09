FROM python:3.12-slim

WORKDIR /app

# 安装 uv（比 pip 快很多）
RUN pip install uv

# 先只复制依赖文件，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 复制项目代码
COPY app/ ./app/

# Node.js（MCP amap/brave 工具需要 npx）
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
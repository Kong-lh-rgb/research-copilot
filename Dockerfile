FROM python:3.12-slim

WORKDIR /app

# 1. Debian 系统镜像源
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || true \
    && sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list || true

# 2. Python 包镜像源
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/

# 🚨【关键修复 1】：限制同时下载的数量为 2 个（默认是几十个），防止触发服务器并发防火墙
ENV UV_CONCURRENT_DOWNLOADS=2
# 🚨【关键修复 2】：把默认超时时间延长到 300 秒，允许大文件（如 curl-cffi）慢慢下
ENV UV_HTTP_TIMEOUT=300

RUN pip install uv -i https://mirrors.aliyun.com/pypi/simple/

COPY pyproject.toml uv.lock ./

# 🚨【关键修复 3】：加上 -v 参数，让它打印详细下载日志，不再“静默卡死”
RUN uv sync  --no-dev -v

COPY app/ ./app/

RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
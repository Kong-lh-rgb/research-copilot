FROM python:3.12-slim

WORKDIR /app

# 【加速优化 1】把 Debian 系统软件源换成阿里云源（解决 apt-get 卡住）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || true \
    && sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list || true

# 【加速优化 2】设置 uv 和 pip 的国内镜像源（解决 Python 包卡住）
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/
RUN pip install uv -i https://mirrors.aliyun.com/pypi/simple/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app/ ./app/

RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
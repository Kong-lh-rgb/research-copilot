FROM node:20-alpine AS builder

WORKDIR /app

# 【加速优化 3】设置 npm 淘宝镜像源（解决前端 npm ci 卡死）
RUN npm config set registry https://registry.npmmirror.com/

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# 运行阶段：只保留构建产物
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
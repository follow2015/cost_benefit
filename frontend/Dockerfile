# 前端镜像：先构建静态资源，再用 nginx 托管 · Node 26.7 基线，不可降级
FROM node:26-alpine AS builder
WORKDIR /app
# 构建期 API 基址（静态包的 import.meta.env 只能在 build 时注入；
# v1 默认 8000，v2 编排通过 build.args 传 8001）
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

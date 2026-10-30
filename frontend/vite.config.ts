/**
 * Vite 配置（P0 前端构建）。
 * - React 插件 + TS；
 * - 为 `decimal.js` 等 ESM 依赖预打包（optimizeDeps）；
 * - 开发代理把 `/api` 转发到后端。
 *
 * 注意：Vite 的 .env 变量（VITE_*）只会注入到 import.meta.env，
 * 不会进入 Node 的 process.env。因此本文件用 loadEnv 从 .env/.env.local
 * 显式读取 VITE_API_PROXY / FRONTEND_PORT，避免配置项读不到而静默回退到默认值。
 */
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/** 项目根目录。Vite 8 起推荐 import.meta.dirname（原生配置加载器不支持 __dirname）。 */
const projectRoot = import.meta.dirname ?? process.cwd();

export default defineConfig(({ mode }) => {
  // 空前缀 '' 表示加载 .env/.env.local 中的全部键（含非 VITE_ 的 FRONTEND_PORT）
  const env = loadEnv(mode, process.cwd(), '');
  const apiProxy = env.VITE_API_PROXY ?? 'http://localhost:8000';
  const frontendPort = Number(env.FRONTEND_PORT ?? 5173) || 5173;

  // 监听地址。不设时 Vite 用 'localhost'，Node 在 Windows 上会解析成 **仅 IPv6 回环 [::1]**，
  // 于是 127.0.0.1:5173 连不上——nginx 反代 127.0.0.1 就会 502。
  // 要经 nginx 反代时设为 '::'（双栈，IPv4/IPv6 都收）或 '127.0.0.1'。
  const frontendHost = (env.FRONTEND_HOST ?? '').trim();

  // Vite 会校验 Host 头，默认只放行 localhost/127.0.0.1。经 nginx 反代、或用局域网 IP /
  // 域名访问 dev server 时会被拦成 "Blocked request. This host is not allowed"。
  // 显式配置才放开——默认留空，保持 Vite 原有的防护（防止 DNS rebinding）。
  // 取值：'*' 全放开；或逗号分隔白名单如 'roi.example.com,.example.com'
  const rawHosts = (env.VITE_ALLOWED_HOSTS ?? '').trim();
  const allowedHosts: true | string[] | undefined =
    rawHosts === '*'
      ? true
      : rawHosts
        ? rawHosts.split(',').map((h) => h.trim()).filter(Boolean)
        : undefined;

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(projectRoot, 'src'),
      },
    },
    server: {
      port: frontendPort,
      // undefined 时不写该键，沿用 Vite 默认（localhost）
      ...(frontendHost ? { host: frontendHost } : {}),
      // undefined 时不写该键，Vite 沿用默认 Host 校验
      ...(allowedHosts === undefined ? {} : { allowedHosts }),
      proxy: {
        '/api': {
          target: apiProxy,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      // 相对 base：H5 挂到 CDN 任意子路径（含小程序 web-view 业务域名）都能正确加载资源
      base: './',
      sourcemap: false,
      chunkSizeWarningLimit: 1500,
    },
    worker: {
      format: 'es',
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
      globals: false,
      // 蒙特卡洛确定性回归（p2.test.ts）与 GV08 长周期黄金向量单条实耗 13–21s，
      // 远超 Vitest 默认 5000ms。此处给重计算回归足够预算，避免升级后误判为失败。
      testTimeout: 120_000,
    },
  };
});

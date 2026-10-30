import { defineConfig, devices } from '@playwright/test';
import fs from 'node:fs';

/**
 * Playwright 配置（Phase 4b e2e 冒烟）。
 * - baseURL / webServer 端口统一从 FRONTEND_PORT 读取（与 .env 同源，默认 5173），
 *   避免此前 baseURL 写死 5174 而 vite dev 实际监听 5173、导致 webServer 等待超时；
 * - 浏览器不再硬编码 /usr/bin/chromium：按平台探测，可用 PW_CHROMIUM 覆盖；
 * - reuseExistingServer: true 兼容本地已起服务或 CI 自动拉起。
 */
const PORT = Number(process.env.FRONTEND_PORT ?? 5173) || 5173;
// 用 127.0.0.1 而不是 localhost：dev server 按 .env.local 的 FRONTEND_HOST=127.0.0.1
// 只绑 IPv4 回环，而 Windows 上 localhost 常先解析成 [::1] —— 那样 webServer 的
// 就绪探测会一直连不上，表现为「等 60s 超时」而不是任何有用的报错。
const BASE_URL = process.env.PW_BASE_URL ?? `http://127.0.0.1:${PORT}`;

/** 按优先级探测本机浏览器；都不存在时返回 undefined，交给 Playwright 默认解析。 */
function detectExecutablePath(): string | undefined {
  if (process.env.PW_CHROMIUM) return process.env.PW_CHROMIUM;
  const candidates = [
    // Linux（CI / WSL）
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
    // Windows
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    // macOS
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ];
  return candidates.find((p) => {
    try {
      return fs.existsSync(p);
    } catch {
      return false;
    }
  });
}

const executablePath = detectExecutablePath();

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    headless: true,
    actionTimeout: 15_000,
    launchOptions: {
      ...(executablePath ? { executablePath } : {}),
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    },
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: `${BASE_URL}/login`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});

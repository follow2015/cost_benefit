/**
 * e2e 公共支撑。
 *
 * 分工原则：
 * - **UI 只验证用户真正走的路径**（点按钮、填表单、看提示）；
 * - **造数据与清理走后端 API**（比 UI 快且稳定，避免测试之间互相污染）。
 *
 * 后端起不来时，任何用例都会在登录阶段失败——这是有意的：本套 e2e 对的是
 * 真实前后端联调，不做 mock。
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test';

/**
 * e2e 登录凭据。
 *
 * 允许用 E2E_EMAIL / E2E_PASSWORD 覆盖：演示账号的密码不再硬编码在 seed 脚本里，
 * 重置后（`python -m scripts.seed --reset-password`）跑测试要能跟着换，
 * 否则每次轮换密码都得改代码。
 */
export const EMAIL = process.env.E2E_EMAIL ?? 'demo@airoi.dev';
export const PASSWORD = process.env.E2E_PASSWORD ?? 'demo123456';

/** 后端基地址，与前端 `VITE_API_BASE` 同源（默认 http://localhost:8000）。 */
export const API_BASE = `${(process.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '')}/api/v1`;

/** AntD 会给两字按钮插空格（「登 录」「确 定」），统一用忽略空白的正则匹配。 */
export function buttonPattern(label: string): RegExp {
  // 先去掉标签自带的空格（如「导出 PDF」），再逐字插入 \s*，兼容任意渲染间距
  return new RegExp(label.replace(/\s+/g, '').split('').join('\\s*'));
}

export async function clickButton(page: Page, label: string): Promise<void> {
  await page.getByRole('button', { name: buttonPattern(label) }).first().click();
}

/** 通过 UI 登录。authStore 落 sessionStorage，同 page 内后续 goto 保持登录态。 */
export async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByPlaceholder('邮箱').fill(EMAIL);
  await page.getByPlaceholder('密码').fill(PASSWORD);
  await clickButton(page, '登录');
  await expect(page).toHaveURL(/\/$/);
}

// --------------------------------------------------------------------------- API
interface ApiEnvelope<T> {
  code: string;
  message?: string;
  data?: T;
}

async function unwrap<T>(resp: Awaited<ReturnType<APIRequestContext['get']>>, label: string): Promise<T> {
  const text = await resp.text();
  if (!resp.ok()) {
    throw new Error(`${label} -> HTTP ${resp.status()} ${text.slice(0, 300)}`);
  }
  const body = JSON.parse(text) as ApiEnvelope<T>;
  if (body.code !== 'OK') {
    throw new Error(`${label} -> ${body.code} ${body.message ?? ''}`);
  }
  return body.data as T;
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

/** 登录并取 access token（用于造数据/清理，不经 UI）。 */
export async function apiLogin(request: APIRequestContext): Promise<string> {
  const data = await unwrap<{ access_token: string }>(
    await request.post(`${API_BASE}/auth/login`, { data: { email: EMAIL, password: PASSWORD } }),
    'POST /auth/login',
  );
  return data.access_token;
}

export async function apiGet<T>(request: APIRequestContext, token: string, path: string): Promise<T> {
  return unwrap<T>(await request.get(`${API_BASE}${path}`, { headers: authHeaders(token) }), `GET ${path}`);
}

export async function apiPost<T>(
  request: APIRequestContext,
  token: string,
  path: string,
  data?: unknown,
): Promise<T> {
  return unwrap<T>(
    await request.post(`${API_BASE}${path}`, { headers: authHeaders(token), data }),
    `POST ${path}`,
  );
}

export async function apiPut<T>(
  request: APIRequestContext,
  token: string,
  path: string,
  data?: unknown,
): Promise<T> {
  return unwrap<T>(
    await request.put(`${API_BASE}${path}`, { headers: authHeaders(token), data }),
    `PUT ${path}`,
  );
}

export async function apiDelete<T>(
  request: APIRequestContext,
  token: string,
  path: string,
): Promise<T> {
  return unwrap<T>(await request.delete(`${API_BASE}${path}`, { headers: authHeaders(token) }), `DELETE ${path}`);
}

// --------------------------------------------------------------------------- 方案
export interface ScenarioDetailLike {
  id: number;
  name: string;
  version: number;
  params: Record<string, Record<string, unknown>>;
}

/** 造一个方案（用默认参数），返回 id。 */
export async function createScenario(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<number> {
  const params = await apiGet<Record<string, unknown>>(request, token, '/scenarios/default-params');
  const detail = await apiPost<ScenarioDetailLike>(request, token, '/scenarios', { name, params });
  return detail.id;
}

/**
 * 改一个参数让版本自增到 v2 并生成带 diff 的快照。
 * 这正是 `PUT /scenarios/{id}` 的唯一有副作用分支（也是 MissingGreenlet 缺陷的触发点）。
 */
export async function bumpScenarioVersion(
  request: APIRequestContext,
  token: string,
  scenarioId: number,
): Promise<Record<string, unknown>> {
  const detail = await apiGet<ScenarioDetailLike>(request, token, `/scenarios/${scenarioId}`);
  const params = JSON.parse(JSON.stringify(detail.params)) as Record<string, Record<string, unknown>>;
  const current = Number(params.hw?.N_gpu ?? 8);
  const next = current === 16 ? 24 : 16;
  params.hw = { ...(params.hw ?? {}), N_gpu: String(next) };
  const updated = await apiPut<ScenarioDetailLike>(request, token, `/scenarios/${scenarioId}`, {
    params,
    note: `e2e 变更 N_gpu ${current} → ${next}`,
  });
  expect(updated.version).toBe(2);
  return params.hw;
}

export async function deleteScenario(
  request: APIRequestContext,
  token: string,
  scenarioId: number,
): Promise<void> {
  await apiDelete(request, token, `/scenarios/${scenarioId}`);
}

// --------------------------------------------------------------------------- 基准库
export interface BenchBundleLike {
  gpus: Array<Record<string, unknown>>;
  models: Array<Record<string, unknown>>;
  cloud_prices: Array<Record<string, unknown>>;
  api_prices: Array<Record<string, unknown>>;
}

export async function getBenchBundle(
  request: APIRequestContext,
  token: string,
): Promise<BenchBundleLike> {
  return apiGet<BenchBundleLike>(request, token, '/benchmarks');
}

/** 按代号找基准行（找不到返回 undefined）。 */
export async function findGpuByCode(
  request: APIRequestContext,
  token: string,
  code: string,
): Promise<Record<string, unknown> | undefined> {
  const bundle = await getBenchBundle(request, token);
  return bundle.gpus.find((row) => row.code === code);
}

/** 按代号删除基准（清理用；已不存在时静默忽略）。 */
export async function deleteGpuByCode(
  request: APIRequestContext,
  token: string,
  code: string,
): Promise<void> {
  const row = await findGpuByCode(request, token, code);
  if (!row) return;
  await apiDelete(request, token, `/benchmarks/gpus/${row.id}`).catch(() => undefined);
}

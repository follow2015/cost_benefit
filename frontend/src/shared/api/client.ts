/**
 * Axios 客户端：统一基地址、JWT 注入、租户标识、统一响应解包与错误归一。
 * - 请求拦截：注入 `Authorization: Bearer <token>` 与 `X-Tenant-Id`（来自 auth store）；
 * - 响应拦截：解包 `{code,message,data}`，非 2xx 或 `code !== 'OK'` 抛 `ApiError`；
 * - 401 → 尝试 refresh，失败则清理登录态并跳转登录页。
 */
import axios, { type AxiosInstance, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios';
import type { ApiResponse } from '@/shared/types';

const BASE_URL = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  code: string;
  detail?: unknown;
  constructor(message: string, status = 0, code = 'ERR', detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
}

/** 从外部（store / sessionStorage）读取鉴权上下文。避免在模块间形成硬引用环。 */
interface AuthContext {
  getAccessToken: () => string | null;
  getRefreshToken: () => string | null;
  getTenantId: () => number | null;
  setTokens: (t: AuthTokens) => void;
  clear: () => void;
  onUnauthorized: () => void;
}

let authCtx: AuthContext | null = null;

export function registerAuthContext(ctx: AuthContext): void {
  authCtx = ctx;
}

const client: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (authCtx) {
    const token = authCtx.getAccessToken();
    if (token) config.headers.set('Authorization', `Bearer ${token}`);
    const tenantId = authCtx.getTenantId();
    if (tenantId != null) config.headers.set('X-Tenant-Id', String(tenantId));
  }
  return config;
});

let refreshing: Promise<boolean> | null = null;

client.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiResponse<unknown>;
    // 文件流等非 JSON 结构直接放行
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 'OK') {
        throw new ApiError(body.message || '请求失败', resp.status, body.code, (body as { data?: unknown }).data);
      }
      resp.data = body.data as never;
    }
    return resp;
  },
  async (error) => {
    const status = error?.response?.status ?? 0;
    const body = error?.response?.data as ApiResponse<unknown> | undefined;
    if (status === 401 && authCtx && !error.config?.__retried) {
      const refreshToken = authCtx.getRefreshToken();
      if (refreshToken) {
        try {
          if (!refreshing) {
            refreshing = (async () => {
              const r = await axios.post(`${BASE_URL}/api/v1/auth/refresh`, { refresh_token: refreshToken });
              const data = (r.data as ApiResponse<{ access_token: string; refresh_token: string }>).data;
              if (data) authCtx.setTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
              return Boolean(data);
            })();
          }
          const ok = await refreshing;
          refreshing = null;
          if (ok && error.config) {
            error.config.__retried = true;
            const token = authCtx.getAccessToken();
            if (token) error.config.headers.set('Authorization', `Bearer ${token}`);
            return client.request(error.config);
          }
        } catch {
          refreshing = null;
        }
      }
      authCtx.clear();
      authCtx.onUnauthorized();
    }
    const message = body?.message || error.message || '网络错误';
    throw new ApiError(message, status, body?.code || 'ERR', body?.data);
  },
);

/** 请求并解包 data。 */
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const resp = await client.request<T>(config);
  return resp.data as T;
}

export function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request<T>({ method: 'GET', url, params });
}

export function post<T>(url: string, data?: unknown): Promise<T> {
  return request<T>({ method: 'POST', url, data });
}

export function put<T>(url: string, data?: unknown): Promise<T> {
  return request<T>({ method: 'PUT', url, data });
}

export function del<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request<T>({ method: 'DELETE', url, params });
}

export { BASE_URL };
export default client;

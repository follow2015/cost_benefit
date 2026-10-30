/** 鉴权相关 API（含成员管理 CRUD）。 */
import { get, post, put, del, type AuthTokens } from '@/shared/api/client';
import type { LoginRequest, MemberCreateIn, MemberUpdateIn, TokenResponse, UserOut } from '@/shared/types';

export function login(payload: LoginRequest): Promise<TokenResponse> {
  return post<TokenResponse>('/auth/login', payload);
}

export function refresh(refreshToken: string): Promise<TokenResponse> {
  return post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken });
}

export function me(): Promise<UserOut> {
  return get<UserOut>('/auth/me');
}

export function members(): Promise<UserOut[]> {
  return get<UserOut[]>('/auth/members');
}

export function createMember(payload: MemberCreateIn): Promise<UserOut> {
  return post<UserOut>('/auth/members', payload);
}

export function updateMember(id: number, payload: MemberUpdateIn): Promise<UserOut> {
  return put<UserOut>(`/auth/members/${id}`, payload);
}

export function deleteMember(id: number): Promise<{ ok: boolean }> {
  return del<{ ok: boolean }>(`/auth/members/${id}`);
}

export type { AuthTokens };

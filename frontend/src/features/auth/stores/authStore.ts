/**
 * 鉴权状态（Zustand）。持久化 token 到 sessionStorage，并对外暴露给 api/client 的拦截器。
 */
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { TokenResponse, UserOut } from '@/shared/types';

export interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: UserOut | null;
  setTokens: (t: { access_token: string; refresh_token: string }) => void;
  setUser: (u: UserOut) => void;
  clear: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setTokens: (t: { access_token: string; refresh_token: string }) =>
        set({ accessToken: t.access_token, refreshToken: t.refresh_token }),
      setUser: (u: UserOut) => set({ user: u }),
      clear: () => set({ accessToken: null, refreshToken: null, user: null }),
      isAuthenticated: () => Boolean(get().accessToken),
    }),
    {
      name: 'airoi-auth',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({ accessToken: s.accessToken, refreshToken: s.refreshToken, user: s.user }),
    },
  ),
);

/** 供 api/client 注册使用的鉴权上下文。 */
export function authContext() {
  const getState = useAuthStore.getState;
  return {
    getAccessToken: () => getState().accessToken,
    getRefreshToken: () => getState().refreshToken,
    getTenantId: () => getState().user?.tenant?.id ?? null,
    setTokens: (t: { access_token: string; refresh_token: string }) => getState().setTokens(t),
    clear: () => getState().clear(),
    onUnauthorized: () => {
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.assign('/login');
      }
    },
  };
}

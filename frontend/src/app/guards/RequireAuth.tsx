/** 鉴权守卫：未登录跳转 /login。 */
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/features/auth/stores/authStore';

export function RequireAuth({ children }: { children: React.ReactNode }): React.ReactElement {
  const token = useAuthStore((s) => s.accessToken);
  const location = useLocation();
  if (!token) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <>{children}</>;
}

import React from 'react';
import ReactDOM from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { Providers } from './providers';
import { ErrorBoundary } from './errorBoundary';
import { registerAuthContext } from '@/shared/api/client';
import { authContext } from '@/features/auth/stores/authStore';
import './styles/index.css';

registerAuthContext(authContext());

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <Providers>
        <RouterProvider router={router} />
      </Providers>
    </ErrorBoundary>
  </React.StrictMode>,
);

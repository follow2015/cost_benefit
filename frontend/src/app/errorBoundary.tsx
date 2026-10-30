/** 全局错误边界：捕获渲染异常并兜底展示。 */
import React from 'react';

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { hasError: false, message: '' };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, info);
  }

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 32, maxWidth: 720, margin: '0 auto' }}>
          <h2>页面出错了</h2>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#cf1322' }}>{this.state.message}</pre>
          <button onClick={() => window.location.reload()}>刷新重试</button>
        </div>
      );
    }
    return this.props.children;
  }
}

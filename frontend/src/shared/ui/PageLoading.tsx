/** 路由懒加载占位：切页时展示居中加载态，避免异步 chunk 拉取期间白屏。 */
import React from 'react';
import { Spin, Typography } from 'antd';

export function PageLoading(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        minHeight: 240,
      }}
    >
      <Spin size="large" />
      <Typography.Text type="secondary">加载中…</Typography.Text>
    </div>
  );
}

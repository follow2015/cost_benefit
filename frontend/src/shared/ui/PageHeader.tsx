/** 页面级标题区（标题 + 描述 + 操作区），统一页面节奏。 */
import React from 'react';
import { Space, Typography } from 'antd';

interface Props {
  title: React.ReactNode;
  description?: React.ReactNode;
  extra?: React.ReactNode;
}

export function PageHeader({ title, description, extra }: Props): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 16,
        flexWrap: 'wrap',
        marginBottom: 16,
      }}
    >
      <div>
        <Typography.Title level={4} style={{ margin: 0, fontWeight: 600 }}>
          {title}
        </Typography.Title>
        {description ? (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {description}
          </Typography.Text>
        ) : null}
      </div>
      {extra ? <Space>{extra}</Space> : null}
    </div>
  );
}

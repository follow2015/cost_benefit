/** 登录页。调用 /auth/login，写入 token 并跳转工作台。 */
import React from 'react';
import { Card, Form, Input, Button, Typography, Alert, Tag } from 'antd';
import { LockOutlined, MailOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/features/auth/stores/authStore';
import { login as loginApi } from '@/features/auth/api/authApi';
import type { LoginRequest } from '@/shared/types';

/**
 * 是否展示演示账号提示。**默认关闭，且提示里不再写密码**。
 *
 * 之前这一栏把「demo@airoi.dev / demo123456」明文印在登录页上，还把邮箱密码
 * 预填进输入框——等于给每个能打开页面的人发了一份 owner 权限的凭据。
 * 构建产物是静态文件，谁拿到 dist 谁就读得到，改后端也拦不住。
 *
 * 本地演示需要提示时，在 `frontend/.env.local` 里设 `VITE_DEMO_HINT=true`；
 * 密码本身请从 `python -m scripts.seed` 的输出里取（或 `--reset-password` 重置）。
 */
const SHOW_DEMO_HINT = import.meta.env.VITE_DEMO_HINT === 'true';

export default function LoginPage(): React.ReactElement {
  const [form] = Form.useForm<LoginRequest>();
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);
  const navigate = useNavigate();
  const location = useLocation();

  const onFinish = async (values: LoginRequest) => {
    setLoading(true);
    setError(null);
    try {
      const res = await loginApi(values);
      setTokens({ access_token: res.access_token, refresh_token: res.refresh_token });
      setUser(res.user);
      const from = (location.state as { from?: string } | null)?.from ?? '/';
      navigate(from, { replace: true });
    } catch (e) {
      setError((e as Error).message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f7fa' }}>
      <Card style={{ width: 380 }} title={<Typography.Title level={4} style={{ margin: 0 }}>AI 算力投资 ROI 测算平台</Typography.Title>}>
        <div style={{ marginBottom: 16 }}>
          <Tag color="blue">CNY 本位币</Tag>
          <Tag color="default">税前口径</Tag>
          <Tag color="green">PG16 多租户</Tag>
        </div>
        {error && <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} />}
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item name="email" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
            <Input prefix={<MailOutlined />} placeholder="邮箱" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
          {SHOW_DEMO_HINT ? (
            <>
              演示账号见后端 <Typography.Text code>python -m scripts.seed</Typography.Text>{' '}
              的输出（重置密码加 <Typography.Text code>--reset-password</Typography.Text>）。
            </>
          ) : null}
          本平台测算结果不构成投资承诺。
        </Typography.Paragraph>
      </Card>
    </div>
  );
}

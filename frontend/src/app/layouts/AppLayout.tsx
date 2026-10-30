/** 应用骨架：深蓝渐变侧边导航 + 白色顶栏 + 内容区（ui-ux-pro-max · Trust & Authority）。 */
import React from 'react';
import { Layout as AntLayout, Menu, Avatar, Tag, Button, Tooltip, Space } from 'antd';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  DashboardOutlined,
  PlusSquareOutlined,
  BookOutlined,
  LogoutOutlined,
  DatabaseOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ImportOutlined,
  RobotOutlined,
  ClusterOutlined,
  ApartmentOutlined,
  ExperimentOutlined,
  ThunderboltFilled,
} from '@ant-design/icons';
import { useAuthStore } from '@/features/auth/stores/authStore';
import { FormulaDrawer } from '@/shared/ui/FormulaDrawer';
import { useFormulaDrawerState } from '@/shared/ui/useFormulaDrawerState';
import { DESIGN_TOKENS as T } from '@/shared/theme';

const { Header, Sider, Content } = AntLayout;

type MenuItem = {
  key: string;
  icon?: React.ReactNode;
  label: string;
};

export function AppLayout(): React.ReactElement {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);
  const { open: drawerOpen, openDrawer, closeDrawer } = useFormulaDrawerState();

  const isAdmin = Boolean(user?.permissions?.includes('benchmark:write') || user?.is_super);
  const pathname = location.pathname;

  const selectedKey = pathname.startsWith('/benchmarks')
    ? 'benchmarks'
    : pathname.startsWith('/network-bom')
      ? 'network-bom'
      : pathname.startsWith('/network-catalog')
      ? 'network-catalog'
      : pathname.startsWith('/tenant')
        ? 'tenant'
        : pathname.startsWith('/throughput')
          ? 'throughput'
          : pathname.startsWith('/builder')
            ? 'builder'
            : pathname.startsWith('/recommend')
              ? 'recommend'
              : pathname.startsWith('/import')
                ? 'import'
                : pathname.startsWith('/scenarios/new') || pathname.includes('/edit')
                  ? 'new'
                  : 'workbench';

  const nav = (key: string) => {
    if (key === 'new') navigate('/scenarios/new');
    else if (key === 'benchmarks') navigate('/benchmarks');
    else if (key === 'network-catalog') navigate('/network-catalog');
    else if (key === 'network-bom') navigate('/network-bom');
    else if (key === 'tenant') navigate('/tenant');
    else if (key === 'throughput') navigate('/throughput');
    else if (key === 'builder') navigate('/builder');
    else if (key === 'recommend') navigate('/recommend');
    else if (key === 'import') navigate('/import');
    else navigate('/');
  };

  const group = (label: string, children: MenuItem[]) => ({ type: 'group' as const, label, children });

  const menuItems = [
    group('核心', [
      { key: 'workbench', icon: <DashboardOutlined />, label: '工作台' },
      { key: 'new', icon: <PlusSquareOutlined />, label: '新建测算方案' },
      { key: 'builder', icon: <ExperimentOutlined />, label: '方案构建向导' },
    ]),
    group('工具', [
      { key: 'throughput', icon: <ThunderboltOutlined />, label: '吞吐计算器' },
      { key: 'recommend', icon: <RobotOutlined />, label: '硬件反选推荐' },
      { key: 'import', icon: <ImportOutlined />, label: '批量导入参数' },
    ]),
    ...(isAdmin
      ? [
          group('管理', [
            { key: 'benchmarks', icon: <DatabaseOutlined />, label: '基准库' },
            { key: 'network-bom', icon: <ApartmentOutlined />, label: '组网配套估算' },
            { key: 'network-catalog', icon: <ClusterOutlined />, label: '组网配套目录' },
            { key: 'tenant', icon: <TeamOutlined />, label: '租户权限' },
          ]),
        ]
      : []),
  ];

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider
        width={T.layout.siderWidth}
        breakpoint="lg"
        collapsedWidth={64}
        style={{
          background: `linear-gradient(180deg, ${T.colors.siderBg} 0%, ${T.colors.siderBg2} 120%)`,
          boxShadow: '2px 0 12px rgba(15, 29, 64, 0.18)',
          position: 'sticky',
          top: 0,
          height: '100vh',
          overflow: 'auto',
        }}
      >
        {/* 品牌区 */}
        <div
          style={{
            height: T.layout.headerHeight,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            color: '#fff',
            fontWeight: 700,
            fontSize: 16,
            letterSpacing: 0.5,
          }}
        >
          <ThunderboltFilled style={{ color: T.colors.secondary, fontSize: 20 }} />
          <span>AI 算力 ROI</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems as never[]}
          onClick={({ key }) => nav(key)}
          style={{ background: 'transparent', borderInlineEnd: 'none', paddingBottom: 24 }}
        />
      </Sider>
      <AntLayout>
        <Header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 28px',
            background: T.colors.surface,
            borderBottom: `1px solid ${T.colors.border}`,
            position: 'sticky',
            top: 0,
            zIndex: 20,
          }}
        >
          <Space size={12}>
            <span style={{ fontSize: 15, fontWeight: 600, color: T.colors.fg }}>AI 算力投资 ROI 测算平台</span>
            <Tag color="blue" style={{ marginInlineEnd: 0 }}>CNY · 税前</Tag>
            <Tooltip title="公式速查（ⓘ 口径溯源）">
              <Button type="text" icon={<BookOutlined />} onClick={() => openDrawer()}>
                公式
              </Button>
            </Tooltip>
          </Space>
          <Space size={12}>
            <Avatar style={{ backgroundColor: T.colors.primary }}>{user?.display_name?.[0] ?? user?.email?.[0]?.toUpperCase() ?? 'U'}</Avatar>
            <span style={{ color: T.colors.fgSecondary }}>{user?.display_name || user?.email}</span>
            <Tooltip title="退出登录">
              <Button type="text" icon={<LogoutOutlined />} onClick={() => { clear(); navigate('/login'); }} />
            </Tooltip>
          </Space>
        </Header>
        <Content style={{ padding: '24px 28px', overflow: 'auto', background: T.colors.bg }}>
          <div style={{ maxWidth: T.layout.contentMaxWidth, margin: '0 auto' }}>
            <Outlet />
          </div>
        </Content>
      </AntLayout>
      <FormulaDrawer open={drawerOpen} onClose={closeDrawer} />
    </AntLayout>
  );
}

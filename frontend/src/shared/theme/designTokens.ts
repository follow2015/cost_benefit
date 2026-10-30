/**
 * 设计令牌（ui-ux-pro-max · Trust & Authority 风格，适配 AI 算力 ROI 企业级平台）。
 *
 * - 风格：信任权威（金融/企业软件）——深蓝主色 + 琥珀强调 + 浅灰蓝背景；
 * - 字体：IBM Plex Sans（金融信任感），中文回退 PingFang SC / Microsoft YaHei；
 * - 涨跌语义：按中国惯例 涨红（#CF1322）/ 跌绿（#389E0D），用于财务 KPI 与图表；
 * - 间距 4/8 节奏；圆角 6/10/14/20；卡片轻阴影 + hover 抬升。
 */

export const DESIGN_TOKENS = {
  colors: {
    // 品牌主色系（金融蓝）
    primary: '#1E40AF', // 主色（品牌/主按钮）
    primaryHover: '#1D4ED8', // 主色 hover
    primaryActive: '#1E3A8A', // 主色按下
    secondary: '#3B82F6', // 次级/链接强调
    accent: '#D97706', // 强调/CTA（琥珀，WCAG 3:1 校准）
    // 中性面
    bg: '#F8FAFC', // 页面背景（浅灰蓝）
    surface: '#FFFFFF', // 卡片/容器
    surfaceAlt: '#F1F5F9', // 次级面（表头/斑马）
    fg: '#0F172A', // 主文本（近黑）
    fgSecondary: '#475569', // 次级文本
    fgMuted: '#94A3B8', // 弱化文本
    muted: '#E9EEF6', // 弱化面
    border: '#DBEAFE', // 分隔线
    // 语义
    destructive: '#DC2626',
    ring: '#1E40AF',
    up: '#CF1322', // 涨/盈（中国惯例红）
    down: '#389E0D', // 跌/亏（中国惯例绿）
    warning: '#D97706',
    // Sider（深蓝渐变）
    siderBg: '#0F1D40',
    siderBg2: '#1E3A8A',
    siderText: 'rgba(255,255,255,0.75)',
    siderTextActive: '#FFFFFF',
    siderItemActive: 'rgba(59,130,246,0.22)',
  },
  typography: {
    fontFamily: "'IBM Plex Sans', 'PingFang SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    fontMono: "'IBM Plex Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', monospace",
    weights: { regular: 400, medium: 500, semibold: 600, bold: 700 },
  },
  spacing: {
    xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48,
  },
  radius: {
    sm: 6, md: 10, lg: 14, xl: 20,
  },
  shadow: {
    card: '0 1px 2px rgba(15, 29, 64, 0.05), 0 4px 12px rgba(15, 29, 64, 0.05)',
    cardHover: '0 4px 16px rgba(30, 64, 175, 0.14)',
    popup: '0 8px 24px rgba(15, 29, 64, 0.16)',
  },
  motion: {
    fast: '120ms', base: '200ms', slow: '300ms',
  },
  layout: {
    siderWidth: 232,
    headerHeight: 56,
    contentMaxWidth: 1440,
  },
} as const;

export type DesignToken = typeof DESIGN_TOKENS;

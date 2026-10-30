/** AntD 主题令牌（由 designTokens 驱动 · ui-ux-pro-max Trust & Authority）。 */
import type { ThemeConfig } from 'antd';
import { DESIGN_TOKENS as T } from './designTokens';

const base: ThemeConfig = {
  token: {
    colorPrimary: T.colors.primary,
    colorInfo: T.colors.primary,
    colorLink: T.colors.secondary,
    colorSuccess: T.colors.down,
    colorWarning: T.colors.warning,
    colorError: T.colors.destructive,
    colorBgLayout: T.colors.bg,
    colorBgContainer: T.colors.surface,
    colorBgElevated: T.colors.surface,
    colorBorder: T.colors.border,
    colorBorderSecondary: '#E2E8F0',
    colorText: T.colors.fg,
    colorTextSecondary: T.colors.fgSecondary,
    colorTextTertiary: T.colors.fgMuted,
    colorSplit: '#E2E8F0',
    borderRadius: T.radius.md,
    borderRadiusSM: T.radius.sm,
    borderRadiusLG: T.radius.lg,
    fontSize: 14,
    fontFamily: T.typography.fontFamily,
    controlHeight: 36,
    boxShadowSecondary: T.shadow.popup,
  },
  components: {
    Layout: {
      headerBg: T.colors.surface,
      headerHeight: T.layout.headerHeight,
      siderBg: T.colors.siderBg,
      triggerBg: T.colors.siderBg2,
    },
    Menu: {
      itemBg: 'transparent',
      itemColor: T.colors.siderText,
      itemSelectedBg: T.colors.siderItemActive,
      itemSelectedColor: T.colors.siderTextActive,
      itemHoverBg: 'rgba(59,130,246,0.14)',
      itemHoverColor: T.colors.siderTextActive,
      itemHeight: 42,
      itemMarginInline: 8,
      itemBorderRadius: T.radius.md,
      subMenuItemBg: 'transparent',
      groupTitleColor: 'rgba(255,255,255,0.45)',
    },
    Card: {
      borderRadiusLG: T.radius.lg,
      headerFontSize: 15,
      headerHeight: 52,
      paddingLG: 20,
    },
    Table: {
      headerBg: T.colors.surfaceAlt,
      headerColor: T.colors.fgSecondary,
      rowHoverBg: '#F0F6FF',
      borderColor: '#E2E8F0',
      headerSplitColor: 'transparent',
      cellPaddingBlock: 12,
    },
    Button: {
      fontWeight: 500,
      primaryShadow: '0 2px 6px rgba(30, 64, 175, 0.28)',
    },
    Tag: {
      borderRadiusSM: T.radius.sm,
    },
    Modal: {
      borderRadiusLG: T.radius.lg,
    },
    Tabs: {
      inkBarColor: T.colors.primary,
      itemSelectedColor: T.colors.primary,
      titleFontSize: 14,
    },
    Statistic: {
      titleFontSize: 13,
      contentFontSize: 26,
    },
    Input: {
      activeBorderColor: T.colors.primary,
      hoverBorderColor: T.colors.secondary,
    },
    Select: {
      optionSelectedBg: '#E8F0FE',
    },
  },
};

export const lightTheme: ThemeConfig = base;

export const darkTheme: ThemeConfig = {
  ...base,
  algorithm: undefined,
  token: {
    ...base.token,
    colorBgLayout: '#141414',
  },
};

/**
 * 版本快照与审计（P1 REQ-16）端到端：时间线 + 参数 diff 抽屉 + 审计日志抽屉。
 *
 * 造数据走后端 API：建方案得 v1，再改一个参数得 v2 与带 diff 的快照。
 * 这条链路同时覆盖了 `PUT /scenarios/{id}`——它曾因 `updated_at` 惰性加载在
 * 异步会话下抛 MissingGreenlet 而恒 500（见 backend/tests/test_pg_integration.py
 * 的 TestScenarioUpdateWritePath）。
 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import {
  apiLogin,
  bumpScenarioVersion,
  buttonPattern,
  createScenario,
  deleteScenario,
  login,
} from './support';

test.describe('版本与审计', () => {
  let token = '';
  let scenarioId = 0;
  let scenarioName = '';

  test.beforeEach(async ({ request, page }) => {
    token = await apiLogin(request);
    scenarioName = `e2e-版本-${Date.now()}`;
    scenarioId = await createScenario(request, token, scenarioName);
    await bumpScenarioVersion(request, token, scenarioId);
    await login(page);
    await page.goto(`/scenarios/${scenarioId}/versions`);
  });

  test.afterEach(async ({ request }) => {
    if (scenarioId) await deleteScenario(request, token, scenarioId).catch(() => undefined);
  });

  test('时间线呈现 v1/v2，参数变更抽屉给出字段级前后值', async ({ page }) => {
    await expect(page.getByText(`版本与审计 · ${scenarioName}`)).toBeVisible();

    const timeline = page.locator('.ant-timeline');
    await expect(timeline.getByText('v2', { exact: true })).toBeVisible();
    await expect(timeline.getByText('v1', { exact: true })).toBeVisible();
    // 改参数时写了备注，应原样展示
    await expect(timeline.getByText(/e2e 变更 N_gpu/)).toBeVisible();

    // 新→旧排序，首个「查看参数变更」即 v2
    await timeline.getByRole('button', { name: buttonPattern('查看参数变更') }).first().click();
    const drawer = page.locator('.ant-drawer').filter({ hasText: '参数变更' });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText(/参数变更 · v2/)).toBeVisible();

    // diff 表：参数路径 + 原值 + 新值
    const diffRow = drawer.getByRole('row').filter({ hasText: 'hw.N_gpu' });
    await expect(diffRow).toBeVisible();
    const cells = await diffRow.locator('td').allInnerTexts();
    expect(cells.map((c) => c.trim())).toEqual(['hw.N_gpu', '8', '16']);

    // 关闭按钮必须限定在本抽屉内：审计日志抽屉也在 DOM 中（只是未展开），
    // 用全局 .ant-drawer-close 的 last() 会点到另一个抽屉上。
    await drawer.locator('.ant-drawer-close').click();
    // antd 关闭后仍保留 .ant-drawer 根节点（只是摘掉 ant-drawer-open、卸载内容），
    // 根节点始终占满视口，故不能断言 toBeHidden——改为断言「打开态类移除 + 内容清空」。
    await expect(drawer).not.toHaveClass(/ant-drawer-open/);
    await expect(drawer.getByText('参数路径')).toHaveCount(0);
  });

  test('审计日志抽屉能查到本方案的创建与更新记录', async ({ page }) => {
    await page.getByRole('button', { name: buttonPattern('审计日志') }).click();
    const drawer = page.locator('.ant-drawer').filter({ hasText: '审计日志' });
    await expect(drawer).toBeVisible();

    // 造数据阶段产生两条：创建方案 + 更新方案
    const rows = drawer.getByRole('row');
    await expect(rows.filter({ hasText: '创建方案' })).toHaveCount(1);
    await expect(rows.filter({ hasText: '更新方案' })).toHaveCount(1);
    // 操作人与对象落库正确
    await expect(rows.filter({ hasText: 'demo@airoi.dev' }).first()).toBeVisible();
    await expect(rows.filter({ hasText: `scenario:${scenarioId}` })).toHaveCount(2);
  });
});

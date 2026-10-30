import { test, expect } from '@playwright/test';
import { apiLogin, clickButton, deleteScenario, login } from './support';

/**
 * 核心测算链路冒烟：登录 → 新建向导 → 保存并计算 → 结果页渲染 KPI。
 * 对接真实后端（VITE_API_BASE 直连，默认 http://localhost:8000；需后端 CORS 放行 5173）：向导以默认参数提交，验证端到端可用。
 */
test.describe('测算链路', () => {
  let token = '';
  let createdId = 0;

  test.beforeEach(async ({ page, request }) => {
    token = await apiLogin(request);
    await login(page);
  });

  // 走 UI 建的方案也走 API 清理，避免长期跑 e2e 把租户库塞满
  test.afterEach(async ({ request }) => {
    if (createdId) await deleteScenario(request, token, createdId).catch(() => undefined);
  });

  test('向导默认参数保存并计算 → 结果页渲染财务指标', async ({ page }) => {
    await page.getByText('新建测算方案').first().click();
    await expect(page).toHaveURL(/\/scenarios\/new$/);
    // 填写方案名称（其余以默认参数提交）
    await page.getByPlaceholder('例如：H100×8 自建 vs 租赁对比').fill('e2e-冒烟方案');
    await clickButton(page, '保存并计算');
    // 跳转到结果页 /scenarios/{id}
    await expect(page).toHaveURL(/\/scenarios\/\d+/);
    createdId = Number(page.url().match(/\/scenarios\/(\d+)/)?.[1] ?? 0);
    // 结果页 KPI 卡片渲染（财务指标语境）
    await expect(page.getByText('杠杆后 NPV').or(page.getByText('净现值')).first()).toBeVisible();
    // 敏感性图表区存在
    await expect(page.getByText('敏感性龙卷风').first()).toBeVisible();
  });
});

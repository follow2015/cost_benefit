/**
 * 图表渲染护栏。
 *
 * 背景：8 张结果页图表原先都从 `echarts-for-react` 默认入口引入，会把 echarts 全量
 * （所有图表类型 + 组件 + 双渲染器）打进 chunk。改为 `@/shared/ui/EChart` 按需注册后，
 * 包体从 1.04 MB 降到 590 KB——**代价是漏注册组件时 echarts 不再报错，而是静默画不出来**。
 *
 * 所以这里不看 DOM 结构，直接验「像素」：每个可见 canvas 必须真的画上了东西，
 * 且控制台不得出现 echarts 的 "used but not imported" 告警。
 */
import { test, expect } from '@playwright/test';
import { apiLogin, clickButton, deleteScenario, login } from './support';

/** 统计 canvas 的非透明像素（按行采样，避免大画布逐像素遍历）。 */
async function paintedPixels(
  canvas: import('@playwright/test').Locator,
): Promise<number> {
  return canvas.evaluate((el: HTMLCanvasElement) => {
    const ctx = el.getContext('2d');
    if (!ctx || el.width === 0 || el.height === 0) return -1;
    const { data } = ctx.getImageData(0, 0, el.width, el.height);
    let painted = 0;
    for (let y = 0; y < el.height; y += 4) {
      for (let x = 0; x < el.width; x += 2) {
        if (data[(y * el.width + x) * 4 + 3] > 0) painted += 1;
      }
    }
    return painted;
  });
}

test.describe('图表渲染', () => {
  let token = '';
  let createdId = 0;

  test.beforeEach(async ({ request }) => {
    token = await apiLogin(request);
  });

  // 走 UI 建的方案同样走 API 清理，避免长期跑 e2e 把租户库塞满
  test.afterEach(async ({ request }) => {
    if (createdId) await deleteScenario(request, token, createdId).catch(() => undefined);
  });

  test('结果页图表真实绘出像素，且无 echarts 未注册告警', async ({ page }) => {
    const echartsWarnings: string[] = [];
    const pageErrors: string[] = [];
    page.on('console', (msg) => {
      // 未注册能力时 echarts 输出：
      //   [ECharts] Component markLine is used but not imported.
      //   [ECharts] Series line is used but not imported.
      if (/\[ECharts\]/i.test(msg.text())) echartsWarnings.push(msg.text());
    });
    page.on('pageerror', (err) => pageErrors.push(String(err)));

    // 走与用户一致的 UI 路径：向导默认参数 → 保存并计算 → 结果页
    await login(page);
    await page.getByText('新建测算方案').first().click();
    await expect(page).toHaveURL(/\/scenarios\/new$/);
    await page.getByPlaceholder('例如：H100×8 自建 vs 租赁对比').fill('e2e-图表护栏');
    await clickButton(page, '保存并计算');
    await expect(page).toHaveURL(/\/scenarios\/\d+/);
    createdId = Number(page.url().match(/\/scenarios\/(\d+)/)?.[1] ?? 0);

    await expect(page.getByText('敏感性龙卷风').first()).toBeVisible();
    const canvases = page.locator('canvas');
    await expect.poll(async () => canvases.count(), { timeout: 30_000 }).toBeGreaterThan(3);

    const total = await canvases.count();
    let checked = 0;
    for (let i = 0; i < total; i += 1) {
      const canvas = canvases.nth(i);
      if (!(await canvas.isVisible())) continue;
      const painted = await paintedPixels(canvas);
      expect(painted, `第 ${i + 1} 个 canvas 是空白（对应 echarts 组件可能未注册）`).toBeGreaterThan(0);
      checked += 1;
    }
    expect(checked, '没有可校验的可见图表').toBeGreaterThan(3);

    expect(echartsWarnings, `出现 echarts 未注册告警：\n${echartsWarnings.join('\n')}`).toEqual([]);
    expect(pageErrors, `页面抛出异常：\n${pageErrors.join('\n')}`).toEqual([]);
  });
});

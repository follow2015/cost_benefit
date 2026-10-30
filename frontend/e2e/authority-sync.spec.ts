/** 权威同步：三源比对抽屉的端到端验证。
 *
 * 重点断言「冲突不默认采信」这条业务底线——这是本功能存在的核心原因：
 * 权威源之间会成倍分歧（实测 deepseek-v4-pro $1.32 vs $0.66），
 * 若默认勾选就会把错值静默写进基准库。
 */
import { expect, test } from '@playwright/test';
import { login } from './support';

test.describe('基准库 · 权威同步', () => {
  // 首次预览需下载三源约 9MB（后端有 10 分钟 TTL 缓存，第二次起秒开）
  test.setTimeout(180_000);

  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/benchmarks');
  });

  test('拉取三源并展示比对结果与汇率偏离', async ({ page }) => {
    await page.getByTestId('authority-sync-button').click();
    // antd 6 的 Drawer 以 role=dialog 呈现，类名不再是 .ant-drawer-content
    const drawer = page.getByRole('dialog').filter({ hasText: '多源比对' });
    await expect(drawer.getByText('权威同步 · 多源比对')).toBeVisible();

    // 三源下载 + 比对约需数秒
    // 三源下载约需数秒；以抽屉内的统计项出现为就绪信号（「已比对」是 toast，不在抽屉里）
    await expect(drawer.getByText('多源一致', { exact: true }).first()).toBeVisible({ timeout: 120_000 });

    // 分维度投票后的统计口径：待决策 / 仅汇率口径 / 三档判决
    for (const label of ['待决策', '仅汇率口径', '多源一致', '单源', '冲突 / 无覆盖']) {
      await expect(drawer.getByText(label, { exact: true }).first()).toBeVisible();
    }

    // 汇率偏离提示（库内折算口径 vs 权威值）
    await expect(drawer.getByText(/库内/).first()).toBeVisible();
    // 表格里必须出现判决标签
    await expect(drawer.locator('.ant-tag').filter({ hasText: '多源一致' }).first()).toBeVisible();

    // 「仅汇率」必须与真实调价区分开：19 条里常有十几条只是把 6.76/7.2 折算值
    // 统一到权威汇率，混在 +12% 里会让人误以为大面积涨价
    await expect(drawer.locator('.ant-tag').filter({ hasText: '仅汇率' }).first()).toBeVisible();
  });

  test('冲突项不给勾选框，必须人工选源', async ({ page }) => {
    await page.getByTestId('authority-sync-button').click();
    // antd 6 的 Drawer 以 role=dialog 呈现，类名不再是 .ant-drawer-content
    const drawer = page.getByRole('dialog').filter({ hasText: '多源比对' });
    await expect(drawer.getByText('多源一致', { exact: true }).first()).toBeVisible({ timeout: 120_000 });

    // 找到标着「源间冲突」的行
    const conflictRow = drawer.locator('tr', { has: page.locator('.ant-tag', { hasText: '源间冲突' }) }).first();
    const hasConflict = await conflictRow.count();
    if (hasConflict === 0) test.skip(true, '当前数据无冲突项，跳过');

    // 该行不应有 checkbox——冲突项必须显式选源，不能一个勾就应用
    await expect(conflictRow.locator('input[type="checkbox"]')).toHaveCount(0);
    // 应出现「选择采信源」下拉
    await expect(conflictRow.locator('.ant-select')).toBeVisible();
  });

  test('分维度判决：输出价分歧不该把输入价的明确结论一起废掉', async ({ page }) => {
    await page.getByTestId('authority-sync-button').click();
    const drawer = page.getByRole('dialog').filter({ hasText: '多源比对' });
    await expect(drawer.getByText('多源一致', { exact: true }).first()).toBeVisible({ timeout: 120_000 });

    // deepseek-v3.2 这类：三源输入价同为 $0.28，只有输出价 0.40 / 0.42 不同。
    // 旧实现把 (输入,输出) 捆成一组投票，整条判冲突，连一致的输入价一起作废。
    const partialRow = drawer
      .locator('tr', { has: page.getByText('输出价分歧', { exact: true }) })
      .first();
    if ((await partialRow.count()) === 0) test.skip(true, '当前数据无分维度部分采信项，跳过');

    // 该行整条仍是冲突（不能自动应用），但必须在界面上说清是哪一项有分歧
    await expect(partialRow.locator('.ant-tag', { hasText: '源间冲突' })).toBeVisible();
    // 冲突项永远不给勾选框
    await expect(partialRow.locator('input[type="checkbox"]')).toHaveCount(0);
  });

  test('应用按钮只统计已勾选条目', async ({ page }) => {
    await page.getByTestId('authority-sync-button').click();
    // antd 6 的 Drawer 以 role=dialog 呈现，类名不再是 .ant-drawer-content
    const drawer = page.getByRole('dialog').filter({ hasText: '多源比对' });
    await expect(drawer.getByText('多源一致', { exact: true }).first()).toBeVisible({ timeout: 120_000 });

    const applyBtn = drawer.getByRole('button', { name: /应用 \d+ 条/ });
    await expect(applyBtn).toBeVisible();

    // 初始数量 = 多源一致条数
    const text = (await applyBtn.textContent()) ?? '';
    const initial = Number(text.match(/应用 (\d+) 条/)?.[1] ?? '0');
    expect(initial).toBeGreaterThan(0);

    // 取消一个勾选，计数应减一
    const boxes = drawer.locator('tbody input[type="checkbox"]:checked');
    if ((await boxes.count()) > 0) {
      await boxes.first().click();
      await expect(drawer.getByRole('button', { name: new RegExp(`应用 ${initial - 1} 条`) })).toBeVisible();
    }
  });
});

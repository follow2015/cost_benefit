/**
 * 参数导入页护栏。
 *
 * 该页原先把 `xlsx`（约 380 KB）静态打进首屏 chunk，但只有「上传 Excel」这一个分支用到。
 * 改成 `await import('xlsx')` 后首屏降到 58 KB——代价是解析器变成异步、多一次网络往返，
 * 因此这里必须真的走一次上传，确认惰性 chunk 能加载、能解析、能出结果。
 */
import { test, expect } from '@playwright/test';
import { API_BASE, apiLogin, login } from './support';

test.describe('参数导入', () => {
  test('上传 xlsx 模板可被解析（惰性加载的 xlsx 解析器可用）', async ({ page, request }) => {
    const token = await apiLogin(request);
    // 用后端生成的真实模板：既验证模板下载接口，又保证表头与页面映射一致
    const resp = await request.get(`${API_BASE}/imports/template`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(resp.ok(), `GET /imports/template -> HTTP ${resp.status()}`).toBeTruthy();
    const buffer = await resp.body();
    expect(buffer.length).toBeGreaterThan(1000);

    await login(page);
    await page.goto('/import');
    await expect(page.getByText('批量导入参数').first()).toBeVisible();

    // 页面有两个 Upload（参数导入 / 组网清单估算），第一个 accept 含 .csv 的是参数导入
    await page.locator('input[type="file"][accept*=".csv"]').setInputFiles({
      name: 'ROI参数录入模板.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer,
    });

    // 空模板必然出现「必填项缺失」，能走到这一步就说明 xlsx chunk 已加载并解析出字段行
    await expect(page.getByText(/解析完成|解析成功/).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('必填项缺失').first()).toBeVisible();

    // 官方模板前 3 行是标题/说明/空行，表头在第 4 行。空模板下非必填项会被跳过、
    // 只剩下「必填项缺失」的行——能出这些行就证明表头定位与字段映射都生效了。
    const rows = page.locator('.ant-table-tbody > tr.ant-table-row');
    await expect.poll(async () => rows.count(), { timeout: 10_000 }).toBeGreaterThan(5);
    await expect(page.getByText('GPU 数量').first()).toBeVisible();
    await expect(page.getByText('有效吞吐').first()).toBeVisible();
  });
});

/**
 * 报告导出（P1 REQ-12 / P2-5）端到端：三种格式都必须**下载到真实文件**。
 *
 * 关键回归点（此前无人验证）：后端对 `fmt=xinchuang` 的实际产物是 **Excel**
 * （interfaces/api/v1/reports.py 把 effective_fmt 改写为 excel），而前端曾按
 * `fmt === 'excel' ? 'xlsx' : 'pdf'` 推导扩展名，导致信创版下载出的
 * 「.pdf」其实是一份 xlsx —— 文件打不开。本用例直接校验扩展名与文件头一致。
 */
import fs from 'node:fs';
import { test, expect, type Download, type Page } from '@playwright/test';
import { apiLogin, buttonPattern, createScenario, deleteScenario, login } from './support';

/** 点导出按钮并等下载落盘，返回文件名与实际字节。 */
async function downloadReport(page: Page, label: string): Promise<{ name: string; bytes: Buffer }> {
  const [download]: [Download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: buttonPattern(label) }).first().click(),
  ]);
  const path = await download.path();
  expect(path, '下载应已落盘').toBeTruthy();
  return { name: download.suggestedFilename(), bytes: fs.readFileSync(path as string) };
}

test.describe('报告导出', () => {
  let token = '';
  let scenarioId = 0;
  let scenarioName = '';

  test.beforeEach(async ({ request, page }) => {
    token = await apiLogin(request);
    scenarioName = `e2e-报告-${Date.now()}`;
    scenarioId = await createScenario(request, token, scenarioName);
    await login(page);
    await page.goto(`/reports/${scenarioId}`);
    await expect(page.getByText(`报告导出 · ${scenarioName}`)).toBeVisible();
  });

  test.afterEach(async ({ request }) => {
    if (scenarioId) await deleteScenario(request, token, scenarioId).catch(() => undefined);
  });

  test('PDF 导出得到可用的 PDF 文件', async ({ page }) => {
    const { name, bytes } = await downloadReport(page, '导出 PDF');
    expect(name).toBe('ROI报告_pdf.pdf');
    expect(bytes.length).toBeGreaterThan(5000);
    expect(bytes.subarray(0, 5).toString('latin1')).toBe('%PDF-');
    await expect(page.locator('.ant-message').getByText('已开始下载 PDF 报告')).toBeVisible();
  });

  test('Excel 导出得到可用的 xlsx 文件', async ({ page }) => {
    const { name, bytes } = await downloadReport(page, '导出 Excel');
    expect(name).toBe('ROI报告_excel.xlsx');
    expect(bytes.length).toBeGreaterThan(3000);
    // xlsx 是 zip 容器：PK\x03\x04
    expect(bytes.subarray(0, 4).toString('latin1')).toBe('PK\x03\x04');
  });

  test('信创合规报表：内容为 xlsx，文件名也必须是 .xlsx（回归 .pdf 命名缺陷）', async ({ page }) => {
    const { name, bytes } = await downloadReport(page, '信创合规报表（xinchuang）');
    expect(name).toBe('ROI报告_信创合规.xlsx');
    expect(bytes.subarray(0, 4).toString('latin1')).toBe('PK\x03\x04');
    expect(bytes.length).toBeGreaterThan(3000);
    // 兜底：绝不允许出现「名为 pdf、实为 zip」的组合
    expect(name.endsWith('.pdf')).toBe(false);
  });
});

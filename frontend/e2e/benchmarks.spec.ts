/**
 * 基准库管理（P1 REQ-13）端到端：四类表格渲染 + 新增 / 编辑 / 删除全链路。
 *
 * 这是重构后唯一没有 UI 级回归保护的核心管理功能。用例会真实写库，因此
 * 使用固定代号并在 afterEach 里按代号清理，重复跑不会累积脏数据。
 */
import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import {
  apiLogin,
  apiPost,
  apiPut,
  buttonPattern,
  clickButton,
  deleteGpuByCode,
  findGpuByCode,
  getBenchBundle,
  login,
} from './support';

const CODE = 'E2E-BENCH-GPU';
/** 发布/回滚用例专用代号（与增删改用例互不干扰）。 */
const PUB_CODE = 'E2E-PUB-GPU';
const NAME = 'E2E 基准卡';
/** 与页面 `pagination={{ pageSize: 8 }}` 保持一致（用于算目标行落在第几页）。 */
const PAGE_SIZE = 8;

/** 定位某类基准的卡片（四张卡片的标题各不相同）。 */
function cardOf(page: Page, title: string) {
  return page
    .locator('.ant-card')
    .filter({ has: page.locator('.ant-card-head-title', { hasText: title }) });
}

/**
 * 翻到目标行所在页。
 * 列表由后端按 (vendor, code) 排序，新增行不保证在末页，故按真实顺序推算页码。
 */
async function gotoPageOfCode(
  request: APIRequestContext,
  token: string,
  page: Page,
  code: string,
): Promise<number> {
  const bundle = await getBenchBundle(request, token);
  const index = bundle.gpus.findIndex((row) => row.code === code);
  expect(index, `基准 ${code} 应已存在于后端列表`).toBeGreaterThanOrEqual(0);
  const pageNo = Math.floor(index / PAGE_SIZE) + 1;
  const card = cardOf(page, 'GPU 基准');
  await card.locator(`.ant-pagination-item-${pageNo}`).click();
  return pageNo;
}

/** 卡片内某代号所在的数据行。 */
function rowOfCode(page: Page, code: string) {
  // 用 .ant-table-row 而非 role=row：后者会把隐藏的 .ant-table-measure-row 也算进来
  return cardOf(page, 'GPU 基准').locator('.ant-table-row').filter({ hasText: code });
}

/** 当前正在行内编辑的那一行（只有它带「保存」按钮）。 */
function editingRow(page: Page) {
  return cardOf(page, 'GPU 基准')
    .locator('.ant-table-row')
    .filter({ has: page.getByRole('button', { name: buttonPattern('保存') }) });
}

test.describe('基准库管理', () => {
  let token = '';

  test.beforeEach(async ({ request, page }) => {
    token = await apiLogin(request);
    await deleteGpuByCode(request, token, CODE); // 前置清场：上轮异常中断的残留
    await login(page);
    await page.goto('/benchmarks');
  });

  test.afterEach(async ({ request }) => {
    await deleteGpuByCode(request, token, CODE);
  });

  test('四类基准表格渲染且写权限可见操作入口', async ({ page }) => {
    for (const title of ['GPU 基准', '模型基准', '云租赁价基准', '第三方 API 价基准']) {
      await expect(cardOf(page, title)).toBeVisible();
    }
    // demo 账号为 owner（含 benchmark:write）→ 每张卡片都有「新增」，行内都有「编辑/删除」
    for (const title of ['GPU 基准', '模型基准', '云租赁价基准', '第三方 API 价基准']) {
      await expect(cardOf(page, title).getByRole('button', { name: buttonPattern('新增') })).toBeVisible();
    }
    const gpuCard = cardOf(page, 'GPU 基准');
    await expect(gpuCard.locator('.ant-table-row').first()).toBeVisible();
    await expect(gpuCard.getByRole('button', { name: buttonPattern('编辑') }).first()).toBeVisible();
    await expect(gpuCard.getByRole('button', { name: buttonPattern('删除') }).first()).toBeVisible();
    // 分页生效（内置 GPU ≥ 9 行 → 出现第 2 页）
    await expect(gpuCard.locator('.ant-pagination')).toBeVisible();
  });

  test('新增 → 编辑（版本自增）→ 删除 全链路走真实接口', async ({ page, request }) => {
    const card = cardOf(page, 'GPU 基准');

    // ---------------------------------------------------------------- 新增
    await card.getByRole('button', { name: buttonPattern('新增') }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByLabel('代号').fill(CODE);
    await dialog.getByLabel('名称').fill(NAME);
    await dialog.getByLabel('厂商').fill('E2E');
    await dialog.getByLabel('价格(元)').fill('12345');
    await dialog.getByLabel('功耗(W)').fill('300');
    await dialog.getByLabel('显存(GB)').fill('80');
    await dialog.getByRole('button', { name: buttonPattern('确定') }).click();

    await expect(page.locator('.ant-message').getByText('已新增基准')).toBeVisible();
    await expect(dialog).toBeHidden();

    // 落库校验：字段值原样保存，归属为租户条目（is_builtin=false）
    const created = await findGpuByCode(request, token, CODE);
    expect(created, '新增的基准应能从后端读回').toBeTruthy();
    expect(created?.name).toBe(NAME);
    expect(created?.price_cny).toBe('12345');
    expect(created?.is_builtin).toBe(false);
    expect(created?.version).toBe(1);

    // UI 可见性：翻到它所在的页并确认渲染
    await page.reload();
    await gotoPageOfCode(request, token, page, CODE);
    const row = rowOfCode(page, CODE);
    await expect(row).toBeVisible();
    await expect(row).toContainText(NAME);

    // ---------------------------------------------------------------- 编辑
    await row.getByRole('button', { name: buttonPattern('编辑') }).click();
    // 进入编辑态后代号列变成 <input>，行内不再有该文本，故改用「带保存按钮的行」定位
    const editRow = editingRow(page);
    await expect(editRow).toBeVisible();
    const priceCell = editRow.locator('td').nth(3).locator('input'); // 列序：代号/名称/厂商/价格
    await expect(priceCell).toHaveValue('12345');
    await priceCell.fill('19999');
    await editRow.getByRole('button', { name: buttonPattern('保存') }).click();

    await expect(page.locator('.ant-message').getByText('已保存（版本自增）')).toBeVisible();
    const updated = await findGpuByCode(request, token, CODE);
    expect(updated?.price_cny).toBe('19999');
    expect(updated?.version, '编辑后版本号应自增').toBe(2);

    // ---------------------------------------------------------------- 删除
    await row.getByRole('button', { name: buttonPattern('删除') }).click();
    await page
      .locator('.ant-popconfirm')
      .getByRole('button', { name: buttonPattern('确定') })
      .click();

    await expect(page.locator('.ant-message').getByText('已删除')).toBeVisible();
    expect(await findGpuByCode(request, token, CODE), '删除后不应再查到该基准').toBeUndefined();
    await expect(rowOfCode(page, CODE)).toHaveCount(0);
  });

  test('新增表单必填校验拦截空提交', async ({ page }) => {
    await cardOf(page, 'GPU 基准').getByRole('button', { name: buttonPattern('新增') }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: buttonPattern('确定') }).click();
    // 代号 / 名称为必填，未填时不得发请求、不得关闭弹窗
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('请填写代号')).toBeVisible();
    await expect(dialog.getByText('请填写名称')).toBeVisible();
  });

  test('发布版本后可回滚：字段还原且行版本继续自增', async ({ page, request }) => {
    // 造一条本租户基准（v1，价格 100000），发布之后再改动，模拟「后来的维护」
    const created = await apiPost<{ id: number; version: number }>(request, token, '/benchmarks/gpus', {
      code: PUB_CODE,
      name: 'E2E 发布用卡',
      price_cny: '100000',
      tdp_w: '700',
    });
    try {
      await page.reload();

      // ---- 发布 ----
      await page.getByRole('button', { name: buttonPattern('发布版本') }).click();
      await expect(page.locator('.ant-message').getByText(/已发布基准库版本 #\d+/)).toBeVisible();

      // ---- 事后改动（v2，价格 222222） ----
      await apiPut<Record<string, unknown>>(request, token, `/benchmarks/gpus/${created.id}`, {
        price_cny: '222222',
      });

      // ---- 回滚到刚才的发布 ----
      await page.getByRole('button', { name: buttonPattern('发布历史') }).click();
      // antd 6 的抽屉按 role=dialog 命名（类名 .ant-drawer-content 已不可靠）
      const drawer = page.getByRole('dialog', { name: '基准库发布历史' });
      await expect(drawer).toBeVisible();
      // 历史按版本倒序，第一条就是刚发布的版本
      await drawer.getByRole('button', { name: buttonPattern('回滚到此版') }).first().click();
      const confirm = page.locator('.ant-popconfirm').filter({ hasText: '回滚到版本' });
      await confirm.getByRole('button', { name: buttonPattern('确定') }).click();
      await expect(page.locator('.ant-message').getByText(/已回滚 1 条/)).toBeVisible();

      // ---- 值已还原，且回滚本身也留痕（v2 → v3） ----
      const restored = await findGpuByCode(request, token, PUB_CODE);
      expect(Number(restored?.price_cny), '价格应还原为发布时的 100000').toBe(100000);
      expect(Number(restored?.version), '回滚应使行版本自增到 v3').toBe(3);
    } finally {
      await deleteGpuByCode(request, token, PUB_CODE);
    }
  });
});

/**
 * 生效日期（`as_of`）的数据质量回归。
 *
 * 背景：种子数据曾把 69 条基准的 `as_of` 全写成 `2026-08-01` 这个占位常量，
 * 界面上每一天都长一样，既看不出「这条数据是哪天的」，也无法判断老化程度。
 * 后端现在按 `source` 文本还原（只到月的取月末、无依据的置空），前端把空值
 * 显示成「未核实」、超 90 天标「过期」。这组断言守住三条底线：
 *
 * 1. 不再存在统一的占位日；
 * 2. 来源没写日期 ≠ 有个日期（必须是 null，而不是随便给一天）；
 * 3. 新鲜度提示条的数字与后端数据一致。
 */
test.describe('基准库 · 生效日期语义', () => {
  const PLACEHOLDER = '2026-08-01';

  test('日期不再是同一个占位值，且「不知道」就是空值', async ({ request, page }) => {
    const token = await apiLogin(request);
    const bundle = await getBenchBundle(request, token);
    const rows = [...bundle.gpus, ...bundle.models, ...bundle.cloud_prices, ...bundle.api_prices];
    expect(rows.length).toBeGreaterThan(0);

    // 1. 占位日彻底消失
    const stillPlaceholder = rows.filter((r) => String(r.as_of ?? '') === PLACEHOLDER);
    expect(stillPlaceholder.map((r) => String(r.code ?? r.model_code)), '仍有行停留在占位日期').toEqual([]);

    // 2. 日期分布确实被还原成了多个值，而不是换了个常量继续糊
    const values = new Set(rows.map((r) => (r.as_of === null ? '∅' : String(r.as_of))));
    expect(values.size, '所有行仍共用同一个日期').toBeGreaterThan(1);

    // 3. 无日期依据的条目（source=seed 等）必须是 null，不能伪造一天
    const seedRows = rows.filter((r) => String(r.source ?? '') === 'seed');
    expect(seedRows.length).toBeGreaterThan(0);
    for (const row of seedRows) {
      expect(row.as_of, `source=seed 的行不该有生效日期：${String(row.code ?? row.model_code)}`).toBeNull();
    }

    // 4. 界面把空值显示成「未核实」，且不再出现占位日
    await login(page);
    await page.goto('/benchmarks');
    await expect(page.getByTestId('inferencex-source-bar')).toBeVisible();
    await expect(page.getByText(PLACEHOLDER)).toHaveCount(0);
  });

  test('新鲜度提示条给出过期条数与最老一条', async ({ request, page }) => {
    const token = await apiLogin(request);
    const bundle = await getBenchBundle(request, token);
    const rows = [...bundle.gpus, ...bundle.models, ...bundle.cloud_prices, ...bundle.api_prices];

    const dayMs = 86_400_000;
    const today = Date.now();
    const ages = rows
      .filter((r) => r.as_of)
      .map((r) => Math.floor((today - Date.parse(`${String(r.as_of).slice(0, 10)}T00:00:00`)) / dayMs));
    const staleCount = ages.filter((d) => d > 90).length;
    const unknownCount = rows.length - ages.length;

    await login(page);
    await page.goto('/benchmarks');
    const alert = page.getByTestId('staleness-alert');

    if (staleCount === 0 && unknownCount === 0) {
      // 数据全新时不该出现警告条——提示条不是装饰
      await expect(alert).toHaveCount(0);
      return;
    }
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(`${staleCount} 条基准超过 90 天未更新`);
    if (unknownCount > 0) await expect(alert).toContainText(`${unknownCount} 条来源未标注日期`);
    // 最老一条必须点名到具体日期，否则「很老」还是句空话
    await expect(alert).toContainText(/\d{4}-\d{2}-\d{2}（\d+ 天前）/);
  });
});

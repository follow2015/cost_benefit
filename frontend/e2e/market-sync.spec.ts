/**
 * 租赁价采集端到端：四条链路的面板渲染 + GPU 行情抽屉的真实采集链路。
 *
 * 这套用例打的是**真实上游**（GetDeploying 的 1.1MB CSV），所以：
 * - 只断言结构与语义（有几个可采条目、有没有把「无市场」单独列出来），
 *   不断言具体价格——上游每天在变，断言数值等于每天都会红一次；
 * - 采集一次要几秒，超时给足。
 */
import { expect, test, type Page } from '@playwright/test';
import { login } from './support';

/** 采集要下载并解析上游 CSV，给足超时。 */
const COLLECT_TIMEOUT = 120_000;

/**
 * 拦截所有写库调用。
 *
 * 这套用例只验证「能不能正确采集并展示差异」，**绝不能真的改基准数据** ——
 * 那是测算输入，改一条就换一批结论。所以把 apply 端点全挡掉：
 * 万一某处误触发（例如重试、误点、组件副作用），测试会立刻失败而不是静默改库。
 */
async function blockWrites(page: Page): Promise<string[]> {
  const hits: string[] = [];
  await page.route('**/api/v1/benchmarks/**-apply*', async (route) => {
    hits.push(route.request().url());
    await route.abort();
  });
  return hits;
}

test.describe('基准库 · 数据采集面板', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/benchmarks');
    await expect(page.getByTestId('inferencex-source-bar')).toBeVisible();
  });

  test('四条采集链路各自有独立的按钮与状态', async ({ page }) => {
    // 成本标杆（自动，每 7 天）
    await expect(page.getByTestId('cost-benchmark-sync')).toBeVisible();
    await expect(page.getByTestId('inferencex-sync-button')).toBeVisible();

    // API 价（三源投票）
    await expect(page.getByTestId('authority-sync-block')).toBeVisible();
    await expect(page.getByTestId('authority-sync-button')).toBeVisible();

    // GPU 租赁价（本次新增）
    await expect(page.getByTestId('gpu-rental-sync-block')).toBeVisible();
    await expect(page.getByTestId('gpu-rental-sync-button')).toBeVisible();
    await expect(page.getByTestId('gpu-rental-coverage')).toContainText('已采集');

    // 云租赁价（本次新增）
    await expect(page.getByTestId('cloud-official-sync-block')).toBeVisible();
    await expect(page.getByTestId('cloud-official-sync-button')).toBeVisible();
    await expect(page.getByTestId('cloud-official-coverage')).toContainText('已采集');
  });

  test('GPU 覆盖率区分「可采集」与「国际市场无此 SKU」', async ({ page }) => {
    const gpuBlock = page.getByTestId('gpu-rental-sync-block');
    const text = (await gpuBlock.getByTestId('gpu-rental-coverage').innerText()) ?? '';

    // 14 个型号里 8 个国产/特供型号根本没有国际市场，必须单列出来而不是算作"待采集"
    expect(text).toMatch(/已采集\s*\d+\/\d+/);
    expect(text).toContain('国际市场无此 SKU');
  });

  test('GPU 行情抽屉能拉到真实数据并说明无源条目', async ({ page }) => {
    test.setTimeout(COLLECT_TIMEOUT);
    const writes = await blockWrites(page);
    await page.getByTestId('gpu-rental-sync-button').click();

    const drawer = page.locator('.ant-drawer').filter({ hasText: 'GPU 租赁行情' });
    await expect(drawer).toBeVisible({ timeout: 15_000 });

    // 采集完成后应出现至少一条可应用条目
    await expect(drawer.getByTestId('market-total')).toBeVisible({ timeout: COLLECT_TIMEOUT });
    const total = Number(await drawer.getByTestId('market-total').innerText());
    expect(total).toBeGreaterThan(0);

    // 「没有公开数据源」必须显式列出，且点名国产卡
    const manualOnly = drawer.getByTestId('market-manual-only');
    await expect(manualOnly).toBeVisible();
    await expect(manualOnly).toContainText('ASCEND910B');

    // 应用按钮默认可用（默认全选），且带上选中条数
    const applyBtn = drawer.getByTestId('market-apply');
    await expect(applyBtn).toContainText(`应用 ${total} 条`);

    // 全程只读：任何 apply 请求都说明有东西在偷偷写库
    expect(writes, `出现了意外的写库请求：${writes.join(', ')}`).toHaveLength(0);
  });

  test('云官价抽屉同时列出 Azure 与 AWS，并说明国内云无公开接口', async ({ page }) => {
    test.setTimeout(COLLECT_TIMEOUT);
    const writes = await blockWrites(page);
    await page.getByTestId('cloud-official-sync-button').click();

    const drawer = page.locator('.ant-drawer').filter({ hasText: '云厂商官方价' });
    await expect(drawer).toBeVisible({ timeout: 15_000 });

    await expect(drawer.getByTestId('market-total')).toBeVisible({ timeout: COLLECT_TIMEOUT });
    // 15 行里 Azure 1 行 + AWS 2 行（H100 / A100）有官方价格接口
    const total = Number(await drawer.getByTestId('market-total').innerText());
    expect(total).toBe(3);

    // 两家是两条独立报价，不能互相顶替
    await expect(drawer).toContainText('Azure · H100');
    await expect(drawer).toContainText('AWS · H100');
    await expect(drawer).toContainText('AWS · A100');

    const manualOnly = drawer.getByTestId('market-manual-only');
    await expect(manualOnly).toBeVisible();
    await expect(manualOnly).toContainText('阿里云');
    // AWS 已经接了接口，不能再被算成「没有数据源」
    await expect(manualOnly).not.toContainText('AWS');

    expect(writes, `出现了意外的写库请求：${writes.join(', ')}`).toHaveLength(0);
  });
});

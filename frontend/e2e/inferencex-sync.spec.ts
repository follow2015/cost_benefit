/**
 * InferenceX 自动采集：数据源提示 + 手动执行按钮（端到端）。
 *
 * 采集本身打真实上游（每 7 天一次的服务端任务），因此这里**不假设成功**：
 * - 有外网 → 走真实 HTTP，断言拿到成本点；
 * - 无外网/上游变更 → 后端返回 status=failed 并保留旧数据，前端必须给出可读提示。
 * 两种结果都要求「消息出现且不是静默失败」，这才是这条链路真正的契约。
 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import { apiGet, apiLogin, login } from './support';

interface SyncStatusResp {
  source: string;
  source_name: string;
  source_url: string;
  endpoint: string;
  interval_days: number;
  due: boolean;
  next_run_at: string | null;
  last: { status: string; started_at: string | null; point_count: number } | null;
}

interface SyncOutcomeResp {
  status: string;
  trigger: string;
  point_count: number;
  matched_count: number;
  added: number;
  updated: number;
  error: string;
  unmatched: string[];
  endpoint: string;
}

interface AuthorityStatusResp {
  fx_usd_cny: string;
  total: number;
  from_authority: number;
  manual: number;
  last_synced_at: string | null;
  as_of: string | null;
  sources: Array<{ source: string; label: string; url: string }>;
}

interface ModelCoverageResp {
  as_of: string | null;
  run_id: number | null;
  judgeable: boolean;
  upstream: {
    model_count: number;
    with_value: number;
    without_value: string[];
    unmatched: string[];
    models: Array<{ slug: string; code: string; point_count: number }>;
  };
  summary: {
    total: number;
    covered: number;
    no_value: number;
    untested: number;
    unknown: number;
  };
  rows: Array<{ code: string; status: string; label: string; slug: string; detail: string }>;
}

test.describe('InferenceX 数据源采集', () => {
  let token = '';

  test.beforeEach(async ({ request, page }) => {
    token = await apiLogin(request);
    await login(page);
    await page.goto('/benchmarks');
  });

  test('成本标杆与 API 价是两个独立按钮', async ({ page }) => {
    const panel = page.getByTestId('inferencex-source-bar');
    await expect(panel).toBeVisible();

    // 左栏：成本标杆（InferenceX 单源采集）
    const costCol = page.getByTestId('cost-benchmark-sync');
    await expect(costCol).toContainText('成本标杆');
    await expect(costCol.getByTestId('inferencex-sync-button')).toContainText('立即采集');

    // 右栏：API 价（三源投票）
    const authorityCol = page.getByTestId('authority-sync-block');
    await expect(authorityCol).toContainText('API 价');
    await expect(authorityCol.getByTestId('authority-sync-button')).toContainText('同步 API 价');

    // 两个按钮互不相同 → 分别触发、分别失败、分别重试
    const costBtn = costCol.getByTestId('inferencex-sync-button');
    const authBtn = authorityCol.getByTestId('authority-sync-button');
    await expect(costBtn).not.toHaveText((await authBtn.textContent()) ?? '');
  });

  test('模型基准翻遍所有页不崩，成本标杆/来源/生效日期都能读出来', async ({ page }) => {
    // 这条是回归用例：采集写入的 Decimal 在 JSON 里是**字符串**，
    // 早前「成本标杆」列直接 `.toFixed(3)` 会抛 `o.toFixed is not a function`，
    // 整个基准库被 ErrorBoundary 接走 —— 而它只在有采集数据的那几页才触发，
    // 首屏永远看不到，所以必须逐页翻。
    const table = page.locator('table').filter({ hasText: '成本标杆' }).first();
    await expect(table).toBeVisible();
    const wrapper = table.locator('xpath=ancestor::div[contains(@class,"ant-table-wrapper")][1]');

    const rows: string[] = [];
    const pageCount = Math.max(await wrapper.locator('.ant-pagination-item').count(), 1);
    for (let p = 1; p <= pageCount; p++) {
      if (p > 1) {
        await wrapper.locator(`.ant-pagination-item-${p}`).click();
        await page.waitForTimeout(600);
        await expect(table).toBeVisible();
      }
      // 只取真实数据行：`tbody` 里还夹着 antd 的 measure row / 吸顶表头副本，
      // 它们带着列名「成本标杆(¥/Mtok)」，会把下面的 ¥ 断言喂成表头。
      rows.push(...(await table.locator('tbody tr.ant-table-row').allInnerTexts()));
    }

    await expect(page.getByText('Unexpected Application Error')).toHaveCount(0);
    expect(rows.length).toBeGreaterThan(0);
    // 有成本标杆的行：必须是可读数字，且保留 3 位小数
    for (const row of rows.filter((r) => r.includes('¥'))) {
      expect(row).toMatch(/¥\d+\.\d{3}/);
    }
    // 采集接管过的行：来源写成 `InferenceX <数据生效日>`，配合绿色标签
    for (const row of rows.filter((r) => r.includes('InferenceX'))) {
      expect(row).toMatch(/InferenceX \d{4}-\d{2}-\d{2}/);
    }
  });

  test('权威同步状态接口返回覆盖率与生效日', async ({ request }) => {
    const status = await apiGet<AuthorityStatusResp>(request, token, '/benchmarks/authority-status');

    expect(status.total).toBeGreaterThan(0);
    expect(status.from_authority + status.manual).toBe(status.total);
    expect(status.sources).toHaveLength(3);
    expect(status.sources.map((s) => s.source)).toEqual(
      expect.arrayContaining(['litellm', 'modelsdev', 'openrouter']),
    );
  });

  test('基准库页标注数据源与采集周期，链接指向官方站点', async ({ page }) => {
    const bar = page.getByTestId('inferencex-source-bar');
    await expect(bar).toBeVisible();
    await expect(bar).toContainText('成本标杆');
    await expect(bar).toContainText('每 7 天自动采集');

    const link = page.getByTestId('inferencex-source-link');
    await expect(link).toHaveText('inferencex.semianalysis.com');
    await expect(link).toHaveAttribute('href', /inferencex\.semianalysis\.com/);
    await expect(link).toHaveAttribute('target', '_blank');
  });

  test('模型基准逐行标注采集覆盖，把「上游不测」和「本次缺数据」分开', async ({ page, request }) => {
    const coverage = await apiGet<ModelCoverageResp>(request, token, '/benchmarks/model-coverage');

    // 四种判决互斥且加总等于总行数：不能出现「既是上游不测又有值」
    const { summary } = coverage;
    expect(summary.total).toBeGreaterThan(0);
    expect(summary.total).toBe(
      summary.covered + summary.no_value + summary.untested + summary.unknown,
    );

    const upstreamCodes = new Set(coverage.upstream.models.map((m) => m.code));
    for (const row of coverage.rows) {
      expect(row.label).toMatch(/已采到|上游无值|上游不测|未采集/);
      if (!coverage.judgeable) continue;
      if (row.status === 'untested') {
        // 「上游不测」的唯一判据：不在上游这次返回的清单里
        expect(upstreamCodes.has(row.code)).toBe(false);
      }
      if (row.status === 'no_value') {
        // 「本次缺数据」的唯一判据：在上游清单里，只是没值
        expect(upstreamCodes.has(row.code)).toBe(true);
      }
    }
    // 有值的行必须真的在上游清单里取到过点数，不能是「凭空 covered」
    for (const row of coverage.rows.filter((r) => r.status === 'covered')) {
      expect(row.detail).toContain('已采到');
    }

    // 界面：模型表多出「采集覆盖」列，且首屏每行都有标签
    const table = page.locator('table').filter({ hasText: '采集覆盖' }).first();
    await expect(table).toBeVisible();
    const tags = table.locator('tbody tr.ant-table-row [data-testid^="coverage-"]');
    await expect(tags.first()).toBeVisible();
    expect(await tags.count()).toBeGreaterThan(0);

    // 面板那一栏要给出总量口径（不能只有一个孤零零的「已采到」数字）
    const line = page.getByTestId('model-coverage-line');
    await expect(line).toContainText(`模型覆盖 ${summary.covered}/${summary.total} 条`);
    if (coverage.judgeable) {
      await expect(line).toContainText('上游本次只测');
    } else {
      await expect(line).toContainText('重新采集后可判定');
    }
  });

  test('采集状态接口返回数据源、周期与上次结果', async ({ request }) => {
    const status = await apiGet<SyncStatusResp>(request, token, '/benchmarks/sync-status');

    expect(status.source).toBe('inferencex');
    expect(status.source_url).toContain('inferencex.semianalysis.com');
    expect(status.interval_days).toBe(7);
    expect(status.endpoint).toContain('/api/v1/overview');
    // 上次可能为空（全新库），非空时必须带状态与采集时间
    if (status.last) {
      expect(['success', 'partial', 'failed', 'skipped', 'running']).toContain(status.last.status);
      expect(status.last.started_at).toBeTruthy();
    }
  });

  test('手动采集按钮可执行，并给出非静默反馈', async ({ page }) => {
    // 真实上游 + 两次重试，最坏情况接近 60s
    test.setTimeout(120_000);
    const button = page.getByTestId('inferencex-sync-button');
    await expect(button).toBeVisible();
    await expect(button).toContainText('立即采集');

    // 统计「基准列表」的拉取次数：采集完成后必须重新拉一次，
    // 否则界面上生效日期/来源还停在旧值 —— 这正是「点了按钮没刷新」的根因。
    // 只认 /benchmarks 本体，不含 /benchmarks/sync-status 与 sync 自身。
    let listCalls = 0;
    page.on('request', (r) => {
      if (r.method() === 'GET' && /\/api\/v1\/benchmarks(\?|$)/.test(r.url())) listCalls += 1;
    });
    const before = listCalls;

    await button.click();

    // 成功/失败都必须落到一条 message 上：不能点了没反应
    const notice = page.locator('.ant-message-notice').last();
    await expect(notice).toBeVisible({ timeout: 90_000 });
    await expect(notice).toHaveText(/采集完成|采集失败|已跳过/);
    // 按钮必须恢复可点（loading 不会永久卡住）
    await expect(button).toBeEnabled({ timeout: 90_000 });

    await expect.poll(() => listCalls, { timeout: 30_000 }).toBeGreaterThan(before);
  });

  test('手动采集接口返回结构化结果（成功或失败都有原因）', async ({ request }) => {
    test.setTimeout(120_000);
    const res = await request.post(
      `${(process.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '')}/api/v1/benchmarks/sync`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(res.ok()).toBeTruthy();
    const body = (await res.json()) as { data: SyncOutcomeResp };
    const outcome = body.data;

    expect(outcome.trigger).toBe('manual');
    expect(['success', 'partial', 'failed', 'skipped']).toContain(outcome.status);
    if (outcome.status === 'failed') {
      // 失败必须给原因，且不能把已有数据清空（数据侧由后端单测保证不清空）
      expect(outcome.error).not.toBe('');
    } else {
      expect(outcome.point_count).toBeGreaterThan(0);
      expect(outcome.matched_count).toBeGreaterThan(0);
    }
  });
});

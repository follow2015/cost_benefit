/**
 * 财务输出数值复核（第四轮评审遗留项：e2e 只断言 KPI「存在」，未校验数值合理性）。
 *
 * 三层校验，逐层收紧，互不依赖：
 * ① **序列 ↔ 聚合自洽**：用返回的 36 期现金流重算 NPV / TCO / ROI / 回本 / IRR，
 *    与聚合字段逐项对齐。抓的是「聚合口径与明细口径漂移」。
 * ② **闭式解析对照**：把参数退化成等额年金（无通胀/无增长/无税/无杠杆/无残值），
 *    此时全部指标都有解析解，由测试代码独立算一遍再比对。抓的是「引擎系统性算错」
 *    ——黄金向量由引擎自身生成，只有解析解才是真正的独立预言机。
 * ③ **UI 渲染对齐**：结果页 KPI 卡片文本反解成数值，与载荷比对。抓的是
 *    「字段映射错、量纲错、单位被当成百分比」（静态回本曾被渲染成 2179.28%月）。
 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import { apiGet, apiPost, apiLogin, deleteScenario, login } from './support';

// --------------------------------------------------------------------------- 类型
interface CashflowRow {
  period: number;
  revenue: string;
  opex_cash: string;
  depreciation: string;
  ebt: string;
  interest: string;
  principal: string;
  tax: string;
  net_cf: string;
  cum_cf: string;
  discount_factor: string;
  discounted_cf: string;
  cum_discounted_cf: string;
}

interface Financials {
  I0: string;
  SV: string;
  r_m: string;
  npv: string;
  roi: string;
  tco: string;
  total_revenue: string;
  total_opex_cash: string;
  total_tax: string;
  total_net_cf: string;
  payback_static: string | null;
  payback_discounted: string | null;
  irr: { solution: boolean; irr_monthly: string | null; irr_annual: string | null };
  financing: { debt: string; equity: string; roe: string };
  cashflows: CashflowRow[];
  cashflows_yearly: CashflowRow[];
  notes: string[];
}

interface Derived {
  CAPEX: string;
  I0: string;
  SV: string;
  r_m: string;
  C_fix_cash: string;
}

interface CalcPayload {
  derived: Derived;
  financials: Financials;
  kpis: Array<{ key: string; label: string; value: string | null; unit: string; kind: string }>;
  params: Record<string, Record<string, unknown>>;
}

type ParamDict = Record<string, Record<string, unknown>>;

// --------------------------------------------------------------------------- 工具
/** 仅保留敏感性/情景/对比关闭的最小计算选项（少算 80%，载荷仍含完整现金流）。 */
const LITE_OPTIONS = {
  include_sensitivity: false,
  include_scenarios: false,
  include_crossover: false,
};

async function calcWithScenario(
  request: APIRequestContext,
  token: string,
  scenarioId: number,
): Promise<CalcPayload> {
  const res = await apiPost<{ payload: CalcPayload }>(request, token, '/calc', {
    scenario_id: scenarioId,
    options: LITE_OPTIONS,
  });
  return res.payload;
}

/** 无状态试算（不落库），用于同参数不同周期的对照。 */
async function calcStateless(
  request: APIRequestContext,
  token: string,
  params: ParamDict,
): Promise<CalcPayload> {
  const res = await apiPost<{ payload: CalcPayload }>(request, token, '/calc', {
    params,
    persist: false,
    options: LITE_OPTIONS,
  });
  return res.payload;
}

/** 相对容差断言：绝对值不超过 `max(absTol, |expected| × relTol)`。 */
function assertClose(actual: number, expected: number, label: string, absTol = 0.01, relTol = 1e-9): void {
  const tol = Math.max(absTol, Math.abs(expected) * relTol);
  expect(
    Math.abs(actual - expected),
    `${label}：实际 ${actual} / 期望 ${expected}（容差 ${tol}）`,
  ).toBeLessThanOrEqual(tol);
}

const sum = (values: number[]): number => values.reduce((a, b) => a + b, 0);
const n = (v: string | number | null | undefined): number =>
  v === null || v === undefined ? NaN : Number(v);

/** 把结果页 KPI 文本反解成数值：「118.20万」→ 1182000、「46.46%」→ 46.46。 */
function parseDisplay(text: string): number {
  const matched = text.trim().match(/^(-?\d+(?:\.\d+)?)(亿|万|%)?$/);
  if (!matched) return NaN;
  const base = Number(matched[1]);
  if (matched[2] === '亿') return base * 1e8;
  if (matched[2] === '万') return base * 1e4;
  return base;
}

/** 退化参数：等额年金（全部时间/增长/税/杠杆/残值因素清零），解析解可手算。 */
function degenerateParams(base: ParamDict, horizon: number): ParamDict {
  const params = JSON.parse(JSON.stringify(base)) as ParamDict;
  params.finance = { ...params.finance, T_horizon: String(horizon), infl: '0', debt_ratio: '0', cost_learning_rate: '0', revenue_ramp: false };
  params.pricing = { ...params.pricing, g_price: '0' };
  params.demand = { ...params.demand, g_demand: '0' };
  params.perf = { ...params.perf, SLA_penalty_rate: '0' };
  params.hw = { ...params.hw, S_pct: '0', pre_launch_cost: '0' };
  params.conventions = { ...(params.conventions ?? {}), taxed: false };
  return params;
}

// --------------------------------------------------------------------------- 用例
test.describe('财务输出数值复核', () => {
  let token = '';
  let createdId = 0;

  test.beforeEach(async ({ request }) => {
    token = await apiLogin(request);
  });

  test.afterEach(async ({ request }) => {
    if (createdId) await deleteScenario(request, token, createdId).catch(() => undefined);
    createdId = 0;
  });

  test('现金流序列重算出的 NPV/TCO/ROI/回本/IRR 与聚合字段一致', async ({ request }) => {
    const params = await apiGet<ParamDict>(request, token, '/scenarios/default-params');
    const detail = await apiPost<{ id: number }>(request, token, '/scenarios', { name: 'e2e-数值复核-自洽', params });
    createdId = detail.id;

    const payload = await calcWithScenario(request, token, createdId);
    const fin = payload.financials;
    const rows = fin.cashflows;

    // ---- 规模与期初口径 ----
    expect(rows.length, '现金流期数应等于分析周期 T_horizon').toBe(Number(params.finance.T_horizon));
    assertClose(
      n(payload.derived.I0),
      n(payload.derived.CAPEX) + n(params.hw.pre_launch_cost as number),
      'I0 = CAPEX + 上线前费用',
    );
    assertClose(n(payload.derived.SV), n(payload.derived.CAPEX) * n(params.hw.S_pct as number), 'SV = CAPEX × 残值率');
    assertClose(
      n(payload.derived.r_m),
      (1 + n(params.finance.r_w as number)) ** (1 / 12) - 1,
      'r_m = (1+r_w)^(1/12) − 1',
    );

    // ---- 逐期恒等式：折现因子、净现金流构成、累计递推 ----
    const r = n(fin.r_m);
    let cum = 0;
    let cumDisc = 0;
    for (const row of rows) {
      const period = row.period;
      const netCf = n(row.net_cf);
      const discountFactor = 1 / (1 + r) ** period;
      assertClose(n(row.discount_factor), discountFactor, `第 ${period} 期折现因子`);
      assertClose(n(row.discounted_cf), netCf * discountFactor, `第 ${period} 期折现值`);
      assertClose(
        n(row.ebt),
        n(row.revenue) - n(row.opex_cash) - n(row.depreciation) - n(row.interest),
        `第 ${period} 期 EBT = R − OPEX − 折旧 − 利息`,
      );
      assertClose(
        netCf,
        n(row.revenue) - n(row.opex_cash) - n(row.interest) - n(row.principal) - n(row.tax) +
          (period === rows.length ? n(fin.SV) : 0),
        `第 ${period} 期 CF = R − OPEX − 利息 − 本金 − 税 (+ 期末残值)`,
      );
      cum += netCf;
      cumDisc += n(row.discounted_cf);
      assertClose(n(row.cum_cf), cum, `第 ${period} 期累计现金流`);
      assertClose(n(row.cum_discounted_cf), cumDisc, `第 ${period} 期累计折现现金流`);
    }

    // ---- 聚合字段 = 明细求和 ----
    assertClose(n(fin.total_revenue), sum(rows.map((x) => n(x.revenue))), 'Σ revenue');
    assertClose(n(fin.total_opex_cash), sum(rows.map((x) => n(x.opex_cash))), 'Σ opex_cash');
    assertClose(n(fin.total_tax), sum(rows.map((x) => n(x.tax))), 'Σ tax');
    assertClose(n(fin.total_net_cf), sum(rows.map((x) => n(x.net_cf))), 'Σ net_cf');
    assertClose(n(fin.tco), n(payload.derived.CAPEX) + n(fin.total_opex_cash), 'TCO = CAPEX + Σ OPEX');
    assertClose(n(fin.roi), (n(fin.total_net_cf) - n(fin.I0)) / n(fin.I0), 'ROI = (ΣCF − I0)/I0');

    // ---- NPV = −权益 + Σ 折现值（默认无杠杆时权益 = I0） ----
    assertClose(n(fin.financing.equity), n(fin.I0) * (1 - n(params.finance.debt_ratio as number)), '权益 = I0×(1−负债率)');
    assertClose(n(fin.npv), -n(fin.financing.equity) + sum(rows.map((x) => n(x.discounted_cf))), 'NPV');

    // ---- 回本周期：累计现金流首次转正的线性插值 ----
    const paybackBySeries = (threshold: number, key: 'cum_cf' | 'cum_discounted_cf', flow: 'net_cf' | 'discounted_cf') => {
      let previous = 0;
      for (const row of rows) {
        const cumValue = n(row[key]);
        if (cumValue >= threshold) {
          const current = n(row[flow]);
          return current === 0 ? row.period : row.period - 1 + (threshold - previous) / current;
        }
        previous = cumValue;
      }
      return null;
    };
    const staticPayback = paybackBySeries(n(fin.I0), 'cum_cf', 'net_cf');
    const discountedPayback = paybackBySeries(n(fin.I0), 'cum_discounted_cf', 'discounted_cf');
    if (staticPayback === null) {
      expect(fin.payback_static, '序列未回本时聚合字段必须为 null').toBeNull();
    } else {
      assertClose(n(fin.payback_static), staticPayback, '静态回本');
    }
    if (discountedPayback === null) {
      expect(fin.payback_discounted, '序列未折现回本时聚合字段必须为 null').toBeNull();
    } else {
      assertClose(n(fin.payback_discounted), discountedPayback, '折现回本');
    }

    // ---- IRR：权益现金流序列在 irr_monthly 处 NPV 应为 0，年化口径一致 ----
    expect(fin.irr.solution, '默认参数应有唯一 IRR 实根').toBe(true);
    const irrMonthly = n(fin.irr.irr_monthly);
    const equitySeries = [-n(fin.financing.equity), ...rows.map((x) => n(x.net_cf))];
    const npvAtIrr = sum(equitySeries.map((cf, t) => (t === 0 ? cf : cf / (1 + irrMonthly) ** t)));
    assertClose(npvAtIrr, 0, 'IRR 处权益 NPV 应为 0', 0.01);
    assertClose(n(fin.irr.irr_annual), (1 + irrMonthly) ** 12 - 1, 'IRR 年化 = (1+r_m)^12 − 1');

    // ---- 年度聚合只是月度序列的分桶，不得改变总量 ----
    assertClose(sum(fin.cashflows_yearly.map((x) => n(x.net_cf))), n(fin.total_net_cf), '年度净现金流合计');
    assertClose(
      sum(fin.cashflows_yearly.map((x) => n(x.discounted_cf))),
      sum(rows.map((x) => n(x.discounted_cf))),
      '年度折现现金流合计',
    );
    expect(fin.cashflows_yearly.length, '年度序列档数应为周期/12 上取整').toBe(Math.ceil(rows.length / 12));
  });

  test('等额年金退化的解析解对照（闭式 NPV / 回本 / 折现回本）', async ({ request }) => {
    const base = await apiGet<ParamDict>(request, token, '/scenarios/default-params');
    const shortParams = degenerateParams(base, 24);
    const longParams = degenerateParams(base, 48);

    const [short, long] = await Promise.all([
      calcStateless(request, token, shortParams),
      calcStateless(request, token, longParams),
    ]);
    const shortRows = short.financials.cashflows;
    const longRows = long.financials.cashflows;
    expect(shortRows.length).toBe(24);
    expect(longRows.length).toBe(48);

    // ---- 退化性：算出来必须是「等额」现金流，否则解析解前提不成立 ----
    const cf = n(shortRows[0].net_cf);
    expect(cf, '退化参数下首期净现金流应大于 0').toBeGreaterThan(0);
    for (const row of shortRows) {
      assertClose(n(row.net_cf), cf, `第 ${row.period} 期净现金流应等额`);
      assertClose(n(row.tax), 0, `第 ${row.period} 期税前口径不应计所得税`);
    }
    assertClose(n(short.financials.SV), 0, '残值率 0 ⇒ 期末残值 0');
    assertClose(n(short.financials.I0), n(long.financials.I0), '分析周期不改变期初投资');

    const r = n(short.financials.r_m);
    const I0 = n(short.financials.I0);

    // ---- 解析解 ①：NPV = −I0 + CF × Σ_{t=1..T} (1+r)^−t ----
    const annuity = (horizon: number) => sum(Array.from({ length: horizon }, (_, i) => (1 + r) ** -(i + 1)));
    assertClose(n(short.financials.npv), -I0 + cf * annuity(24), 'NPV(24) 年金闭式');
    assertClose(n(long.financials.npv), -I0 + cf * annuity(48), 'NPV(48) 年金闭式');

    // ---- 解析解 ②：静态回本 = I0 / CF（等额现金流下插值即等比） ----
    assertClose(n(short.financials.payback_static), I0 / cf, '静态回本闭式');

    // ---- 解析解 ③：折现回本。引擎按「离散年金 + 期内线性插值」给值，
    //      因此不比连续解析根逐位相等，而要求 ① 该点累计折现值回到 I0（相对 0.1% 内）；
    //      ② 与连续解析根 −ln(1−I0·r/CF)/ln(1+r) 的偏差远小于 1 期。 ----
    const annuityAt = (months: number) => (1 - (1 + r) ** -months) / r;
    const discountedPayback = n(short.financials.payback_discounted);
    assertClose(annuityAt(discountedPayback) * cf, I0, '折现回本处累计折现值应回到 I0', I0 * 1e-3, 0);
    assertClose(
      discountedPayback,
      -Math.log(1 - (I0 * r) / cf) / Math.log(1 + r),
      '折现回本 vs 连续解析根',
      0.05,
    );

    // ---- 跨周期一致性：延长周期只是把后续等额现金流纳入，差额必须是年金增量 ----
    assertClose(
      n(long.financials.npv) - n(short.financials.npv),
      cf * (annuity(48) - annuity(24)),
      'NPV(48) − NPV(24) = CF × 年金增量',
    );
    assertClose(n(long.financials.roi) - n(short.financials.roi), (cf * 24) / I0, 'ROI 增量 = 24 期等额现金流 / I0');
  });

  test('结果页 KPI 卡片数值与载荷一致（量纲不得错位）', async ({ page, request }) => {
    const params = await apiGet<ParamDict>(request, token, '/scenarios/default-params');
    const detail = await apiPost<{ id: number }>(request, token, '/scenarios', { name: 'e2e-数值复核-渲染', params });
    createdId = detail.id;
    const payload = await calcWithScenario(request, token, createdId);
    const fin = payload.financials;

    await login(page);
    await page.goto(`/scenarios/${createdId}`);
    await expect(page.getByText('NPV', { exact: true }).first()).toBeVisible();

    /** 卡片值文本：StatCard 把「标签（单位）」放在 value 的 title 上，可直接定位。 */
    const card = async (label: string, unit: string) => {
      const valueLocator = page.locator(`.num-mono[title="${label}（${unit}）"]`).first();
      await expect(valueLocator, `应渲染 ${label} 卡片`).toBeVisible();
      // 比率类已不再渲染单位后缀（数值自带 %，再挂「比率」纯属噪音），取不到即为空
      const suffixLocator = valueLocator.locator('xpath=following-sibling::span').first();
      const suffix =
        (await suffixLocator.count()) > 0 ? (await suffixLocator.innerText()).trim() : '';
      return {
        text: (await valueLocator.innerText()).trim(),
        suffix,
      };
    };

    // ---- 静态回本：量纲必须是「月」，曾被渲染成 2179.28% ----
    const payback = await card('静态回本', '月');
    expect(payback.text, '静态回本不得按百分比渲染').not.toContain('%');
    expect(payback.suffix, '静态回本的卡片后缀应为「月」').toBe('月');
    assertClose(parseDisplay(payback.text), n(fin.payback_static), '静态回本卡片数值', 0.005);

    // ---- 折现回本：同类指标一并盯住 ----
    const paybackDisc = await card('折现回本', '月');
    expect(paybackDisc.text, '折现回本不得按百分比渲染').not.toContain('%');
    assertClose(parseDisplay(paybackDisc.text), n(fin.payback_discounted), '折现回本卡片数值', 0.005);

    // ---- NPV / TCO：万·亿进位后反解，容差为半个最小单位（0.005 万 = 50 元） ----
    const npv = await card('NPV', '元');
    assertClose(parseDisplay(npv.text), n(fin.npv), 'NPV 卡片数值', 50);
    expect(npv.suffix).toBe('元');

    const tco = await card('TCO（全周期）', '元');
    assertClose(parseDisplay(tco.text), n(fin.tco), 'TCO 卡片数值', 50);

    // ---- IRR：百分比反解成小数点，容差 0.005% ----
    const irr = await card('IRR（年化）', '比率/年');
    expect(irr.text, 'IRR 应按百分比渲染').toContain('%');
    expect(irr.suffix, '比率类数值已带 %，卡片后缀不应再挂「比率/年」').toBe('');
    assertClose(parseDisplay(irr.text), n(fin.irr.irr_annual) * 100, 'IRR 卡片数值（百分点）', 0.005);

    // ---- ROI 同样走百分比 ----
    const roi = await card('ROI', '比率');
    expect(roi.suffix, '比率类数值已带 %，卡片后缀不应再挂「比率」').toBe('');
    assertClose(parseDisplay(roi.text), n(fin.roi) * 100, 'ROI 卡片数值（百分点）', 0.005);
  });
});

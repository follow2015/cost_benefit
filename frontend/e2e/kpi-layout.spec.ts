/**
 * KPI 展示排版护栏。
 *
 * 钉住的是两个已修缺陷，二者都是「看起来只是不好看，其实读错了数」：
 *
 * 1. 窄列下数值被从**中间**拆开。antd `Statistic` 的 content 是 block + normal
 *    换行，值与单位作为行内内容按字符断行：1024px 下每个 KPI 只有 118px，
 *    「118.20万 / 元」被拆成三行、「Token/度」断成「Token/」+「度」。
 *    修法是数值与单位各自 nowrap、容器 flex-wrap（见 `shared/ui/KpiStat.tsx`）。
 *    这里按「行高 × 行数」判读，比断言像素更稳、也不依赖具体字号。
 * 2. 比率类 KPI 在百分号后面再挂「比率」。数值已是 `46.46%`，元数据 unit 是
 *    量纲说明不是单位，紧跟只添噪音（且宽 88–94px，是换行主因之一）。
 *
 * 三档宽度都跑：1440 通过不代表 1024 通过，反例正是窄屏。
 */
import { test, expect } from '@playwright/test';
import { clickButton, login } from './support';

/** 读取全部 KPI 的排版度量：数值/单位各占几行、是否撑破所在列。 */
async function measure(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const lineH = (el: HTMLElement) => parseFloat(getComputedStyle(el).lineHeight) || el.getBoundingClientRect().height;
    type Row = {
      label: string;
      value: string;
      unit: string;
      vLines: number;
      uLines: number;
      overflowPx: number;
    };
    const rows: Row[] = [];
    document.querySelectorAll('[data-kpi-value]').forEach((node) => {
      const valueEl = node as HTMLElement;
      const holder = valueEl.parentElement as HTMLElement;
      const unitEl = holder.querySelector('[data-kpi-unit]') as HTMLElement | null;
      const cell = holder.parentElement as HTMLElement;
      const labelEl = cell.firstElementChild as HTMLElement | null;
      const cellRect = cell.getBoundingClientRect();
      const vr = valueEl.getBoundingClientRect();
      const ur = unitEl?.getBoundingClientRect();
      // nowrap 之后「断行」不再发生，代价变成撑破所在列——必须一起量，
      // 只测断行的话护栏会被 nowrap 骗过去（实测撤掉修复仍绿）。
      const overflowPx = Math.max(
        0,
        Math.round(Math.max(vr.right, ur ? ur.right : 0) - cellRect.right),
      );
      rows.push({
        label: (labelEl?.textContent ?? '').trim(),
        value: (valueEl.textContent ?? '').trim(),
        unit: (unitEl?.textContent ?? '').trim(),
        vLines: Math.round(vr.height / lineH(valueEl)),
        uLines: ur ? Math.round(ur.height / lineH(unitEl as HTMLElement)) : 1,
        overflowPx,
      });
    });
    return rows;
  });
}

for (const width of [1024, 1280, 1440]) {
  test(`向导预览 KPI 数值与单位各自完整（@${width}）`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await login(page);
    await page.goto('/scenarios/new');
    await page.waitForSelector('[data-kpi-value]', { timeout: 30_000 });
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-kpi-value]');
        return !!el && (el.textContent ?? '').trim() !== '' && (el.textContent ?? '').trim() !== '—';
      },
      undefined,
      { timeout: 30_000 },
    );

    const rows = await measure(page);
    expect(rows.length).toBeGreaterThanOrEqual(15);

    const broken = rows.filter((r) => r.vLines > 1 || r.uLines > 1 || r.overflowPx > 1);
    expect(
      broken.map((r) => `${r.label}: ${r.value} ${r.unit}（数值 ${r.vLines} 行 / 单位 ${r.uLines} 行 / 溢出 ${r.overflowPx}px）`),
      '数值与单位都必须各自完整且待在本列内：不许从数字中间断开，也不许撑破列宽压到相邻列',
    ).toEqual([]);
  });
}

test('比率类 KPI 不在百分号后再挂「比率」', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page);
  await page.goto('/scenarios/new');
  await page.waitForSelector('[data-kpi-value]', { timeout: 30_000 });
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[data-kpi-value]');
      return !!el && (el.textContent ?? '').trim() !== '';
    },
    undefined,
    { timeout: 30_000 },
  );

  const rows = await measure(page);
  const ratios = rows.filter((r) => r.value.endsWith('%'));
  expect(ratios.length, '默认参数下应有若干比率类 KPI（ROI / 毛利率 / 盈亏平衡利用率 …）').toBeGreaterThan(0);
  for (const r of ratios) {
    expect(r.unit, `${r.label} 的数值已是百分比，后缀不得再写「比率」`).not.toContain('比率');
  }
  // 反向：非比率的金额/月份类必须仍带单位，否则就是矫枉过正
  const money = rows.find((r) => r.label.includes('NPV'));
  expect(money?.unit).toBe('元');
  const payback = rows.find((r) => r.label.includes('静态回本'));
  expect(payback?.unit).toBe('月');
});

test('结果页 KPI 卡同样不被拆开（@1024 最窄列）', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  await login(page);
  await page.getByText('新建测算方案').first().click();
  await expect(page).toHaveURL(/\/scenarios\/new$/);
  await page.getByPlaceholder('例如：H100×8 自建 vs 租赁对比').fill('e2e-KPI排版');
  await clickButton(page, '保存并计算');
  await expect(page).toHaveURL(/\/scenarios\/\d+/);
  await page.waitForSelector('[data-kpi-value]', { timeout: 30_000 });
  await page.waitForTimeout(1500);

  const rows = await measure(page);
  expect(rows.length).toBeGreaterThanOrEqual(10);
  const broken = rows.filter((r) => r.vLines > 1 || r.uLines > 1 || r.overflowPx > 1);
  expect(
    broken.map((r) => `${r.label}: ${r.value} ${r.unit}（数值 ${r.vLines} 行 / 单位 ${r.uLines} 行 / 溢出 ${r.overflowPx}px）`),
    '结果页数值与单位也必须各自完整且待在本列内',
  ).toEqual([]);
});

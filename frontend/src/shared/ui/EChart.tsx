/**
 * ECharts 按需入口（唯一引入点）。
 *
 * 此前 8 个图表都从 `echarts-for-react` 默认入口引入，它内部 `import * as echarts from 'echarts'`，
 * 把全部图表类型 + 全部组件 + 双渲染器打进包里（结果页 chunk 因此达到 1.04 MB）。
 *
 * 这里只注册实际用到的能力：
 * - 图表：line（现金流/盈亏平衡/三方案交叉）、bar（龙卷风/蒙特卡洛直方图/自定义情景）、pie（成本结构）
 * - 组件：grid / tooltip / legend / title（两张图带标题）/ markLine（零轴、回本点标线）、
 *   axisPointer（tooltip 的 `trigger: 'axis'` 与 `axisPointer.type: 'shadow'`）
 * - 渲染器：canvas（全站未用 SVG 渲染）
 *
 * 新增图表类型或组件时**必须**回到本文件补注册，否则运行时会静默画不出来。
 * 刻意不提供 `echarts` 具名导出：外部应只通过本组件使用，避免绕开按需边界。
 */
import React from 'react';
// 必须走 esm/ 入口：lib/ 是 CJS，Vite dev 的 interop 会把默认导出包成 `{ default }`，
// React 19 报「Element type is invalid ... got: object」。生产构建能过、dev 白屏，
// 这种 dev/prod 不一致只有在浏览器里跑才暴露（见 e2e/charts.spec.ts）。
import ReactEChartsCore from 'echarts-for-react/esm/core';
import type { EChartsReactProps } from 'echarts-for-react/esm/types';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import {
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
]);

/** 与 `echarts-for-react` 默认导出同名的封装，调用方只需改 import 路径。 */
export default function ReactECharts(props: EChartsReactProps): React.ReactElement {
  return <ReactEChartsCore echarts={echarts} {...props} />;
}

/**
 * 向导参数元数据：描述每个字段的分组、标签、单位、类型与边界。
 * 渲染层据此自动生成表单；与后端 `app/calc/parameters.py` 字段对齐。
 * 缺省字段由 codec 回落到默认参数，不影响计算口径。
 */

import type { ScenarioParams } from '@/features/calc/engine/parameters';

export type FieldType = 'number' | 'percent' | 'percentPositive' | 'select' | 'switch' | 'nullable-number' | 'text';

export interface FieldMeta {
  path: string; // group.field
  label: string;
  unit?: string;
  type: FieldType;
  step?: number;
  min?: number;
  max?: number;
  options?: { value: string; label: string }[];
  hint?: string;
  /** percent 字段在 UI 中以百分比展示，存储为比率（×100 转换）。 */
  scale100?: boolean;
  /** M-17 来源标记：字段取值来源（基准库 benchmark / 用户估算 estimated）。用于 UI 来源徽标。 */
  source?: 'benchmark' | 'estimated';
}

export interface GroupMeta {
  key: keyof ScenarioParams;
  label: string;
  fields: FieldMeta[];
}

export const GROUPS: GroupMeta[] = [
  {
    key: 'hw',
    label: '硬件投资',
    fields: [
      { path: 'hw.N_gpu', label: 'GPU 数量', unit: '张', type: 'number', step: 1, min: 0 },
      { path: 'hw.P_gpu', label: '单卡价格', unit: '元/张', type: 'number', step: 1000, min: 0 },
      { path: 'hw.P_aux', label: '辅助设备 CAPEX', unit: '元', type: 'number', step: 1000, min: 0, hint: '整机配套价；硬件反选推荐时承载存储+组网配套 CAPEX（含于总硬件投资）' },
      { path: 'hw.T_deploy', label: '部署周期', unit: '月', type: 'number', step: 0.5, min: 0 },
      { path: 'hw.availability', label: '可用率', unit: '%', type: 'percent', step: 0.1, min: 0, max: 1, scale100: true },
      { path: 'hw.Y_dep', label: '折旧年限', unit: '年', type: 'number', step: 0.5, min: 0 },
      { path: 'hw.S_pct', label: '残值率', unit: '%', type: 'percent', step: 0.5, min: 0, max: 1, scale100: true },
      { path: 'hw.L_sw', label: '软件授权摊销', unit: '元', type: 'number', step: 1000, min: 0 },
      { path: 'hw.pre_launch_cost', label: '上线前费用', unit: '元', type: 'number', step: 1000, min: 0 },
    ],
  },
  {
    key: 'power',
    label: '电力与运维',
    fields: [
      { path: 'power.TDP', label: '单卡 TDP', unit: 'W', type: 'number', step: 10, min: 0 },
      { path: 'power.P_aux_power', label: '辅助功耗', unit: 'kW', type: 'number', step: 0.1, min: 0 },
      { path: 'power.P_sys_override', label: '整机功耗(覆盖)', unit: 'kW', type: 'nullable-number', step: 0.1, min: 0, hint: '留空则按 N_gpu×TDP/1000+P_aux 推算' },
      { path: 'power.PUE', label: 'PUE', unit: '', type: 'number', step: 0.01, min: 1 },
      { path: 'power.E_price', label: '电价', unit: '元/kWh', type: 'number', step: 0.01, min: 0 },
      { path: 'power.e_price_peak', label: '峰时电价', unit: '元/kWh', type: 'number', step: 0.01, min: 0, hint: '分时 TOU：峰段单价（默认 = 电价 E_price，退化为现状）' },
      { path: 'power.e_price_flat', label: '平时电价', unit: '元/kWh', type: 'number', step: 0.01, min: 0, hint: '分时 TOU：平段单价（默认 = 电价 E_price）' },
      { path: 'power.e_price_valley', label: '谷时电价', unit: '元/kWh', type: 'number', step: 0.01, min: 0, hint: '分时 TOU：谷段单价（默认 = 电价 E_price）' },
      { path: 'power.tou_peak_share', label: '峰段占比', unit: '%', type: 'percent', step: 1, min: 0, max: 1, scale100: true, hint: '峰段月小时占比；加权电价 = 谷×谷占比 + 平×平占比 + 峰×峰占比' },
      { path: 'power.tou_valley_share', label: '谷段占比', unit: '%', type: 'percent', step: 1, min: 0, max: 1, scale100: true, hint: '谷段月小时占比；平段占比 = 1 − 峰占比 − 谷占比' },
      {
        path: 'power.power_mode', label: '电力运维口径', unit: '', type: 'select',
        options: [
          { value: 'separate', label: '柜电分离（机柜费 + 电费按功耗）' },
          { value: 'bundle', label: '包柜包电（机柜+电费一口价）' },
        ],
        hint: '柜电分离=现状（机位租金 Co_loc + 电费按 P_sys×PUE×电价×利用率）；包柜包电=托管商一口价（元/柜/月），电费不再按功耗核算',
      },
      { path: 'power.bundle_monthly_per_rack', label: '包柜包电单价', unit: '元/柜/月', type: 'number', step: 100, min: 0, hint: '包柜包电模式下生效：含机柜+电费一口价；此时机位租金与按功耗电费不再计' },
      { path: 'power.racks', label: '机柜数', unit: '柜', type: 'number', step: 1, min: 0, hint: '0=按卡数自动推导（ceil(N_gpu/32)）；包柜包电按此计费' },
      { path: 'power.nodes_per_rack', label: '每柜节点数', unit: '台/柜', type: 'number', step: 1, min: 1, hint: '机柜数自动推导参考（默认 4 台/柜）' },
      { path: 'power.Co_loc', label: '机位租金', unit: '元/月', type: 'number', step: 100, min: 0, hint: '柜电分离模式生效' },
      { path: 'power.Co_net', label: '网络费用', unit: '元/月', type: 'number', step: 100, min: 0 },
      { path: 'power.Co_stor', label: '存储费用', unit: '元/月', type: 'number', step: 100, min: 0 },
      { path: 'power.Co_ops', label: '运维人力', unit: '元/年', type: 'number', step: 1000, min: 0 },
    ],
  },
  {
    key: 'perf',
    label: '性能与吞吐',
    fields: [
      { path: 'perf.M_param', label: '模型参数量', unit: 'B', type: 'number', step: 1, min: 0 },
      { path: 'perf.quant', label: '量化', unit: '', type: 'select', options: [
        { value: 'FP8', label: 'FP8' }, { value: 'FP16', label: 'FP16' }, { value: 'INT8', label: 'INT8' }, { value: 'INT4', label: 'INT4' },
      ] },
      { path: 'perf.Mem_w', label: '权重显存', unit: 'GB', type: 'number', step: 1, min: 0 },
      { path: 'perf.Ctx', label: '上下文长度', unit: 'tok', type: 'number', step: 512, min: 0 },
      { path: 'perf.B_max', label: '最大批大小', unit: '', type: 'number', step: 1, min: 0 },
      { path: 'perf.T_eff', label: '有效吞吐', unit: 'tok/s', type: 'number', step: 100, min: 0, source: 'estimated', hint: '默认值为待核实估算；建议用实测或基准库覆盖' },
      { path: 'perf.T_pf', label: 'Prefill 吞吐', unit: 'tok/s', type: 'number', step: 100, min: 0, source: 'estimated', hint: '默认值为待核实估算；建议用实测或基准库覆盖' },
      { path: 'perf.T_dc', label: 'Decode 吞吐', unit: 'tok/s', type: 'number', step: 100, min: 0, source: 'estimated', hint: '默认值为待核实估算；建议用实测或基准库覆盖' },
      { path: 'perf.SLA_ttft', label: 'SLA TTFT', unit: 'ms', type: 'number', step: 10, min: 0 },
      { path: 'perf.SLA_tpot', label: 'SLA TPOT', unit: 'ms', type: 'number', step: 5, min: 0 },
      { path: 'perf.k_override', label: 'k 实测/录入', unit: '比率', type: 'nullable-number', step: 0.01, min: 0, source: 'estimated', hint: '解码/总 token 比；留空则按 T_dc/T_pf 或基准库推算（缺省 0.1 为估算值）' },
      { path: 'perf.k_benchmark', label: 'k 基准库', unit: '比率', type: 'nullable-number', step: 0.01, min: 0, hint: '从模型基准库带入' },
    ],
  },
  {
    key: 'demand',
    label: '需求结构',
    fields: [
      { path: 'demand.rho', label: '输入/输出比', unit: '', type: 'number', step: 0.1, min: 0 },
      { path: 'demand.D_eq', label: '等效月需求', unit: 'Mtok/月', type: 'number', step: 10, min: 0 },
      { path: 'demand.h', label: '缓存命中率', unit: '%', type: 'percent', step: 1, min: 0, max: 1, scale100: true },
      { path: 'demand.U', label: '利用率', unit: '%', type: 'percent', step: 1, min: 0, max: 1, scale100: true },
      { path: 'demand.K_peak', label: '峰谷系数', unit: '', type: 'number', step: 0.1, min: 0 },
      { path: 'demand.g_demand', label: '需求年增长率', unit: '%/年', type: 'percent', step: 0.5, min: -0.2, max: 0.5, scale100: true, hint: '按月 D_t = D·(1+g)^floor((t−1)/12) 爬坡；默认 0 为恒量需求' },
      { path: 'demand.util_mode', label: '利用率口径', unit: '', type: 'select', options: [
        { value: 'explicit', label: '直接给定 U' }, { value: 'demand_from_u', label: '由 U 推需求' }, { value: 'u_from_demand', label: '由需求推 U' },
      ] },
    ],
  },
  {
    key: 'pricing',
    label: '定价与成本',
    fields: [
      { path: 'pricing.p_in', label: '输入单价', unit: '元/Mtok', type: 'number', step: 0.5, min: 0 },
      { path: 'pricing.p_out', label: '输出单价', unit: '元/Mtok', type: 'number', step: 0.5, min: 0 },
      { path: 'pricing.p_cache', label: '缓存单价', unit: '元/Mtok', type: 'nullable-number', step: 0.5, min: 0, hint: '留空按 p_in/10' },
      { path: 'pricing.g_price', label: '价格年降', unit: '%/年', type: 'percent', step: 0.5, min: 0, max: 1, scale100: true },
      { path: 'pricing.Rent_gpu', label: '租用单价', unit: '元/GPU·时', type: 'number', step: 0.5, min: 0 },
      { path: 'pricing.rent_inc', label: '租金含项', unit: '', type: 'select', options: [
        { value: 'power', label: '含电' }, { value: 'power_hosting', label: '含电+托管' }, { value: 'none', label: '纯算力' },
      ] },
      { path: 'pricing.rent_fixed_monthly', label: '包月固定', unit: '元/月', type: 'number', step: 100, min: 0 },
      { path: 'pricing.API_in', label: 'API 输入价', unit: '元/Mtok', type: 'number', step: 1, min: 0 },
      { path: 'pricing.API_out', label: 'API 输出价', unit: '元/Mtok', type: 'number', step: 1, min: 0 },
      { path: 'pricing.API_cache', label: 'API 缓存价', unit: '元/Mtok', type: 'nullable-number', step: 1, min: 0 },
      { path: 'pricing.cost_benchmark', label: '市场成本标杆', unit: '元/Mtok', type: 'nullable-number', step: 0.01, min: 0, source: 'benchmark', hint: 'C-1：市场公允等效输出 token 成本（对标 InferenceX y_costh）；数据源 inferencex.semianalysis.com（每 7 天自动采集，见基准库页）；留空不启用双口径对标与亏损告警' },
      { path: 'pricing.fx_usd_cny', label: 'USD→CNY 汇率', unit: '', type: 'number', step: 0.1, min: 0, hint: 'S-3：仅用于「市场成本标杆」换算；默认 7.2，运行期可按实时汇率覆盖' },
    ],
  },
  {
    key: 'finance',
    label: '财务假设',
    fields: [
      { path: 'finance.T_horizon', label: '投资期', unit: '月', type: 'number', step: 1, min: 1 },
      { path: 'finance.r_w', label: '年化折现率', unit: '%', type: 'percent', step: 0.5, min: 0, max: 1, scale100: true },
      { path: 'finance.Tax', label: '税率', unit: '%', type: 'percent', step: 0.5, min: 0, max: 1, scale100: true },
      { path: 'finance.infl', label: '通胀率', unit: '%', type: 'percent', step: 0.5, min: 0, scale100: true },
      { path: 'finance.revenue_ramp', label: '收入爬坡', unit: '', type: 'switch' },
      { path: 'finance.debt_ratio', label: '债务占比', unit: '%', type: 'percent', step: 1, min: 0, max: 0.8, scale100: true, hint: '融资杠杆：debt = I0×占比，equity = I0×(1−占比)；默认 0 无融资' },
      { path: 'finance.debt_rate', label: '债务年利率', unit: '%/年', type: 'percent', step: 0.5, min: 0, max: 0.2, scale100: true, hint: '月利息 = 余额×年利率/12' },
      { path: 'finance.loan_term_months', label: '贷款期限', unit: '月', type: 'number', step: 1, min: 12, max: 240, hint: '直线摊销；末月结清余数；默认 = 折旧年限×12' },
    ],
  },
  {
    key: 'bench',
    label: '基准引用',
    fields: [
      { path: 'bench.gpu_id', label: 'GPU 基准', unit: '', type: 'text', hint: '由基准库下拉带入，存储 id' },
      { path: 'bench.model_id', label: '模型基准', unit: '', type: 'text' },
      { path: 'bench.cloud_id', label: '云价基准', unit: '', type: 'text' },
      { path: 'bench.api_id', label: 'API 基准', unit: '', type: 'text' },
    ],
  },
];

/** 从 ScenarioParams 读取值（Decimal/string/null/bool）→ 表单展示值。 */
export function readFieldValue(params: ScenarioParams, path: string): unknown {
  const [group, field] = path.split('.');
  const groupObj = params[group as keyof ScenarioParams] as unknown as Record<string, unknown>;
  return groupObj?.[field];
}

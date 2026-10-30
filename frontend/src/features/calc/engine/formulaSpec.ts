/**
 * 公式规格（Formula Spec）—— 前后端唯一事实来源。对齐后端 `app/calc/formula_spec.py`。
 * UI 的 ⓘ 抽屉直接渲染这里的公式与输入清单；前端内置一份用于离线可追溯。
 * 修改公式必须同步两端并更新 FORMULA_SPEC_VERSION。
 */

import { FORMULA_SPEC_VERSION } from './context';

export const GROUP_COST = 'cost_chain';
export const GROUP_REVENUE = 'revenue';
export const GROUP_BREAKEVEN = 'breakeven';
export const GROUP_FINANCE = 'finance';
export const GROUP_COMPARE = 'compare';

export interface FormulaDef {
  id: string;
  name: string;
  expr: string;
  inputs: string[];
  output: string;
  unit: string;
  group: string;
  note?: string;
}

export const FORMULAS: FormulaDef[] = [
  { id: 'F001', name: '整机 CAPEX', expr: 'CAPEX = N_gpu × P_gpu + P_aux', inputs: ['hw.N_gpu', 'hw.P_gpu', 'hw.P_aux'], output: 'CAPEX', unit: '元', group: GROUP_COST },
  { id: 'F002', name: '整机功耗', expr: 'P_sys = N_gpu × TDP / 1000 + P_aux_power', inputs: ['hw.N_gpu', 'power.TDP', 'power.P_aux_power'], output: 'P_sys', unit: 'kW/机', group: GROUP_COST, note: '若填写 P_sys_override 则以人工覆盖值为准。' },
  { id: 'F003', name: '折旧月摊销（非现金）', expr: 'Dep_m = CAPEX × (1 − S%) / (Y_dep × 12)', inputs: ['CAPEX', 'hw.S_pct', 'hw.Y_dep'], output: 'Dep_m', unit: '元/月', group: GROUP_COST, note: '折旧不进经营现金流，仅用于利润表与税盾。' },
  { id: 'F004', name: '月固定现金成本', expr: 'C_fix_cash = Co_loc + Co_net + Co_stor + Co_ops/12 + L_sw/12', inputs: ['power.Co_loc', 'power.Co_net', 'power.Co_stor', 'power.Co_ops', 'hw.L_sw'], output: 'C_fix_cash', unit: '元/月', group: GROUP_COST },
  { id: 'F005', name: '月固定会计成本', expr: 'C_fix_acct = C_fix_cash + Dep_m', inputs: ['C_fix_cash', 'Dep_m'], output: 'C_fix_acct', unit: '元/月', group: GROUP_COST },
  { id: 'F006', name: '每单位利用率月电费', expr: 'C_var_per_U = P_sys × PUE × E_price × H × (1−P_idle_ratio)；待机 C_idle_m = P_sys × PUE × E_price × H × P_idle_ratio', inputs: ['P_sys', 'power.PUE', 'power.E_price', 'power.P_idle_ratio'], output: 'C_var_per_U', unit: '元/月', group: GROUP_COST },
  { id: 'F007', name: '满负荷月产能', expr: 'Q_cap_M = T_eff × SEC / MTOK', inputs: ['perf.T_eff'], output: 'Q_cap_M', unit: 'Mtok/月', group: GROUP_COST },
  { id: 'F008', name: '等效折算系数 k', expr: 'k = T_dc / T_pf（优先实测/基准库/默认0.1）', inputs: ['perf.T_dc', 'perf.T_pf'], output: 'k', unit: '比率', group: GROUP_COST, note: '优先级：实测/录入 > 吞吐比 > 基准库 > 默认 0.1。' },
  { id: 'F009', name: '每百万 token 成本', expr: 'cost_per_m = (C_fix_acct + C_var_per_U·U) / (Q_cap_M·U)', inputs: ['C_fix_acct', 'C_var_per_U', 'U', 'Q_cap_M'], output: 'cost_per_m_capacity', unit: '元/Mtok', group: GROUP_COST },
  { id: 'F010', name: '实际月产出', expr: 'Q_out_M = Q_cap_M × U', inputs: ['Q_cap_M', 'U'], output: 'Q_out_M', unit: 'Mtok/月', group: GROUP_COST },
  { id: 'F011', name: '折算因子', expr: 'factor = 1 + k·rho·(1−h)', inputs: ['k', 'demand.rho', 'demand.h'], output: 'factor', unit: '比率', group: GROUP_COST },
  { id: 'F012', name: '月输出 token', expr: 'D_out = D_eq / factor', inputs: ['D_eq', 'factor'], output: 'D_out', unit: 'Mtok', group: GROUP_COST },
  { id: 'F020', name: '月输入 token', expr: 'D_in = rho × D_out', inputs: ['demand.rho', 'D_out'], output: 'D_in', unit: 'Mtok', group: GROUP_REVENUE },
  { id: 'F021', name: '等效单 token 单价', expr: 'p_eq = R / Q_eq', inputs: ['R', 'Q_eq'], output: 'p_eq', unit: '元/Mtok', group: GROUP_REVENUE },
  { id: 'F022', name: '月毛利与毛利率', expr: 'G = R − C_total；GM% = G / R', inputs: ['R', 'C_total'], output: 'G', unit: '元/月', group: GROUP_REVENUE },
  { id: 'F030', name: '单位贡献边际', expr: 'M_U = p_eq × Q_cap_M − C_var_per_U', inputs: ['p_eq', 'Q_cap_M', 'C_var_per_U'], output: 'M_U', unit: '元/月', group: GROUP_BREAKEVEN },
  { id: 'F031', name: '盈亏平衡利用率', expr: 'U_be = C_fix_acct / M_U', inputs: ['C_fix_acct', 'M_U'], output: 'U_be', unit: '比率', group: GROUP_BREAKEVEN, note: '分母 ≤0 时无解。' },
  { id: 'F032', name: '盈亏平衡产量', expr: 'Q_be = Q_cap_M × U_be', inputs: ['Q_cap_M', 'U_be'], output: 'Q_be', unit: 'Mtok/月', group: GROUP_BREAKEVEN },
  { id: 'F040', name: '期初投资', expr: 'I0 = CAPEX + 上线前费用', inputs: ['CAPEX', 'hw.pre_launch_cost'], output: 'I0', unit: '元', group: GROUP_FINANCE },
  { id: 'F041', name: '期末残值', expr: 'SV = CAPEX × S%', inputs: ['CAPEX', 'hw.S_pct'], output: 'SV', unit: '元', group: GROUP_FINANCE },
  { id: 'F042', name: '月折现率', expr: 'r_m = (1 + r_w)^(1/12) − 1', inputs: ['finance.r_w'], output: 'r_m', unit: '比率/月', group: GROUP_FINANCE },
  { id: 'F043', name: '净现值 NPV', expr: 'NPV = −I0 + Σ CF_t / (1+r_m)^t', inputs: ['I0', 'net_cf'], output: 'npv', unit: '元', group: GROUP_FINANCE },
  { id: 'F044', name: '总拥有成本 TCO', expr: 'TCO = CAPEX + Σ OPEX_cash', inputs: ['CAPEX', 'opex_cash'], output: 'tco', unit: '元', group: GROUP_FINANCE },
  { id: 'F045', name: '投资回报率 ROI', expr: 'ROI = (Σ CF_t − I0) / I0', inputs: ['net_cf', 'I0'], output: 'roi', unit: '比率', group: GROUP_FINANCE },
  { id: 'F046', name: '内部收益率 IRR', expr: 'IRR（年化）=(1+r_m)^12 − 1', inputs: ['irr_monthly'], output: 'irr', unit: '比率/年', group: GROUP_FINANCE },
  { id: 'F047', name: '回本期', expr: '静态：Σ CF_t 累计 ≥ I0 的期次；折现：累计折现 CF ≥ I0', inputs: ['cum_cf', 'cum_discounted_cf', 'I0'], output: 'payback', unit: '月', group: GROUP_FINANCE },
  { id: 'F050', name: '方案A 自建成本线', expr: 'C_A(Q) = C_fix_acct + (C_var_per_U/Q_cap_M)·Q', inputs: ['C_fix_acct', 'C_var_per_U', 'Q_cap_M'], output: 'a_A,b_A', unit: '元', group: GROUP_COMPARE },
  { id: 'F051', name: '方案B 租用成本线', expr: 'C_B(Q) = fixed + (Rent_gpu·N_gpu·H/Q_cap_M)·Q', inputs: ['pricing.Rent_gpu', 'hw.N_gpu', 'Q_cap_M'], output: 'a_B,b_B', unit: '元', group: GROUP_COMPARE },
  { id: 'F052', name: '方案C API 成本线', expr: 'C_C(Q) = (rho·((1−h)·API_in+h·API_cache)+API_out)/factor · Q', inputs: ['demand.rho', 'demand.h', 'API_in', 'API_cache', 'API_out', 'factor'], output: 'a_C,b_C', unit: '元', group: GROUP_COMPARE },
  { id: 'F053', name: '两两临界规模', expr: 'Q_XY = (a_X − a_Y) / (b_Y − b_X)', inputs: ['a_X', 'a_Y', 'b_X', 'b_Y'], output: 'Q_XY', unit: 'Mtok', group: GROUP_COMPARE },
  { id: 'F054', name: '下包络推荐区间', expr: '取三方案成本线最低段作为各需求区间的推荐方案', inputs: ['curves'], output: 'recommended', unit: '', group: GROUP_COMPARE },
  { id: 'F060', name: '敏感性龙卷风', expr: 'swing = |high − low|，按降序排列', inputs: ['param'], output: 'swing', unit: '比率', group: GROUP_COMPARE },
  // ---- 增量能力（F061–F066，对齐后端 formula_spec.py） ----
  { id: 'F061', name: '加权月电价（分时 TOU）', expr: 'weighted = e_price_valley·w_valley + e_price_flat·w_flat + e_price_peak·w_peak（w_flat=1−w_peak−w_valley）', inputs: ['power.e_price_valley', 'power.e_price_flat', 'power.e_price_peak', 'power.tou_valley_share', 'power.tou_peak_share'], output: 'weighted_e_price', unit: '元/kWh', group: GROUP_COST, note: '各档=E_price、峰谷占比=0 ⇒ weighted=E_price，退化为现状。' },
  { id: 'F062', name: '融资结构（债务杠杆）', expr: 'debt=I0·r；equity=I0·(1−r)；interest_t=bal·rate/12；principal_t=debt/L（直线摊销）', inputs: ['I0', 'finance.debt_ratio', 'finance.debt_rate', 'finance.loan_term_months'], output: 'debt,equity,interest_t,principal_t', unit: '元', group: GROUP_FINANCE, note: 'debt_ratio=0 ⇒ 无融资，权益 CF = 现状 CF；不影响 C(Q)/U_be。' },
  { id: 'F063', name: '权益现金流与杠杆指标', expr: 'equity_cf_0=−equity；equity_cf_t=R−OPEX−int−prin−tax；资产负债率=debt/I0；利息覆盖=EBIT/int；ROE=Σeq_cf/equity', inputs: ['equity', 'R', 'OPEX_cash', 'interest_t', 'principal_t', 'tax_t', 'EBIT_t'], output: '资产负债率,利息覆盖倍数,ROE,杠杆NPV,杠杆IRR', unit: '比率/元', group: GROUP_FINANCE, note: '杠杆后 NPV/IRR 即默认 npv/irr 在 debt_ratio>0 时的值；debt_ratio=0 退化为现状。' },
  { id: 'F064', name: '需求逐年增长', expr: 'D_t = D·(1+g_demand)^floor((t−1)/12)；R_t ∝ D_t；C_var_t ∝ D_t', inputs: ['D', 'demand.g_demand', 't'], output: 'D_t,revenue_t,opex_cash_t', unit: 'Mtok/月,元/月', group: GROUP_REVENUE, note: 'g_demand=0 ⇒ 恒量需求，退化为现状；crossover 推荐基于初始 D。' },
  { id: 'F065', name: '多因素联合敏感性', expr: '全因子网格 2^N → NPV 联合 min/max/分位数；S_i=|E[NPV|x_i=hi]−E[NPV|x_i=lo]|；I_ij=NPV(hi,hi)−NPV(hi,lo)−NPV(lo,hi)+NPV(lo,lo)', inputs: ['target', 'delta', 'vars'], output: 'joint_min, joint_max, percentiles, S_i, I_ij', unit: '同目标指标', group: GROUP_COMPARE, note: '确定性多因素边界与方差分解，非随机，与蒙特卡洛严格区分。' },
  { id: 'F066', name: '自定义情景集', expr: '任意 K 组参数覆盖 → evaluate_kpis 并列', inputs: ['specs', 'overrides'], output: 'custom_scenarios.cases[].kpis', unit: '同 KPI', group: GROUP_COMPARE, note: '突破保守/基准/乐观三档，K 任意；复用 evaluate_kpis。' },
  // ---- 电力运维口径（F093/F094 对齐后端 formula_spec.py） ----
  { id: 'F093', name: '机柜数（电力运维口径）', expr: 'racks = max(显式 racks, ceil(N_gpu / 32))', inputs: ['hw.N_gpu', 'power.racks'], output: 'racks', unit: '柜', group: GROUP_COST, note: '柜电分离/包柜包电共用；包柜包电时按此计机柜数。' },
  { id: 'F094', name: '包柜包电月成本', expr: 'bundle_rack_cost_m = bundle_monthly_per_rack × racks（包柜包电模式）；柜电分离=0', inputs: ['power.bundle_monthly_per_rack', 'power.racks'], output: 'bundle_rack_cost_m', unit: '元/月', group: GROUP_COST, note: '包柜包电模式：机柜+电费一口价，Co_loc 与按功耗核算的电费（idle+可变）剔除。' },
  // ---- 硬件反选（§3.13，F100/F101 对齐后端 formula_spec.py） ----
  { id: 'F100', name: '单卡有效吞吐估算', expr: 'T_card = REF_T_DC × perf_index × quant_mult × sla_scale', inputs: ['perf_index', 'quant', 'SLA_ttft', 'SLA_tpot'], output: 'T_card', unit: 'tok/s', group: GROUP_COMPARE, note: 'REF_T_DC=2000（H800/FP8 基准）；quant_mult 复用 QUANT_THROUGHPUT_MULT；sla_scale 复用 available_batch_limit 收缩比例（硬件反选，与正向吞吐同源）。' },
  { id: 'F101', name: '权重显存需求估算', expr: 'Mem_w ≈ M_param × bytes_per_param(quant) × 1.15', inputs: ['M_param', 'quant', 'Mem_w_override'], output: 'Mem_w', unit: 'GB', group: GROUP_COMPARE, note: '启发式估算（KV cache/框架开销系数 1.15），可被 Mem_w_override 覆盖，不进黄金向量主链。' },
  // ---- P0 管理驾驶舱 / P1 SLA 与递延收入 / P2 学习曲线（补全 dangling 定义，对齐后端 formula_spec.py） ----
  { id: 'F071', name: '每卡每天收入', expr: 'R / (N_gpu × 30)', inputs: ['R', 'hw.N_gpu'], output: 'rev_per_gpu_day', unit: '元/卡/天', group: GROUP_REVENUE, note: '管理驾驶舱单卡效能指标；分母为自然月 30 天（与 H=720 常量同源）。' },
  { id: 'F072', name: '每卡每天成本(全)', expr: 'C_total / (N_gpu × 30)', inputs: ['C_total', 'hw.N_gpu'], output: 'cost_per_gpu_day', unit: '元/卡/天', group: GROUP_COST, note: '全成本口径（含折旧与固定成本摊销），与 F071 配对解读单卡经济性。' },
  { id: 'F073', name: '每度电产出 Token', expr: 'Q_out_M × 10^6 / (P_eff(U) × PUE × 720)；P_eff(U)=P_sys·(P_idle_ratio + U·(1−P_idle_ratio))', inputs: ['Q_out_M', 'P_sys', 'power.PUE', 'demand.U', 'power.P_idle_ratio'], output: 'token_per_kwh', unit: 'Token/度', group: GROUP_COST, note: '能效指标；待机功耗计入分母（P2 负载曲线），月耗电 = P_eff×PUE×720h。' },
  { id: 'F081', name: 'SLA 赔偿计提', expr: '月计提 = R × SLA_penalty_rate；全周期 = Σ_t R_t × SLA_penalty_rate', inputs: ['R', 'perf.SLA_penalty_rate'], output: 'sla_provision_monthly, sla_provision_total', unit: '元/月,元', group: GROUP_REVENUE, note: 'P1 SLA 风险拨备，计入现金流 opex_cash（真金白银），影响 EBIT/税/NPV/IRR。' },
  { id: 'F082', name: '资源包递延收入链路', expr: '合同负债(初始)=pkg_prepaid；每月确认=pkg_prepaid/pkg_consume_months；期末合同负债=pkg_prepaid×max(0, 1−T_horizon/pkg_consume_months)；未确认占比=同期末比例；现金跑道=pkg_prepaid/R', inputs: ['pricing.pkg_prepaid', 'pricing.pkg_consume_months', 'pricing.pkg_tokens', 'finance.T_horizon', 'R'], output: 'deferred_revenue, rev_recognized_monthly, deferred_revenue_end, unearned_share, cash_prepaid, monthly_consumption, prepaid_cash_months', unit: '元,元/月,元,比率,元,Mtok/月,月', group: GROUP_REVENUE, note: 'P1 报告型字段：不改写核心现金流，仅量化预收费→消耗→确认链路。' },
  { id: 'F091', name: '待机功耗固定成本(月)', expr: 'C_power_idle_m = P_sys × PUE × weighted_e_price × 720 × P_idle_ratio（包柜包电=0）', inputs: ['P_sys', 'power.PUE', 'weighted_e_price', 'power.P_idle_ratio'], output: 'C_power_idle_m', unit: '元/月', group: GROUP_COST, note: 'P2 负载曲线：idle floor 固定功耗成本；P_idle_ratio=0 时退化为 0（零回归）。' },
  { id: 'F092', name: '学习曲线期末系数', expr: '(1 − cost_learning_rate)^(T_horizon/12)', inputs: ['finance.cost_learning_rate', 'finance.T_horizon'], output: 'learning_terminal_factor', unit: '比率', group: GROUP_COST, note: 'P2 学习曲线：单位可变成本随时间缩放因子的期末值；rate=0 时为 1（零回归）。' },
];

const INDEX: Record<string, FormulaDef> = {};
for (const f of FORMULAS) INDEX[f.id] = f;

export function specAsDict(): { version: string; formulas: FormulaDef[] } {
  return { version: FORMULA_SPEC_VERSION, formulas: FORMULAS };
}

export function getFormula(id: string): FormulaDef {
  const formula = INDEX[id.toUpperCase()];
  if (!formula) throw new Error(`未知公式 id：${id}`);
  return formula;
}

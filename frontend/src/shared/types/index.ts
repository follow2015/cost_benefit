/**
 * 前端 DTO 类型定义。与后端 `app/schemas/*` 逐字段对齐。
 * 约定：所有数值字段在 JSON 中均为字符串（Decimal 直出），前端用 `Decimal` 重新解释。
 */

import type { Decimal } from '@/features/calc/engine/decimalConfig';

/** 统一响应体 `{code,message,data}`。 */
export interface ApiResponse<T> {
  code: string;
  message: string;
  data: T | null;
}

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
}

export interface PageResponse<T> {
  items: T[];
  meta: PageMeta;
}

/** 计算选项（与后端 CalcOptionsIn 对齐）。 */
export interface CalcOptions {
  include_sensitivity: boolean;
  include_scenarios: boolean;
  include_crossover: boolean;
  sensitivity_target: 'npv' | 'cost_per_m' | 'cost_advantage';
  sensitivity_delta: string;
  // ---- 增量能力（默认关闭） ----
  include_joint?: boolean;
  joint_target?: 'npv' | 'cost_per_m' | 'cost_advantage';
  joint_delta?: string;
  joint_vars?: string[] | null;
  include_custom_scenarios?: boolean;
  custom_scenario_specs?: CustomScenarioSpecDTO[] | null;
}

/** 自定义情景定义 DTO（覆盖式，Decimal 为字符串）。 */
export interface CustomScenarioSpecDTO {
  key: string;
  label: string;
  overrides: Record<string, string>;
}

/** 计算请求。 */
export interface CalcRequest {
  scenario_id?: number | null;
  params?: Record<string, unknown> | null;
  options?: Partial<CalcOptions>;
  persist?: boolean;
  client_kpis?: Record<string, string> | null;
}

/** 计算结果载荷（与后端 `compute_all` 同构；Decimal 全部为字符串）。 */
export interface CalcPayload {
  engine_version: string;
  formula_spec_version: string;
  authoritative: boolean;
  conventions: Record<string, unknown>;
  params: Record<string, unknown>;
  derived: Record<string, unknown>;
  throughput: Record<string, unknown>;
  unit_cost: Record<string, unknown>;
  revenue: Record<string, unknown>;
  breakeven: Record<string, unknown>;
  cost_models: CostModelEntry[];
  crossover: CrossoverPayload | null;
  financials: FinancialsPayload;
  sensitivity: SensitivityPayload | null;
  scenarios: ScenarioSetPayload | null;
  joint?: JointSensitivityPayload | null;
  custom_scenarios?: CustomScenarioSetPayload | null;
  kpis: Kpi[];
  warnings: string[];
  disclaimer: string;
}

export interface CostModelEntry {
  plan: string;
  label: string;
  a: string;
  b: string;
  cost_at_demand: string;
  unit_cost_at_demand: string;
}

export interface Kpi {
  key: string;
  label: string;
  value: string | null;
  unit: string;
  formula_id: string;
  kind: string;
  /** P3-3 推荐方案可行性分级：viable | loss | no_demand | no_solution（仅 recommended_plan 使用） */
  status?: string;
  /** P3-3 推荐方案分级说明文案（仅 recommended_plan 使用） */
  note?: string;
}

export interface FinancialsPayload {
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
  irr: {
    solution: string;
    irr_monthly: string | null;
    irr_annual: string | null;
    roots_monthly: (string | null)[];
    mirr_monthly: string | null;
    mirr_annual: string | null;
    method: string;
    note: string;
    iterations: number;
  };
  financing: FinancingPayload;
  cashflows: CashflowRow[];
  cashflows_yearly: CashflowRow[];
  notes: string[];
}

export interface FinancingPayload {
  debt_ratio: string;
  debt: string;
  equity: string;
  interest_total: string;
  principal_total: string;
  interest_coverage: string | null;
  roe: string;
  levered_npv: string;
  levered_irr: string | null;
}

export interface CashflowRow {
  period: number;
  period_type: string;
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
  discount_ratio: string;
  discounted_cf: string;
  cum_discounted_cf: string;
}

export interface CrossoverPayload {
  curves: {
    plan: string;
    label: string;
    a: string;
    b: string;
    points: { Q: string; total_cost: string; unit_cost: string }[];
  }[];
  crossovers: {
    plans: string[];
    Q: string | null;
    active: boolean;
    status: string;
    note: string;
  }[];
  recommended: {
    from_Q: string;
    to_Q: string | null;
    best_plan: string;
    best_label: string;
  }[];
  q_max: string;
  capacity_wall: string | null;
  notes: string[];
}

export interface SensitivityPayload {
  target: string;
  target_label: string;
  delta: string;
  base: string | null;
  items: SensitivityItem[];
  notes: string[];
}

export interface SensitivityItem {
  param: string;
  label: string;
  base: string;
  low: string;
  high: string;
  delta_low: string;
  delta_high: string;
  swing: string;
  swing_pct: string;
  low_feasible: boolean;
  high_feasible: boolean;
  note: string;
}

export interface ScenarioSetPayload {
  cases: {
    key: string;
    label: string;
    multipliers: Record<string, string>;
    kpis: Kpi[];
    feasible: boolean;
    note: string;
  }[];
  notes: string[];
}

/** 多因素联合敏感性（确定性网格 + 方差分解）。 */
export interface JointSensitivityPayload {
  npv_min: string;
  npv_max: string;
  percentiles: Record<string, string>;
  main_effects: Record<string, string>;
  interactions: Record<string, string>;
  notes: string[];
}

/** 自定义情景集（任意 K 组参数覆盖并列 KPI）。 */
export interface CustomScenarioSetPayload {
  cases: {
    key: string;
    label: string;
    overrides: Record<string, string>;
    kpis: Kpi[];
    feasible: boolean;
    note: string;
  }[];
  notes: string[];
}

/** 计算结果响应。 */
export interface CalcResultOut {
  id: number | null;
  scenario_id: number | null;
  scenario_version: number;
  engine_version: string;
  formula_spec_version: string;
  params_hash: string;
  duration_ms: number | null;
  payload: CalcPayload;
  client_deviation: string | null;
  created_at: string | null;
}

export interface CalcSummaryOut {
  id: number;
  scenario_id: number | null;
  scenario_name: string;
  kpi_summary: Record<string, unknown>;
  engine_version: string;
  created_at: string;
}

export interface CompareRequest {
  scenario_ids: number[];
  options?: Partial<CalcOptions>;
}

export interface CompareItem {
  scenario_id: number;
  scenario_name: string;
  kpis: Kpi[];
  kpi_map: Record<string, unknown>;
  warnings: string[];
}

export interface CompareMeta {
  key: string;
  label: string;
  unit: string;
  kind: string;
  formula_id: string;
}

export interface CompareResponse {
  items: CompareItem[];
  kpi_meta: CompareMeta[];
}

/** 方案 DTO。 */
export interface ScenarioListItem {
  id: number;
  name: string;
  description: string;
  status: string;
  version: number;
  tags: string[];
  is_template: boolean;
  conventions: Record<string, unknown>;
  latest_kpi: Record<string, unknown> | null;
  latest_result_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ScenarioDetail {
  id: number;
  name: string;
  description: string;
  status: string;
  version: number;
  tags: string[];
  is_template: boolean;
  params: Record<string, unknown>;
  conventions: Record<string, unknown>;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface SnapshotOut {
  id: number;
  version: number;
  note: string;
  diff: Record<string, unknown>;
  created_by: number | null;
  created_at: string;
}

export interface ScenarioCreate {
  name: string;
  description?: string;
  params?: Record<string, unknown>;
  tags?: string[];
  is_template?: boolean;
}

export interface ScenarioUpdate {
  name?: string;
  description?: string;
  params?: Record<string, unknown>;
  tags?: string[];
  status?: string;
  note?: string;
}

/** 鉴权 DTO。 */
export interface LoginRequest {
  email: string;
  password: string;
  tenant_slug?: string | null;
}

export interface TenantBrief {
  id: number;
  name: string;
  slug: string;
}

export interface UserOut {
  id: number;
  email: string;
  display_name: string;
  role: string;
  permissions: string[];
  is_super: boolean;
  is_active: boolean;
  tenant: TenantBrief | null;
  last_login_at: string | null;
}

export interface MemberCreateIn {
  email: string;
  password: string;
  display_name?: string;
  role: string;
}

export interface MemberUpdateIn {
  display_name?: string | null;
  role?: string | null;
  is_active?: boolean | null;
  password?: string | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: UserOut;
}

/** 基准库 DTO（数值均为字符串）。 */
export interface GpuBench {
  id: number;
  code: string;
  name: string;
  vendor: string;
  price_cny: string;
  tdp_w: string;
  vram_gb: string;
  rent_cny_per_hour: string | null;
  meta: Record<string, unknown>;
  source: string;
  as_of: string | null;
  is_builtin: boolean;
}

export interface ModelBench {
  id: number;
  code: string;
  name: string;
  params_b: string;
  throughput_prefill: string | null;
  throughput_decode: string | null;
  throughput_effective: string | null;
  k_ratio: string | null;
  vram_required_gb: string;
  meta: Record<string, unknown>;
  source: string;
  as_of: string | null;
  is_builtin: boolean;
}

export interface CloudPriceBench {
  id: number;
  provider: string;
  gpu_code: string;
  region: string;
  price_cny_per_hour: string;
  include_power: boolean;
  include_hosting: boolean;
  billing_mode: string;
  rent_inc: string;
  meta: Record<string, unknown>;
  source: string;
  as_of: string | null;
  is_builtin: boolean;
}

export interface ApiPriceBench {
  id: number;
  provider: string;
  model_code: string;
  price_in_cny_per_m: string;
  price_out_cny_per_m: string;
  price_cache_cny_per_m: string | null;
  meta: Record<string, unknown>;
  source: string;
  as_of: string | null;
  is_builtin: boolean;
}

export interface BenchmarkBundle {
  gpus: GpuBench[];
  models: ModelBench[];
  cloud_prices: CloudPriceBench[];
  api_prices: ApiPriceBench[];
}

/** 无实体返回占位（删除等）。 */
export interface OkData {
  ok: boolean;
  detail?: unknown;
}

/** 基准种类（路由段）。 */
export type BenchKind = 'gpus' | 'models' | 'cloud-prices' | 'api-prices';

/** 四类基准的写入字段（数值均为字符串；更新时全部可选）。 */
export interface GpuFields {
  code?: string;
  name?: string;
  vendor?: string;
  price_cny?: string;
  tdp_w?: string;
  vram_gb?: string;
  rent_cny_per_hour?: string | null;
  source?: string;
  as_of?: string | null;
  is_builtin?: boolean;
  is_active?: boolean;
}
export interface ModelFields {
  code?: string;
  name?: string;
  params_b?: string;
  throughput_prefill?: string | null;
  throughput_decode?: string | null;
  throughput_effective?: string | null;
  k_ratio?: string | null;
  vram_required_gb?: string;
  source?: string;
  as_of?: string | null;
  is_builtin?: boolean;
  is_active?: boolean;
}
export interface CloudPriceFields {
  provider?: string;
  gpu_code?: string;
  region?: string;
  price_cny_per_hour?: string;
  include_power?: boolean;
  include_hosting?: boolean;
  billing_mode?: string;
  source?: string;
  as_of?: string | null;
  is_builtin?: boolean;
  is_active?: boolean;
}
export interface ApiPriceFields {
  provider?: string;
  model_code?: string;
  price_in_cny_per_m?: string;
  price_out_cny_per_m?: string;
  price_cache_cny_per_m?: string | null;
  source?: string;
  as_of?: string | null;
  is_builtin?: boolean;
  is_active?: boolean;
}
export type BenchRow = GpuBench | ModelBench | CloudPriceBench | ApiPriceBench;

/** 审计条目（含动作中文标签）。 */
export interface AuditEntry {
  id: number;
  action: string;
  action_label: string;
  actor_email: string;
  target_type: string;
  target_id: number | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

/** 公式条目（ⓘ 追溯抽屉）。 */
export interface FormulaOut {
  id: string;
  name: string;
  expression: string;
  inputs: string[];
  unit: string;
  note: string;
  group: string;
}

/** 计算偏差日志条目（前端内部）。 */
export interface DeviationLog {
  timestamp: string;
  maxRelative: number;
  maxAt: string;
  duration_ms: number;
  passed: boolean;
}

// ===========================================================================
// §3.13 硬件反选推荐
// ===========================================================================
export interface HardwareGpuSpec {
  id: string;
  name: string;
  vendor: string;
  mem_gb: string;
  tdp_w: string;
  price_per_card: string;
  perf_index: string;
  max_cards_per_node: string;
  domestic: boolean;
  supported_quant: string[];
  notes: string;
}

export interface HardwareCandidateDto {
  gpu: HardwareGpuSpec;
  N_gpu: string;
  feasible: boolean;
  T_eff_achieved: string;
  mem_required_gb: string;
  capex: string;
  power_kw: string;
  over_budget: boolean;
  score: string;
  /** 完整 ScenarioParams（Decimal 为字符串），前端「一键应用」回填表单用。 */
  params: Record<string, unknown> | null;
  kpis: {
    npv: string | null;
    tco: string | null;
    cost_per_m: string | null;
    payback_static: string | null;
    recommended_plan_at_capacity: string | null;
  };
  assumptions: string[];
  warnings: string[];
  // ---- §3.13 完整建模：配套存储/组网 ----
  node_count: number;
  supporting_capex: string;
  supporting_power_kw: string;
  storage: {
    capacity_gb: string;
    weights_gb: string;
    kv_cache_gb: string;
    dataset_gb: string;
    log_snapshot_gb: string;
    capex: string;
    monthly: string;
    power_kw: string;
  } | null;
  network: {
    node_count: number;
    fabric: string;
    port_speed_gbps: string;
    switches: number;
    storage_switch_qty: number;
    mgmt_switch_qty: number;
    nic_qty: number;
    optics_400g_qty: number;
    optics_100g_qty: number;
    aoc_qty: number;
    mpo_qty: number;
    capex: string;
    monthly: string;
    power_kw: string;
    interconnect_loss: string;
  } | null;
  /** BOM 清单（方案确定后硬件配置明细）：服务器/算力·存储·管理交换机/线缆/存储。 */
  hardware_bom: HardwareBom | null;
}

/** BOM 单项（单价 × 数量）。 */
export interface BomItem {
  unit_price: string;
  unit: string;
  qty: number;
  fabric?: string;
}

/** 硬件 BOM 清单（方案确定后展示）。 */
export interface HardwareBom {
  gpu: { id: string; name: string; vendor: string };
  servers: {
    name: string;
    cards_per_node: number;
    node_count: number;
    unit_price: string;
    qty: number;
    subtotal: string;
  };
  compute_switch: BomItem;
  storage_switch: BomItem;
  mgmt_switch: BomItem;
  nic: BomItem;
  optics_400g: BomItem;
  optics_100g: BomItem;
  aoc: BomItem;
  mpo: BomItem;
  storage: {
    capacity_gb: string;
    unit_price_gb: string;
    capex: string;
    monthly_per_gb: string;
    monthly: string;
  };
  total_supporting_capex: string;
}

export interface HardwareRecommendIn {
  T_eff_target?: string | null;
  D_eq_target?: string | null;
  U_target?: string;
  growth_headroom?: string;
  M_param?: string;
  quant?: string;
  Ctx?: string | null;
  Mem_w_override?: string | null;
  SLA_ttft?: string | null;
  SLA_tpot?: string | null;
  CN_cfg?: string;
  capex_budget?: string | null;
  power_budget_kw?: string | null;
  objective?: string;
  fabric?: string;
  extra_nodes?: number;
  port_speed?: number | null;
  spine_port_speed?: number | null;
  model_code?: string | null;
  base_params?: Record<string, unknown> | null;
  top_n?: number;
}

export interface HardwareRecommendResult {
  target_tok_s: string;
  mem_required_gb: string;
  candidates: HardwareCandidateDto[];
  recommended: HardwareCandidateDto[];
  notes: string[];
}

export type { Decimal };

/** 组网配套目录（配件库）条目。 */
export interface NetworkCatalogItem {
  id: number;
  category: string;
  code: string;
  name: string;
  price_cny: string;
  unit: string;
  spec: NetworkCatalogSpec;
  source: string;
  as_of: string | null;
  version: number;
  is_active: boolean;
  is_builtin: boolean;
}

/** 配件库规格（驱动拓扑推导；仅交换机类目用 ports/speed）。 */
export interface NetworkCatalogSpec {
  ports?: number; // 交换机端口数（如 MQM9790=64）
  speed?: number; // 交换机端口速率（Gbps，如 400）
  [key: string]: unknown;
}

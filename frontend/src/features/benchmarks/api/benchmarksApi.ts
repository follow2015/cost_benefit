/** 基准库 API（P0 只读 + P1 写入）。 */
import { del, get, post, put } from '@/shared/api/client';
import type { BenchKind, BenchmarkBundle, BenchRow, OkData } from '@/shared/types';

export function getBundle(): Promise<BenchmarkBundle> {
  return get<BenchmarkBundle>('/benchmarks');
}

const PATHS: Record<BenchKind, string> = {
  gpus: '/benchmarks/gpus',
  models: '/benchmarks/models',
  'cloud-prices': '/benchmarks/cloud-prices',
  'api-prices': '/benchmarks/api-prices',
};

/** 新增一条基准（需 benchmark:write 权限）。 */
export function createBenchmark(kind: BenchKind, payload: Record<string, unknown>): Promise<BenchRow> {
  return post<BenchRow>(PATHS[kind], payload);
}

/** 更新一条基准（仅提交字段生效，版本号自增）。 */
export function updateBenchmark(
  kind: BenchKind,
  id: number,
  payload: Record<string, unknown>,
): Promise<BenchRow> {
  return put<BenchRow>(`${PATHS[kind]}/${id}`, payload);
}

/** 删除一条基准。 */
export function deleteBenchmark(kind: BenchKind, id: number): Promise<OkData> {
  return del<OkData>(`${PATHS[kind]}/${id}`);
}

/** S-3 成本标杆解析响应（只读；数据闭环可视化用）。 */
export interface CostBenchmarkResp {
  found: boolean;
  model_code: string;
  hardware_code: string;
  scenario: string;
  cost_benchmark_cny_per_mtok: string | null;
  currency: string;
  fx_usd_cny?: string;
  source?: string;
  message?: string;
}

/** S-3 只读：按「模型×硬件×场景」解析 InferenceX 市场成本标杆（元/Mtok）。
 *
 * `fx` 缺省不传，由后端按统一汇率口径（settings.FX_USD_CNY）折算——
 * 前端不再硬编码汇率，避免出现第三份口径。
 */
export function getCostBenchmark(params: {
  model_code: string;
  hardware_code: string;
  scenario?: string;
  fx?: string;
}): Promise<CostBenchmarkResp> {
  const query: Record<string, string> = {
    model_code: params.model_code,
    hardware_code: params.hardware_code,
    scenario: params.scenario ?? 'AgentX',
  };
  if (params.fx) query.fx = params.fx;
  return get<CostBenchmarkResp>('/benchmarks/cost-benchmark', query);
}

// --------------------------------------------------------------------------- 版本发布 / 回滚
export interface PublishSummary {
  publish_id: number;
  published_at: string | null;
  actor_email: string;
  counts: Record<string, number>;
}

export interface PublishResult {
  publish_id: number;
  counts: Record<string, number>;
}

export interface RollbackItem {
  kind: string;
  id: number;
  code: string;
  fields: string[];
  from_version: number;
  to_version: number;
}

export interface RollbackResult {
  source_publish_id: number;
  updated: RollbackItem[];
  unchanged: number;
  skipped: Array<{ kind: string; id: number; code: string; reason: string }>;
}

/** 发布当前基准库版本（冻结全量快照，供后续回滚）。 */
export function publishBenchmarks(): Promise<PublishResult> {
  return post<PublishResult>('/benchmarks/publish', {});
}

/** 发布历史（倒序，不含快照正文）。 */
export function listPublishes(limit = 20): Promise<PublishSummary[]> {
  return get<PublishSummary[]>('/benchmarks/publishes', { limit });
}

/** 回滚到指定发布版本（只提交差异字段，行版本自增）。 */
export function rollbackPublish(publishId: number): Promise<RollbackResult> {
  return post<RollbackResult>(`/benchmarks/publishes/${publishId}/rollback`, {});
}

// --------------------------------------------------------------- InferenceX 自动采集
/** 一次采集的结果（后端 `POST /benchmarks/sync` 的 data）。 */
export interface SyncOutcome {
  status: 'running' | 'success' | 'partial' | 'failed' | 'skipped';
  trigger: 'manual' | 'scheduled';
  started_at: string | null;
  finished_at: string | null;
  /** 数据生效日（上游证据日期，缺则取采集日） */
  as_of: string | null;
  model_count: number;
  platform_count: number;
  point_count: number;
  matched_count: number;
  added: number;
  updated: number;
  unchanged: number;
  skipped: number;
  error: string;
  /** 上游有、基准库无同名 code 的模型（未写入） */
  unmatched: string[];
  warnings: string[];
  run_id: number | null;
  endpoint: string;
  next_run_at: string | null;
}

export interface SyncRunBrief {
  id: number;
  status: SyncOutcome['status'];
  trigger: string;
  started_at: string | null;
  finished_at: string | null;
  as_of: string | null;
  point_count: number;
  matched_count: number;
  added: number;
  updated: number;
  error: string;
}

/** 采集状态总览（数据源、周期、上次结果、下次计划）。 */
export interface SyncStatus {
  source: string;
  source_name: string;
  /** 数据源站点（前端「数据来源」链接用） */
  source_url: string;
  endpoint: string;
  interval_days: number;
  fx_usd_cny: string;
  due: boolean;
  next_run_at: string | null;
  last: SyncRunBrief | null;
  last_success: SyncRunBrief | null;
  recent: SyncRunBrief[];
}

/** 采集状态（无需写权限，页面加载即调）。 */
export function getSyncStatus(): Promise<SyncStatus> {
  return get<SyncStatus>('/benchmarks/sync-status');
}

/** 手动触发一次采集（强制，忽略周期；需 benchmark:write 权限）。 */
export function syncInferencex(): Promise<SyncOutcome> {
  return post<SyncOutcome>('/benchmarks/sync', {});
}

// ------------------------------------------------------------- 权威同步（多源投票）
export type AuthorityVerdict = 'consensus' | 'single_source' | 'conflict' | 'no_data';

export interface AuthorityObservation {
  source: string;
  url: string;
  usd_in: string;
  usd_out: string | null;
  usd_cache: string | null;
  context: number | null;
}

export interface AuthorityItem {
  id: number;
  kind: string;
  provider: string;
  model_code: string;
  current: {
    in_cny: string;
    out_cny: string;
    cache_cny: string | null;
    as_of: string | null;
    source: string;
    version: number;
  };
  verdict: AuthorityVerdict;
  confidence: 'high' | 'medium' | 'low';
  /** 多源一致才允许自动应用 */
  applicable: boolean;
  /** 单源 / 冲突：需人工确认后应用 */
  needs_review: boolean;
  /** 部分维度可采信：整条不能自动应用，但有一项是确定的 */
  partial: boolean;
  /** 输入价 / 输出价分别投票的结论（一侧分歧不连累另一侧） */
  input_verdict: AuthorityVerdict;
  output_verdict: AuthorityVerdict;
  input_verdict_label: string;
  output_verdict_label: string;
  input_agreeing: string[];
  output_agreeing: string[];
  /** 权威值与库内值实质相同（差异只来自折算汇率口径），默认不必勾选 */
  settled: boolean;
  agreement_ratio: number;
  proposed: {
    in_cny: string | null;
    out_cny: string | null;
    /** 采信值（USD / 百万 token），应用时直接提交此值，避免 CNY 反算误差 */
    usd_in: string | null;
    usd_out: string | null;
    usd_cache: string | null;
  };
  change: string;
  observations: AuthorityObservation[];
}

export interface AuthorityFx {
  current: string;
  authoritative: string | null;
  change: string;
  drifted: boolean;
  verdict: AuthorityVerdict;
  confidence: string;
  observations: Array<{ source: string; url: string; value: string }>;
}

export interface AuthorityPreview {
  fx: AuthorityFx;
  summary: Record<string, number>;
  sources: Array<{
    source: string;
    url: string;
    ok: boolean;
    entries: number;
    ambiguous: number;
    error: string | null;
  }>;
  fetched_at: string | null;
  items: AuthorityItem[];
}

export interface AuthorityApplyItem {
  id: number;
  usd_in: string;
  usd_out?: string | null;
  usd_cache?: string | null;
  source_label?: string;
}

export interface AuthorityApplyResult {
  applied: Array<{
    id: number;
    provider: string;
    model_code: string;
    before: Record<string, unknown>;
    after: Record<string, unknown>;
  }>;
  skipped: Array<{ id: number | null; reason: string }>;
  fx_usd_cny: string;
  applied_count: number;
}

/** 权威同步现状（纯读库，即时返回）。 */
export interface AuthorityStatus {
  /** 当前折算口径 */
  fx_usd_cny: string;
  total: number;
  /** 来源为 authority:* 的条数（即已同步过权威价） */
  from_authority: number;
  /** 仍为人工/历史录入的条数 */
  manual: number;
  last_synced_at: string | null;
  as_of: string | null;
  sources: Array<{ source: string; label: string; url: string }>;
}

/** 拉取三源权威数据并与库内比对（只读，不写库）。 */
export function previewAuthority(): Promise<AuthorityPreview> {
  return get<AuthorityPreview>('/benchmarks/authority-preview');
}

/** 权威同步现状（不触发外网请求，可直接跟随页面加载）。 */
export function getAuthorityStatus(): Promise<AuthorityStatus> {
  return get<AuthorityStatus>('/benchmarks/authority-status');
}

/** 应用用户确认的权威价（USD/Mtok；需 benchmark:write 权限）。 */
export function applyAuthority(
  items: AuthorityApplyItem[],
  fxUsdCny?: string,
): Promise<AuthorityApplyResult> {
  return post<AuthorityApplyResult>('/benchmarks/authority-apply', {
    items,
    fx_usd_cny: fxUsdCny,
  });
}

// ---------------------------------------------------------------- 租赁价采集
/** 租赁价采集链路：GPU 行情 / 云厂商官价。 */
export type MarketKind = 'gpu-rental' | 'cloud-official';

/** 一条「现网值 → 采集值」的比对。 */
export interface MarketItem {
  kind: MarketKind;
  id: number;
  /** 人读标签：`H100` / `Azure · H100` */
  label: string;
  current_cny: string | null;
  proposed_cny: string | null;
  current_source: string;
  /** 上游证据日期（行情周 / 采集日） */
  as_of: string | null;
  /** 已格式化变动，如 `-11.16%`；无法计算时为 null */
  change: string | null;
  direction: 'up' | 'down' | 'settled' | 'new';
  /** 变动在汇率噪声范围内（≤0.5%） */
  settled: boolean;
  /** 补充说明，如 `仅 1 家云报价` / `8 卡整机折算` */
  note: string;
}

export interface MarketPreview {
  kind: MarketKind;
  label: string;
  summary: {
    total: number;
    up: number;
    down: number;
    settled: number;
    /** 库里有该行但上游本次没数据 */
    missing: number;
    /** 根本没有公开数据源，只能人工维护 */
    manual_only: number;
  };
  items: MarketItem[];
  /** 库内有行、上游本次缺数据 */
  missing: string[];
  /** 没有公开数据源（国产卡 / 国内云） */
  manual_only: string[];
  /** 上游有、库里没建行 */
  unmatched: string[];
  /** 部分数据源失败时的说明（另一源成功仍可预览） */
  warnings: string[];
  as_of: string | null;
  fx_usd_cny: string;
  source_name: string;
  source_url: string;
}

export interface MarketApplyItem {
  id: number;
  proposed_cny: string;
  as_of?: string | null;
  meta?: Record<string, unknown>;
}

export interface MarketApplyResult {
  kind: MarketKind;
  applied: Array<{
    id: number;
    before: Record<string, unknown>;
    after: Record<string, unknown>;
  }>;
  skipped: Array<{ id: number; reason: string }>;
}

/** 拉取外部价格并与库内比对（只读，不写库）。 */
export function previewMarket(kind: MarketKind): Promise<MarketPreview> {
  return get<MarketPreview>(`/benchmarks/market-preview?kind=${kind}`);
}

/** 应用人工确认的租赁价（需 benchmark:write 权限）。 */
export function applyMarket(
  kind: MarketKind,
  items: MarketApplyItem[],
): Promise<MarketApplyResult> {
  return post<MarketApplyResult>(`/benchmarks/market-apply?kind=${kind}`, { items });
}

/** 两条租赁价链路的覆盖率（纯读库，可跟随页面加载）。 */
export interface SyncOverview {
  gpu_rental: {
    kind: MarketKind;
    total: number;
    from_source: number;
    auto_capable: number;
    no_market: string[];
  };
  cloud_official: {
    kind: MarketKind;
    total: number;
    from_source: number;
    auto_capable: number;
  };
}

export function getSyncOverview(): Promise<SyncOverview> {
  return get<SyncOverview>('/benchmarks/sync-overview');
}

// ---------------------------------------------------------------- 模型采集覆盖
/** 一条模型基准行的采集覆盖判决。
 *
 * `no_value`（上游在测、本次没给值）与 `untested`（上游压根不测）后果完全不同：
 * 前者等下一轮，后者只能人工维护，所以界面上必须分开显示。
 */
export type CoverageStatus = 'covered' | 'no_value' | 'untested' | 'unknown';

export interface ModelCoverageRow {
  code: string;
  status: CoverageStatus;
  /** 后端给的中文标签（`已采到` / `上游无值` / `上游不测` / `未采集`） */
  label: string;
  /** 上游对应的模型名，便于核对版本是否对岔 */
  slug: string;
  /** 人话原因，直接进 tooltip */
  detail: string;
}

export interface ModelCoverage {
  as_of: string | null;
  run_id: number | null;
  upstream: {
    model_count: number;
    with_value: number;
    /** 上游在测、本次却没有成本值的模型名 */
    without_value: string[];
    /** 上游测了、基准库没建行的模型 */
    unmatched: string[];
    models: Array<{ slug: string; code: string; point_count: number; scenarios: string[] }>;
  };
  /** 判据是否可用：旧采集记录没存上游清单时为 false */
  judgeable: boolean;
  summary: {
    total: number;
    covered: number;
    no_value: number;
    untested: number;
    unknown: number;
  };
  rows: ModelCoverageRow[];
}

export function getModelCoverage(): Promise<ModelCoverage> {
  return get<ModelCoverage>('/benchmarks/model-coverage');
}

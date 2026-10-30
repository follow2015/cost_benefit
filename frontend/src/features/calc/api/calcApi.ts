/** 计算相关 API（权威重算 / 无状态试算 / 多方案对比 / 公式）。 */
import { get, post } from '@/shared/api/client';
import type {
  CalcRequest,
  CalcResultOut,
  CalcPayload,
  CompareRequest,
  CompareResponse,
  FormulaOut,
  HardwareRecommendIn,
  HardwareRecommendResult,
} from '@/shared/types';

/** 权威计算（可落库）。 */
export function calculate(req: CalcRequest): Promise<CalcResultOut> {
  return post<CalcResultOut>('/calc', req);
}

/** 无状态试算（向导实时预览后端校验通道）。 */
export function preview(params: Record<string, unknown>, options?: Partial<CalcRequest['options']>): Promise<CalcPayload> {
  return post<CalcPayload>('/calc/preview', params, );
}

/** 多方案横向对比。 */
export function compare(req: CompareRequest): Promise<CompareResponse> {
  return post<CompareResponse>('/calc/compare', req);
}

/** 蒙特卡洛模拟（P2-4 / REQ-18）。返回 NPV/IRR 分布统计。 */
export function montecarlo(req: {
  scenario_id?: number | null;
  params?: Record<string, unknown> | null;
  n?: number;
  seed?: number | null;
}): Promise<Record<string, unknown>> {
  return post<Record<string, unknown>>('/calc/montecarlo', req);
}

/** 硬件反选推荐（§3.13）：按需求反推 GPU 配置并生成完整测算方案。 */
export function recommendHardware(req: HardwareRecommendIn): Promise<HardwareRecommendResult> {
  return post<HardwareRecommendResult>('/calc/recommend', req);
}

/** 读取历史计算结果。 */
export function getResult(resultId: number): Promise<CalcResultOut> {
  return get<CalcResultOut>(`/calc/results/${resultId}`);
}

/** 读取方案最近一次结果（结果页刷新直命中，免重算）。 */
export function latestResult(id: number): Promise<CalcResultOut> {
  return get<CalcResultOut>(`/calc/scenarios/${id}/latest`);
}

/** 方案历史结果摘要。 */
export function resultHistory(id: number, limit = 20): Promise<Record<string, unknown>[]> {
  return get<Record<string, unknown>[]>(`/calc/scenarios/${id}/history`, { limit });
}

/** 公式速查。 */
export function getFormula(id: string): Promise<FormulaOut> {
  return get<FormulaOut>(`/calc/formulas/${id}`);
}

export function listFormulas(): Promise<FormulaOut[]> {
  return get<FormulaOut[]>('/calc/formulas');
}

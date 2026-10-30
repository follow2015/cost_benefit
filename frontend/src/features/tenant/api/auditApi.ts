/** 审计日志 API（P1 REQ-16）。 */
import { get } from '@/shared/api/client';
import type { AuditEntry } from '@/shared/types';

export function listAudit(params: { scenario_id?: number; limit?: number }): Promise<AuditEntry[]> {
  return get<AuditEntry[]>('/audit', params);
}

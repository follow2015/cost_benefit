/** 批量导入 API（P2-2 + 智算组网配置清单测算）。 */
import client, { post } from '@/shared/api/client';

/** 触发 xlsx 模板下载（由后端 openpyxl 生成，含字段说明与来源列）。 */
export async function downloadTemplate(): Promise<void> {
  const resp = await client.get('/imports/template', { responseType: 'blob' });
  const blob = resp.data as Blob;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'ROI参数录入模板.xlsx';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** 智算组网配置清单（xlsx）自动解析 + 方案估算。 */
export function estimateNetworkBom(file: File): Promise<NetworkBomEstimate> {
  const form = new FormData();
  form.append('file', file);
  // 关键：client 默认 Content-Type 是 application/json，必须显式置 undefined，
  // 否则 axios 携带 JSON header 发 FormData（无 multipart boundary）→ 后端 422「请求参数校验失败」。
  // Content-Type: undefined ⇒ 浏览器自动设置 multipart/form-data; boundary=...
  return client
    .post<NetworkBomEstimate>('/imports/network-bom-estimate', form, {
      headers: { 'Content-Type': undefined },
    })
    .then((r) => r.data as NetworkBomEstimate);
}

/** 配置清单估算结果。 */
export interface NetworkBomEstimate {
  assumptions: string[];
  params: Record<string, unknown>;
  kpis: Record<string, string | null>;
  kpi_meta: Record<string, { label: string; unit: string }>;
  bom_summary: {
    gpu: { id: string; name: string; price_per_card: string };
    server_count: string;
    cards_per_node: string;
    n_gpu: string;
    compute_net: string;
    storage_net: string;
    storage: string;
    mgmt_net: string;
    service: string;
    supporting_capex: string;
    total_estimate: string;
    lines: Array<{ type: string; name: string; qty: string; unit_price: string; total: string; note: string }>;
  };
  financials: { npv: string | null; tco: string | null; payback_static: string | null; irr_annual: string | null };
}

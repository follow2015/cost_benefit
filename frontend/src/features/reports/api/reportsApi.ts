/** 报告导出 API（P1 REQ-12 / P2-5 信创合规）。 */
import client from '@/shared/api/client';

export type ReportFmt = 'pdf' | 'excel' | 'xinchuang';

/** 触发报告下载（PDF / Excel / 信创合规变体），返回后由浏览器保存为文件。 */
export async function exportReport(
  scenarioId: number,
  fmt: ReportFmt,
  opts: { compliance?: 'localization' | null } = {},
): Promise<void> {
  const params: Record<string, string> = { fmt };
  if (opts.compliance === 'localization') {
    params.compliance = 'localization';
  }
  const resp = await client.get(`/reports/${scenarioId}`, {
    params,
    responseType: 'blob',
  });
  const blob = resp.data as Blob;
  const url = URL.createObjectURL(blob);
  // 后端语义（interfaces/api/v1/reports.py）：fmt=xinchuang 等价于 compliance=localization
  // 的 **Excel** 导出（effective_fmt 被改写为 excel）。故只有 pdf 产 PDF，其余都是 xlsx。
  // 此前按 `fmt === 'excel' ? 'xlsx' : 'pdf'` 推导，会让信创版下载到一个名为 .pdf 的 xlsx。
  const ext = fmt === 'pdf' ? 'pdf' : 'xlsx';
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `ROI报告_${fmt === 'xinchuang' ? '信创合规' : fmt}.${ext}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** 批量导入参数（P2-2）：下载模板（CSV / xlsx）→ 上传 CSV / Excel → 解析 → 字段映射 → 校验
 *  → 填充 Wizard 参数。导入仅作「参数预填」，不替代用户确认。 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Button, Space, Typography, Alert, Table, Tag, App as AntApp, Input, Upload, Divider,
} from 'antd';
import { DownloadOutlined, ImportOutlined, FileExcelOutlined, RobotOutlined } from '@ant-design/icons';
import { D } from '@/features/calc/engine/decimalConfig';
import { paramsFromDict } from '@/features/calc/engine/codec';
import { useScenarioDraft } from '@/features/scenarios/stores/scenarioStore';
import { downloadTemplate, estimateNetworkBom, type NetworkBomEstimate } from '@/features/import-params/api/importsApi';
import { findHeaderRow } from '@/features/import-params/lib/templateGrid';

interface ImportField {
  group: string;
  field: string;
  label: string;
  unit: string;
  type: 'number' | 'text';
  required: boolean;
}

// 与后端 IMPORT_FIELDS 对齐（字段集一致）
const FIELDS: ImportField[] = [
  { group: 'hw', field: 'N_gpu', label: 'GPU 数量', unit: '张', type: 'number', required: true },
  { group: 'hw', field: 'P_gpu', label: '单卡价格', unit: '元/卡', type: 'number', required: true },
  { group: 'hw', field: 'P_aux', label: '辅助设备 CAPEX', unit: '元', type: 'number', required: false },
  { group: 'hw', field: 'Y_dep', label: '折旧年限', unit: '年', type: 'number', required: false },
  { group: 'hw', field: 'S_pct', label: '残值率', unit: '比率', type: 'number', required: false },
  { group: 'power', field: 'TDP', label: '单卡 TDP', unit: 'W', type: 'number', required: false },
  { group: 'power', field: 'PUE', label: 'PUE', unit: '', type: 'number', required: false },
  { group: 'power', field: 'E_price', label: '电价', unit: '元/kWh', type: 'number', required: true },
  { group: 'power', field: 'Co_loc', label: '机位租金', unit: '元/月', type: 'number', required: false },
  { group: 'perf', field: 'T_eff', label: '有效吞吐', unit: 'tok/s', type: 'number', required: true },
  { group: 'perf', field: 'T_pf', label: 'Prefill 吞吐', unit: 'tok/s', type: 'number', required: false },
  { group: 'perf', field: 'T_dc', label: 'Decode 吞吐', unit: 'tok/s', type: 'number', required: false },
  { group: 'perf', field: 'SLA_ttft', label: 'SLA TTFT', unit: 'ms', type: 'number', required: false },
  { group: 'perf', field: 'SLA_tpot', label: 'SLA TPOT', unit: 'ms', type: 'number', required: false },
  { group: 'demand', field: 'rho', label: '输入/输出比', unit: '', type: 'number', required: false },
  { group: 'demand', field: 'D_eq', label: '等效月需求', unit: 'Mtok/月', type: 'number', required: true },
  { group: 'demand', field: 'h', label: '缓存命中率', unit: '比率', type: 'number', required: false },
  { group: 'demand', field: 'U', label: '利用率', unit: '比率', type: 'number', required: true },
  { group: 'pricing', field: 'p_in', label: '输入单价', unit: '元/Mtok', type: 'number', required: false },
  { group: 'pricing', field: 'p_out', label: '输出单价', unit: '元/Mtok', type: 'number', required: true },
  { group: 'pricing', field: 'Rent_gpu', label: '租用单价', unit: '元/GPU·时', type: 'number', required: false },
  { group: 'pricing', field: 'API_in', label: 'API 输入价', unit: '元/Mtok', type: 'number', required: false },
  { group: 'pricing', field: 'API_out', label: 'API 输出价', unit: '元/Mtok', type: 'number', required: false },
  { group: 'finance', field: 'T_horizon', label: '投资期', unit: '月', type: 'number', required: false },
  { group: 'finance', field: 'r_w', label: '年化折现率', unit: '比率', type: 'number', required: false },
  { group: 'finance', field: 'Tax', label: '税率', unit: '比率', type: 'number', required: false },
];

const TEMPLATE_HEADER = '组别,字段,标签,单位,类型,必填,来源(measured/estimated/benchmark),填入值';

type RowStatus = 'ok' | 'error';
interface ParsedRow {
  key: string;
  field: ImportField;
  value: string;
  source: string;
  status: RowStatus;
  message: string;
}

function buildCsvTemplate(): string {
  const lines = [TEMPLATE_HEADER];
  for (const f of FIELDS) {
    lines.push([f.group, f.field, f.label, f.unit, f.type, f.required ? '是' : '否', '', ''].join(','));
  }
  return '﻿' + lines.join('\n'); // BOM 便于 Excel 识别 UTF-8
}

function parseCsv(text: string): string[][] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => line.split(','));
}

/** 解析 xlsx/xls：取第一个 sheet，按行转二维字符串数组（与 CSV grid 同构）。
 *
 *  `xlsx` 只在「上传 Excel」这一个分支用到，却被打进页面首屏 chunk（约 380 KB）。
 *  改为按需加载后，CSV 路径与「仅仅打开本页」都不再下载它。 */
async function parseXlsx(buffer: ArrayBuffer): Promise<string[][]> {
  const XLSX = await import('xlsx');
  const wb = XLSX.read(buffer, { type: 'array' });
  const sheetName = wb.SheetNames[0];
  if (!sheetName) throw new Error('Excel 文件无工作表');
  const sheet = wb.Sheets[sheetName];
  const raw = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1, defval: '' });
  return raw
    .map((row) => (row as unknown[]).map((cell) => String(cell ?? '').trim()))
    .filter((row) => row.some((c) => c !== ''));
}

export default function ImportParamsPage(): React.ReactElement {
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const [rows, setRows] = React.useState<ParsedRow[]>([]);

  const handleDownloadCsv = () => {
    const blob = new Blob([buildCsvTemplate()], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ROI参数录入模板.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  /** 按表头映射并校验 grid（CSV 与 xlsx 共用）。 */
  const processGrid = (incoming: string[][]): void => {
    // 后端生成的 xlsx 模板前几行是「标题 / 填写说明 / 空行」，表头在第 4 行；
    // CSV 模板首行即表头。此前一律按 `grid[0]` 取表头，导致下载来的官方 xlsx 模板
    // 上传后必定报「表头缺少字段列」——模板与解析器从未闭环验证过。
    const headerAt = findHeaderRow(incoming);
    const grid = incoming.slice(headerAt);
    const header = grid[0] ?? [];
    // 定位列索引（兼容中/英表头）
    const idx = (name: string) => header.findIndex((h) => h.trim() === name);
    const iGroup = idx('组别');
    const iField = idx('字段') >= 0 ? idx('字段') : idx('字段(key)');
    const iValue = Math.max(idx('填入值'), idx('值'));
    const iSource = Math.max(idx('来源'), idx('来源(measured/estimated/benchmark)'));

    if (iField < 0 || iValue < 0) {
      message.error('表头缺少「字段」或「填入值」列（请使用下载的模板）');
      return;
    }

    const parsed: ParsedRow[] = [];
    for (const cells of grid.slice(1)) {
      const group = (cells[iGroup] ?? '').trim();
      const fieldKey = (cells[iField] ?? '').trim();
      const value = (cells[iValue] ?? '').trim();
      const source = iSource >= 0 ? (cells[iSource] ?? '').trim() : '';
      if (!fieldKey) continue;
      const meta = FIELDS.find((f) => f.group === group && f.field === fieldKey);
      if (!meta) {
        parsed.push({ key: fieldKey, field: { group, field: fieldKey, label: fieldKey, unit: '', type: 'number', required: false }, value, source, status: 'error', message: '未知字段，已忽略' });
        continue;
      }
      if (value === '') {
        if (meta.required) {
          parsed.push({ key: fieldKey, field: meta, value, source, status: 'error', message: '必填项缺失' });
        }
        continue; // 非必填空值跳过
      }
      if (meta.type === 'number' && Number.isNaN(Number(value))) {
        parsed.push({ key: fieldKey, field: meta, value, source, status: 'error', message: '数值类型非法' });
        continue;
      }
      const okSource = ['measured', 'estimated', 'benchmark', ''].includes(source);
      parsed.push({
        key: fieldKey,
        field: meta,
        value,
        source,
        status: okSource ? 'ok' : 'error',
        message: okSource ? `来源：${source || '未标注'}` : '来源取值非法（应为 measured/estimated/benchmark）',
      });
    }
    setRows(parsed);
    const errs = parsed.filter((r) => r.status === 'error');
    if (errs.length === 0) message.success(`解析成功，共 ${parsed.length} 条有效参数`);
    else message.warning(`解析完成，${errs.length} 条存在问题，请修正后再填充`);
  };

  const handleFile = (file: File) => {
    const name = file.name.toLowerCase();
    const isXlsx = name.endsWith('.xlsx') || name.endsWith('.xls');
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const grid = isXlsx
          ? await parseXlsx(reader.result as ArrayBuffer)
          : parseCsv(String(reader.result ?? ''));
        processGrid(grid);
      } catch (e) {
        // 解析器按需加载，网络/分发失败也会走到这里，故兜底文案带上原因
        message.error((e as Error).message || '解析失败');
      }
    };
    if (isXlsx) reader.readAsArrayBuffer(file);
    else reader.readAsText(file);
  };

  const hasError = rows.some((r) => r.status === 'error');
  const validRows = rows.filter((r) => r.status === 'ok' && r.value !== '');

  const handleFill = () => {
    if (hasError) {
      message.error('存在校验错误，无法填充');
      return;
    }
    const draft = useScenarioDraft.getState();
    const sources: Record<string, string> = { ...draft.params.bench.sources };
    for (const r of validRows) {
      draft.setField(r.field.group as never, r.field.field, D(r.value));
      if (r.source) sources[r.field.field] = r.source;
    }
    draft.setField('bench', 'sources', sources);
    message.success(`已预填 ${validRows.length} 个参数，请在向导中确认`);
    navigate('/scenarios/new');
  };

  const columns = [
    { title: '字段', dataIndex: 'key', key: 'key' },
    { title: '标签', key: 'label', render: (_: unknown, r: ParsedRow) => r.field.label },
    { title: '单位', key: 'unit', render: (_: unknown, r: ParsedRow) => r.field.unit },
    { title: '填入值', dataIndex: 'value', key: 'value' },
    { title: '来源', dataIndex: 'source', key: 'source' },
    {
      title: '状态',
      key: 'status',
      render: (_: unknown, r: ParsedRow) =>
        r.status === 'ok' ? <Tag color="green">通过</Tag> : <Tag color="red">{r.message}</Tag>,
    },
  ];

  return (
    <div>
      <Card
        title={
          <Space>
            <ImportOutlined />
            <span>批量导入参数（P2-2）</span>
            <Tag color="blue">导入仅预填，需用户确认</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<DownloadOutlined />} onClick={handleDownloadCsv}>下载 CSV 模板</Button>
            <Button icon={<FileExcelOutlined />} onClick={() => void downloadTemplate()}>下载 xlsx 模板</Button>
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          title="使用说明"
          description="下载模板后在「填入值」列录入数值、「来源」列标注实测/估算/基准；上传 CSV 或 Excel（.xlsx/.xls）后系统将解析、校验并预填到新建方案向导。"
        />
        <Space orientation="vertical" style={{ width: '100%' }} size={12}>
          <Upload
            accept=".csv,.xlsx,.xls"
            showUploadList={false}
            beforeUpload={(file) => {
              handleFile(file);
              return false;
            }}
          >
            <Button type="primary" icon={<ImportOutlined />}>上传 CSV / Excel 并解析</Button>
          </Upload>
          <Input.TextArea rows={3} placeholder="或将 CSV 文本内容粘贴到此处（暂不支持，请使用上传）" disabled />
        </Space>
        <Divider />
        {rows.length > 0 ? (
          <>
            {hasError ? (
              <Alert type="error" showIcon style={{ marginBottom: 12 }} title="存在校验错误，已阻断填充" />
            ) : (
              <Alert type="success" showIcon style={{ marginBottom: 12 }} title={`校验通过，可填充 ${validRows.length} 个参数`} />
            )}
            <Table
              columns={columns}
              dataSource={rows}
              pagination={false}
              size="small"
              rowKey="key"
              scroll={{ y: 360 }}
            />
            <Button type="primary" style={{ marginTop: 12 }} disabled={hasError || validRows.length === 0} onClick={handleFill}>
              填充到新建方案向导
            </Button>
          </>
        ) : (
          <Typography.Text type="secondary">尚未解析任何文件。</Typography.Text>
        )}
      </Card>

      <Card
        style={{ marginTop: 16 }}
        title={
          <Space>
            <RobotOutlined />
            <span>智算组网配置清单自动测算</span>
            <Tag color="purple">上传清单 → 自动估算</Tag>
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          title="使用说明"
          description="上传智算组网配置清单（xlsx，如 5090 方案-100GE 组网：含 GPU 服务器/推理·存储·管理交换机/线缆/分布式存储/集成维保，逐项数量与单价）。系统自动解析为 BOM 并映射方案参数，走计算引擎估算 ROI；GPU 型号按名称关键词匹配目录（5090/H20/910B 等），服务器单价缺失时按目录参考价估算并显式标注假设。"
        />
        <BomEstimateSection />
      </Card>
    </div>
  );
}

/** 配置清单上传 → 解析 → 估算 → 一键应用。 */
function BomEstimateSection(): React.ReactElement {
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const [loading, setLoading] = React.useState(false);
  const [result, setResult] = React.useState<NetworkBomEstimate | null>(null);

  const handleUpload = async (file: File) => {
    setLoading(true);
    try {
      const res = await estimateNetworkBom(file);
      setResult(res);
      message.success('解析并估算完成，可查看 BOM 与 KPI 或一键应用');
    } catch (e) {
      // 展示 422 字段级错误（ApiError.detail 含 errors 列表）
      const apiErr = e as { message?: string; detail?: unknown };
      const errs = (apiErr.detail as { errors?: Array<{ loc?: unknown[]; msg?: string }> })?.errors;
      if (errs && errs.length > 0) {
        const first = errs
          .slice(0, 3)
          .map((x) => (x.loc ? `${x.loc.join('.')}: ${x.msg}` : x.msg))
          .join('；');
        message.error(`${apiErr.message || '解析失败'}（${first}）`);
      } else {
        message.error(apiErr.message || '解析失败');
      }
    } finally {
      setLoading(false);
    }
    return false;
  };

  const handleApply = () => {
    if (!result) return;
    const params = paramsFromDict(result.params as Record<string, unknown>);
    const draft = useScenarioDraft.getState();
    draft.setParams(params);
    // 自动生成方案名称与摘要（源自配置清单估算结果）
    const gpuName = result.bom_summary?.gpu?.name ?? '';
    draft.setName(gpuName ? `智算组网方案估算（${gpuName} ×${result.bom_summary?.n_gpu ?? ''}卡）` : '智算组网方案估算');
    const parts = [
      `源自配置清单自动测算`,
      `GPU=${gpuName || '—'}`,
      `N_gpu=${result.bom_summary?.n_gpu ?? '—'}`,
      `配套CAPEX=${fmt(result.bom_summary?.supporting_capex)}元`,
      `总投入=${fmt(result.bom_summary?.total_estimate)}元`,
      `NPV=${fmt(result.financials?.npv)}元`,
    ];
    draft.setDescription(parts.join('；'));
    message.success('估算参数已回填至测算向导（含自动生成的方案名称与摘要），请确认后计算');
    navigate('/scenarios/new');
  };

  const num = (v: string | null | undefined, fallback = 0): number => {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };
  const fmt = (v: string | null | undefined, digits = 0): string => {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(digits || 1)}万`;
    return n.toLocaleString('zh-CN', { maximumFractionDigits: digits });
  };

  const bom = result?.bom_summary;
  const lineColumns = [
    { title: '类型', dataIndex: 'type', key: 'type', width: 110 },
    { title: '设备', dataIndex: 'name', key: 'name', width: 150 },
    { title: '数量', dataIndex: 'qty', key: 'qty', width: 70, align: 'right' as const },
    { title: '单价(元)', dataIndex: 'unit_price', key: 'unit_price', width: 100, align: 'right' as const, render: (v: string) => fmt(v) },
    { title: '总价(元)', dataIndex: 'total', key: 'total', width: 110, align: 'right' as const, render: (v: string) => fmt(v) },
    { title: '备注', dataIndex: 'note', key: 'note', ellipsis: true },
  ];

  return (
    <div>
      <Upload
        accept=".xlsx,.xls"
        showUploadList={false}
        beforeUpload={(file) => {
          void handleUpload(file);
          return false;
        }}
      >
        <Button type="primary" icon={<FileExcelOutlined />} loading={loading}>
          上传配置清单并自动测算
        </Button>
      </Upload>

      {result && bom && (
        <div style={{ marginTop: 16 }}>
          <Space wrap size={[16, 8]} style={{ marginBottom: 12 }}>
            <StatisticBlock label="识别 GPU" value={bom.gpu.name} />
            <StatisticBlock label="服务器" value={`${bom.server_count} 台 × ${bom.cards_per_node} 卡/台`} />
            <StatisticBlock label="总卡数" value={num(bom.n_gpu, 0).toLocaleString()} suffix="卡" />
            <StatisticBlock label="配套 CAPEX" value={fmt(bom.supporting_capex)} suffix="元" />
            <StatisticBlock label="总投入估算" value={fmt(bom.total_estimate)} suffix="元" />
            <StatisticBlock label="NPV" value={fmt(result.financials.npv)} suffix="元" />
            <StatisticBlock label="TCO" value={fmt(result.financials.tco)} suffix="元" />
            <StatisticBlock label="回本" value={result.financials.payback_static ? `${num(result.financials.payback_static, 1)} 月` : '—'} />
          </Space>

          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            title="估算假设（请确认）"
            description={<ul style={{ margin: 0, paddingLeft: 18 }}>{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>}
          />

          <Table
            size="small"
            rowKey={(r) => `${r.type}-${r.name}-${r.qty}`}
            columns={lineColumns}
            dataSource={bom.lines}
            pagination={false}
            scroll={{ y: 260 }}
          />

          <Button type="primary" style={{ marginTop: 12 }} icon={<ImportOutlined />} onClick={handleApply}>
            应用此估算方案
          </Button>
        </div>
      )}
    </div>
  );
}

function StatisticBlock({ label, value, suffix }: { label: string; value: string; suffix?: string }): React.ReactElement {
  return (
    <div>
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>{label}</Typography.Text>
      <Typography.Text strong>{value} {suffix ?? ''}</Typography.Text>
    </div>
  );
}

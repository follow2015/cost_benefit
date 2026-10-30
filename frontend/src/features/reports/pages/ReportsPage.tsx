/** 报告导出页（P1 REQ-12 / P2-5 信创合规）：按方案导出 PDF / Excel 报告（含口径摘要与免责声明）。 */
import React from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { App, Button, Card, Descriptions, Space, Tag, Typography, Alert, Switch, Typography as T } from 'antd';
import { FilePdfOutlined, FileExcelOutlined, ArrowLeftOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { useScenario } from '@/features/scenarios/hooks/useScenarios';
import { exportReport, type ReportFmt } from '@/features/reports/api/reportsApi';

export default function ReportsPage(): React.ReactElement {
  const { id } = useParams();
  const scenarioId = Number(id);
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { data: scenario, isLoading } = useScenario(scenarioId);
  const [exporting, setExporting] = React.useState<ReportFmt | null>(null);
  const [compliance, setCompliance] = React.useState(false);

  const handleExport = async (fmt: ReportFmt) => {
    setExporting(fmt);
    try {
      await exportReport(scenarioId, fmt, { compliance: compliance ? 'localization' : null });
      message.success(`已开始下载 ${fmt.toUpperCase()} 报告${compliance ? '（信创合规版）' : ''}`);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setExporting(null);
    }
  };

  if (isLoading || !scenario) {
    return <Card loading />;
  }

  return (
    <Card
      title={
        <Space>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/scenarios/${scenarioId}`)} />
          <span>报告导出 · {scenario.name}</span>
          <Tag color="blue">CNY · 税前</Tag>
        </Space>
      }
    >
      <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="方案版本">v{scenario.version}</Descriptions.Item>
        <Descriptions.Item label="口径">CNY · 税前 · 利用率=有效负载/满负荷</Descriptions.Item>
      </Descriptions>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="报告内容"
        description="报告包含测算口径摘要、输入参数明细、核心经济指标（KPI）、投资财务摘要、单位成本结构、逐年现金流与敏感性分析，并附免责声明。无历史计算结果时将自动触发一次权威计算后再导出。"
      />

      <Space align="center" style={{ marginBottom: 12 }}>
        <SafetyCertificateOutlined />
        <T.Text>信创合规报表（国产化专项）</T.Text>
        <Switch checked={compliance} onChange={setCompliance} />
        <T.Text type="secondary">开启后追加「国产卡占比 / CN_cfg 取值与含义 / 专项结论与合规提示」段落</T.Text>
      </Space>

      <Space wrap>
        <Button
          type="primary"
          icon={<FilePdfOutlined />}
          loading={exporting === 'pdf'}
          onClick={() => handleExport('pdf')}
        >
          导出 PDF{compliance ? '（合规）' : ''}
        </Button>
        <Button
          icon={<FileExcelOutlined />}
          loading={exporting === 'excel'}
          onClick={() => handleExport('excel')}
        >
          导出 Excel{compliance ? '（合规）' : ''}
        </Button>
        <Button
          icon={<SafetyCertificateOutlined />}
          loading={exporting === 'xinchuang'}
          onClick={() => handleExport('xinchuang')}
        >
          信创合规报表（xinchuang）
        </Button>
      </Space>

      <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
        免责声明：本平台测算结果完全基于用户输入假设与行业基准，不构成任何投资承诺或建议；实际决策须结合尽调与专业意见。
      </Typography.Paragraph>
    </Card>
  );
}

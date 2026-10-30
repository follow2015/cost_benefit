/** 单个参数输入控件：绑定 scenario draft store，支持数字/百分比/选择/开关/可空数字。 */
import React from 'react';
import { InputNumber, Select, Switch, Input, Tooltip, Tag } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';
import { Decimal } from '@/features/calc/engine/decimalConfig';
import { readFieldValue, type FieldMeta } from './paramMeta';

/** M-17 来源标记徽标：标注字段取值来源（基准库 / 用户估算）。 */
function SourceBadge({ source }: { source?: FieldMeta['source'] }): React.ReactNode {
  if (source === 'benchmark') {
    return <Tag color="green" style={{ marginLeft: 4, lineHeight: '16px' }}>基准库</Tag>;
  }
  if (source === 'estimated') {
    return <Tag color="default" style={{ marginLeft: 4, lineHeight: '16px' }}>估算</Tag>;
  }
  return null;
}

interface Props {
  meta: FieldMeta;
  value: unknown;
  onChange: (value: unknown) => void;
}

export function ParamField({ meta, value, onChange }: Props): React.ReactElement {
  const toDisplay = (): number | null => {
    if (value === null || value === undefined || value === '') return null;
    const num = value instanceof Decimal ? value.toNumber() : Number(value);
    if (!Number.isFinite(num)) return null;
    return meta.scale100 ? num * 100 : num;
  };

  const fromDisplay = (display: number | null): unknown => {
    if (display === null || Number.isNaN(display)) return meta.type === 'nullable-number' ? null : 0;
    const ratio = meta.scale100 ? display / 100 : display;
    return meta.type === 'nullable-number' ? (display === null ? null : ratio) : ratio;
  };

  const common = meta.hint ? (
    <Tooltip title={meta.hint}>
      <InfoCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
    </Tooltip>
  ) : null;

  let control: React.ReactNode;
  switch (meta.type) {
    case 'switch':
      control = <Switch checked={Boolean(value)} onChange={(v) => onChange(v)} />;
      break;
    case 'select':
      control = (
        <Select
          style={{ width: '100%' }}
          value={typeof value === 'string' ? value : undefined}
          options={meta.options}
          onChange={(v) => onChange(v)}
        />
      );
      break;
    case 'nullable-number':
      control = (
        <InputNumber
          style={{ width: '100%' }}
          value={toDisplay()}
          step={meta.step}
          min={meta.min}
          max={meta.max}
          placeholder="留空"
          onChange={(v) => onChange(fromDisplay(v == null ? null : Number(v)))}
        />
      );
      break;
    case 'text':
      control = (
        <Input value={value == null ? '' : String(value)} onChange={(e) => onChange(e.target.value)} placeholder="留空" />
      );
      break;
    default:
      control = (
        <InputNumber
          style={{ width: '100%' }}
          value={toDisplay()}
          step={meta.step}
          min={meta.min}
          max={meta.max}
          onChange={(v) => onChange(fromDisplay(v == null ? 0 : Number(v)))}
        />
      );
  }

  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ fontSize: 13, marginBottom: 2 }}>
        {meta.label}
        {meta.unit ? <span style={{ color: '#999' }}>（{meta.unit}）</span> : null}
        <SourceBadge source={meta.source} />
        {common}
      </div>
      {control}
    </div>
  );
}

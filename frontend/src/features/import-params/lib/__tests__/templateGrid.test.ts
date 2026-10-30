import { describe, expect, it } from 'vitest';
import { findHeaderRow, isHeaderRow } from '@/features/import-params/lib/templateGrid';

const HEADER = ['组别', '字段', '标签', '单位', '类型', '必填', '填入值', '来源'];

describe('模板表头定位', () => {
  it('CSV 模板：表头在首行', () => {
    const grid = [HEADER, ['hw', 'N_gpu', 'GPU 数量', '张', 'number', '是', '8', 'measured']];
    expect(findHeaderRow(grid)).toBe(0);
  });

  it('xlsx 模板：跳过标题 / 说明 / 空行，定位到第 4 行', () => {
    const grid = [
      ['AI 算力 ROI 测算 · 批量参数录入模板'],
      ['填写说明：按「填入值」列录入数值…'],
      [],
      HEADER,
      ['hw', 'N_gpu', 'GPU 数量', '张', 'number', '是', '', ''],
    ];
    expect(findHeaderRow(grid)).toBe(3);
  });

  it('英文表头「字段(key)」与「值」同样被识别', () => {
    const grid = [['group', '字段(key)', 'label', 'unit', 'type', 'required', '值', '来源']];
    expect(findHeaderRow(grid)).toBe(0);
    expect(isHeaderRow(grid[0])).toBe(true);
  });

  it('表头缺「填入值」列则不算表头', () => {
    const grid = [['组别', '字段', '标签'], HEADER];
    expect(findHeaderRow(grid)).toBe(1);
  });

  it('完全找不到表头时回退到首行（由调用方报「表头缺少…」）', () => {
    const grid = [['随便', '什么'], ['内容']];
    expect(findHeaderRow(grid)).toBe(0);
  });

  it('空表返回 0 且不抛异常', () => {
    expect(findHeaderRow([])).toBe(0);
    expect(findHeaderRow([[]])).toBe(0);
  });

  it('单元格两侧空白不影响判定', () => {
    expect(isHeaderRow([' 字段 ', ' 填入值 '])).toBe(true);
  });
});

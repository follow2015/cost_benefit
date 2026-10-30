/** UI 全局状态（Zustand）：主题、抽屉、双端一致性偏差日志。 */
import { create } from 'zustand';
import type { DeviationLog } from '@/shared/types';

interface UiState {
  themeMode: 'light' | 'dark';
  toggleTheme: () => void;
  deviationLogs: DeviationLog[];
  pushDeviation: (log: DeviationLog) => void;
  lastDeviation: DeviationLog | null;
  formulaDrawerOpen: boolean;
  openFormulaDrawer: () => void;
  closeFormulaDrawer: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  themeMode: 'light',
  toggleTheme: () => set((s) => ({ themeMode: s.themeMode === 'light' ? 'dark' : 'light' })),
  deviationLogs: [],
  pushDeviation: (log) =>
    set((s) => ({ deviationLogs: [log, ...s.deviationLogs].slice(0, 20), lastDeviation: log })),
  lastDeviation: null,
  formulaDrawerOpen: false,
  openFormulaDrawer: () => set({ formulaDrawerOpen: true }),
  closeFormulaDrawer: () => set({ formulaDrawerOpen: false }),
}));

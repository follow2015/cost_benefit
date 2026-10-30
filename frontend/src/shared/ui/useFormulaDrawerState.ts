/** 公式抽屉共享状态：从 ui store 暴露 open/关闭。 */
import { useUiStore } from '@/shared/ui/uiStore';

export function useFormulaDrawerState() {
  const open = useUiStore((s) => s.formulaDrawerOpen);
  const openDrawer = useUiStore((s) => s.openFormulaDrawer);
  const closeDrawer = useUiStore((s) => s.closeFormulaDrawer);
  return { open, openDrawer, closeDrawer } as const;
}

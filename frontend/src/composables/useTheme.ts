import { storeToRefs } from 'pinia'
import { useUiStore } from '@/stores/ui'

export function useTheme() {
  const store = useUiStore()
  const { theme, isDark } = storeToRefs(store)
  return {
    theme,
    isDark,
    setTheme: store.setTheme,
    toggleTheme: store.toggleTheme,
  }
}

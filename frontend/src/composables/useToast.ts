import { useUiStore } from '@/stores/ui'

export function useToast() {
  const store = useUiStore()
  return {
    info: (message: string, title?: string) => store.pushToast({ kind: 'info', message, title }),
    success: (message: string, title?: string) =>
      store.pushToast({ kind: 'success', message, title }),
    warning: (message: string, title?: string) =>
      store.pushToast({ kind: 'warning', message, title }),
    error: (message: string, title?: string) => store.pushToast({ kind: 'error', message, title }),
    dismiss: store.dismissToast,
  }
}

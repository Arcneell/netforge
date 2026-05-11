<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { CheckCircle2, AlertTriangle, Info, XCircle, X } from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import type { ToastKind } from '@/stores/ui'

const ui = useUiStore()
const { toasts } = storeToRefs(ui)

const icons = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
} as const

const kindClasses: Record<ToastKind, string> = {
  info: 'text-primary-600 bg-primary-50 dark:bg-primary-100/20',
  success: 'text-success bg-success/10',
  warning: 'text-warning bg-warning/10',
  error: 'text-danger bg-danger/10',
}
</script>

<template>
  <div
    class="fixed z-[60] bottom-4 right-4 flex flex-col gap-2 w-full max-w-sm pointer-events-none"
    role="region"
    aria-live="polite"
    aria-label="Notifications"
  >
    <TransitionGroup
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0 translate-x-2"
      enter-to-class="opacity-100 translate-x-0"
      leave-active-class="transition duration-100 ease-in absolute"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0 translate-x-2"
    >
      <div
        v-for="t in toasts"
        :key="t.id"
        :class="['nf-card pointer-events-auto flex items-start gap-3 p-3 pr-2']"
        role="status"
      >
        <div :class="['flex-shrink-0 rounded-md p-1.5', kindClasses[t.kind]]">
          <component :is="icons[t.kind]" class="w-4 h-4" aria-hidden="true" />
        </div>
        <div class="flex-1 min-w-0">
          <p v-if="t.title" class="text-sm font-semibold text-fg">{{ t.title }}</p>
          <p class="text-sm text-fg-muted break-words">{{ t.message }}</p>
        </div>
        <button
          type="button"
          class="p-1 rounded hover:bg-surface-hover text-fg-muted"
          :aria-label="$t('common.close')"
          @click="ui.dismissToast(t.id)"
        >
          <X class="w-4 h-4" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

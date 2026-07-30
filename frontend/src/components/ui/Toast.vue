<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { CheckCircle2, AlertTriangle, Info, XCircle, X } from '@lucide/vue'
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
  info: 'text-primary-600 bg-primary-50 dark:text-primary-300 dark:bg-primary-500/15',
  success: 'text-success bg-success/10',
  warning: 'text-warning bg-warning/10',
  error: 'text-danger bg-danger/10',
}

// Split into two stacks so error/warning toasts announce with
// `aria-live="assertive"` while info/success use the gentler "polite".
// Per WCAG 4.1.3, the failure surface should interrupt the current
// utterance — finishing a sentence and missing "delete failed" is the
// exact UX the polite region produces.
const politeToasts = computed(() =>
  toasts.value.filter((t) => t.kind === 'info' || t.kind === 'success'),
)
const assertiveToasts = computed(() =>
  toasts.value.filter((t) => t.kind === 'warning' || t.kind === 'error'),
)
</script>

<template>
  <!-- Single positioned wrapper so the two ARIA regions stack
       vertically instead of overlapping. The previous implementation
       had both regions `fixed bottom-4 right-4` at the same z-index;
       when both held a toast (bulk import with mixed success/error,
       success toast followed by a network error within the dismissal
       window, etc.), the assertive region painted on top of the polite
       one — the success/info card became visually invisible and its
       dismiss-X was covered by the assertive card's pointer-events
       surface. Use `flex-col-reverse` so newer toasts sit closer to
       the corner (matching how each region's TransitionGroup already
       enters new items), and render assertive first so warnings/errors
       end up at the bottom (most visually prominent).
  -->
  <div
    class="fixed z-[60] bottom-4 right-4 flex flex-col-reverse gap-2 w-full max-w-sm pointer-events-none"
  >
    <!-- Assertive region (rendered first so it sits at the bottom
         under `flex-col-reverse`) for warnings + errors. -->
    <div role="region" aria-live="assertive" aria-label="Alerts" class="flex flex-col gap-2">
      <TransitionGroup
        enter-active-class="transition duration-200 ease-soft"
        enter-from-class="opacity-0 translate-y-2 scale-[0.98]"
        enter-to-class="opacity-100 translate-y-0 scale-100"
        leave-active-class="transition duration-150 ease-soft absolute"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0 translate-x-3"
        move-class="transition-transform duration-200 ease-soft"
      >
        <div
          v-for="t in assertiveToasts"
          :key="t.id"
          :class="['nf-card pointer-events-auto flex items-start gap-3 p-3 pr-2']"
          role="alert"
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

    <!-- Polite region (rendered second so it sits ABOVE the assertive
         one under `flex-col-reverse`) for info + success toasts. -->
    <div role="region" aria-live="polite" aria-label="Notifications" class="flex flex-col gap-2">
      <TransitionGroup
        enter-active-class="transition duration-200 ease-soft"
        enter-from-class="opacity-0 translate-y-2 scale-[0.98]"
        enter-to-class="opacity-100 translate-y-0 scale-100"
        leave-active-class="transition duration-150 ease-soft absolute"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0 translate-x-3"
        move-class="transition-transform duration-200 ease-soft"
      >
        <div
          v-for="t in politeToasts"
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
  </div>
</template>

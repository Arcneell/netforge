<script setup lang="ts">
import { onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    closable?: boolean
    size?: 'sm' | 'md' | 'lg' | 'xl'
  }>(),
  {
    closable: true,
    size: 'md',
  },
)

const emit = defineEmits<{ (e: 'close'): void }>()
const dialogRef = ref<HTMLDivElement | null>(null)
const titleId = useId()
// Track the element that had focus before the dialog opened so we can hand
// focus back to it on close — keyboard users land on the trigger again,
// not at the top of the page.
const previouslyFocused = ref<HTMLElement | null>(null)

const sizeClass = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
} as const

// CSS selector for elements that participate in the tab order. Matches what
// most accessibility libraries use; intentionally loose so we don't have to
// list every form control type.
const FOCUSABLE_SELECTOR =
  'a[href], area[href], input:not([disabled]):not([type="hidden"]), select:not([disabled]),' +
  ' textarea:not([disabled]), button:not([disabled]), iframe, object, embed,' +
  ' [tabindex]:not([tabindex="-1"]), [contenteditable="true"]'

function focusables(): HTMLElement[] {
  const root = dialogRef.value
  if (!root) return []
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    // Visible-only — `offsetParent` is null when the element (or its parent)
    // is `display: none`. We also drop `aria-hidden` regions.
    (el) => el.offsetParent !== null && el.getAttribute('aria-hidden') !== 'true',
  )
}

function onKey(e: KeyboardEvent) {
  if (!props.open) return
  if (e.key === 'Escape' && props.closable) {
    emit('close')
    return
  }
  if (e.key !== 'Tab') return

  // Focus trap: keep keyboard navigation inside the dialog. Without this
  // shift-tab from the first input escapes back into the page below the
  // overlay, breaking the modal contract for keyboard users.
  const els = focusables()
  if (els.length === 0) {
    e.preventDefault()
    dialogRef.value?.focus()
    return
  }
  const first = els[0]
  const last = els[els.length - 1]
  const active = document.activeElement as HTMLElement | null
  if (e.shiftKey && (active === first || !dialogRef.value?.contains(active))) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && active === last) {
    e.preventDefault()
    first.focus()
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})

watch(
  () => props.open,
  (open) => {
    document.body.style.overflow = open ? 'hidden' : ''
    if (open) {
      previouslyFocused.value = document.activeElement as HTMLElement | null
      requestAnimationFrame(() => {
        // Prefer the first focusable inside the dialog (input, button) so the
        // user can start typing immediately. Fall back to the dialog itself
        // when the modal has no focusable content (e.g. a pure message).
        const els = focusables()
        if (els.length > 0) els[0].focus()
        else dialogRef.value?.focus()
      })
    } else {
      // Return focus to the trigger on close. Microtask defers until after
      // the closing transition swaps focus targets.
      const target = previouslyFocused.value
      previouslyFocused.value = null
      queueMicrotask(() => target?.focus?.())
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-100 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 bg-zinc-950/30 dark:bg-zinc-950/60 backdrop-blur-md"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="title ? titleId : undefined"
        :aria-label="title ? undefined : $t('common.confirm')"
        @click.self="closable && $emit('close')"
      >
        <Transition
          enter-active-class="transition duration-200 ease-ios-spring"
          enter-from-class="opacity-0 translate-y-4 sm:translate-y-2 scale-[0.96]"
          enter-to-class="opacity-100 translate-y-0 scale-100"
          leave-active-class="transition duration-150 ease-in"
          leave-from-class="opacity-100 translate-y-0"
          leave-to-class="opacity-0 translate-y-4 sm:translate-y-2"
        >
          <div
            v-if="open"
            ref="dialogRef"
            tabindex="-1"
            :class="[
              // iOS sheet on mobile (full-width, rounded only at the top),
              // floating card on desktop with bigger radius and richer shadow.
              'bg-surface w-full focus:outline-none shadow-pop',
              'rounded-t-2xl sm:rounded-xl',
              'border-t border-x sm:border border-border/70 dark:border-border/40',
              sizeClass[size],
            ]"
          >
            <header
              v-if="title || closable"
              class="flex items-center justify-between px-6 pt-5 pb-4"
            >
              <h2 :id="titleId" class="text-base font-semibold text-fg tracking-tight">
                {{ title }}
              </h2>
              <button
                v-if="closable"
                type="button"
                class="inline-flex items-center justify-center w-8 h-8 rounded-full bg-muted/60 hover:bg-muted text-fg-muted hover:text-fg transition-colors"
                :aria-label="$t('common.close')"
                @click="$emit('close')"
              >
                <X class="w-3.5 h-3.5" />
              </button>
            </header>
            <div class="px-6 pb-6">
              <slot />
            </div>
            <footer
              v-if="$slots.footer"
              class="px-6 py-4 border-t border-border/70 dark:border-border/40 bg-muted/30 rounded-b-2xl sm:rounded-b-xl"
            >
              <slot name="footer" />
            </footer>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

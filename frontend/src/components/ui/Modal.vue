<script setup lang="ts">
import { onMounted, onUnmounted, ref, toRef, useId, watch } from 'vue'
import { X } from 'lucide-vue-next'

import { useScrollLock } from '@/composables/useScrollLock'
import { pushModal, popModal, isTopmostModal } from '@/composables/useModalStack'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    /** Accessible name for title-less modals. Ignored when `title` is set
     * (the visible heading labels the dialog via `aria-labelledby`). */
    ariaLabel?: string
    closable?: boolean
    size?: 'sm' | 'md' | 'lg' | 'xl'
  }>(),
  {
    title: undefined,
    ariaLabel: undefined,
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

// Per-instance identity that joins the global modal stack. Symbols are
// unique even when the same Modal component renders multiple times.
const stackId = Symbol('modal')

function onKey(e: KeyboardEvent) {
  if (!props.open) return
  // Only the topmost modal in the stack handles keyboard input.
  // Otherwise pressing Escape on the inner dialog also dismisses the
  // outer one, and the outer's focus-trap fights the inner's Tab.
  if (!isTopmostModal(stackId)) return
  if (e.key === 'Escape' && props.closable) {
    e.stopPropagation()
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

// Ref-counted body scroll-lock. Replaces the per-instance
// `document.body.style.overflow = 'hidden' / ''` toggle that broke when
// modals stacked (closing the inner one released the lock while the
// outer was still visible).
useScrollLock(toRef(props, 'open'))

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  // Belt-and-suspenders pop in case the parent unmounted us while
  // `props.open` was still true (route change mid-open, v-if flip).
  popModal(stackId)
})

watch(
  () => props.open,
  (open, prev) => {
    if (open) {
      pushModal(stackId)
      previouslyFocused.value = document.activeElement as HTMLElement | null
      requestAnimationFrame(() => {
        // Prefer the first focusable inside the dialog (input, button) so the
        // user can start typing immediately. Fall back to the dialog itself
        // when the modal has no focusable content (e.g. a pure message).
        const els = focusables()
        if (els.length > 0) els[0].focus()
        else dialogRef.value?.focus()
      })
    } else if (prev) {
      // Close-path only fires on a real open→close transition. Avoids
      // running the focus-restore + popModal on the synthetic initial
      // run when the modal mounted with `open=false` (prev === undefined).
      popModal(stackId)
      // Return focus to the trigger on close. Microtask defers until
      // after the closing transition swaps focus targets.
      const target = previouslyFocused.value
      previouslyFocused.value = null
      queueMicrotask(() => target?.focus?.())
    }
  },
  // `immediate: true` so a modal mounted with `open` already true (the
  // typical `v-if="editing"` + `:open="!!editing"` pattern across the
  // remaining modal editors — SiteEditor, RoomEditor, LinkEditor) still
  // gets pushed onto the stack on first render. Without this, the topmost-
  // modal guard returns early for Escape/Tab and the keyboard close +
  // focus trap silently break for every "open on mount" path (Codex
  // P2 on #98).
  { immediate: true },
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
        class="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 bg-plate/70"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="title ? titleId : undefined"
        :aria-label="title ? undefined : (ariaLabel ?? $t('common.confirm'))"
        @click.self="closable && $emit('close')"
      >
        <Transition
          enter-active-class="transition duration-150 ease-soft"
          enter-from-class="opacity-0 translate-y-3 sm:translate-y-0 sm:scale-[0.98]"
          enter-to-class="opacity-100 translate-y-0 sm:scale-100"
          leave-active-class="transition duration-100 ease-soft"
          leave-from-class="opacity-100 translate-y-0"
          leave-to-class="opacity-0 translate-y-3 sm:translate-y-0"
        >
          <div
            v-if="open"
            ref="dialogRef"
            tabindex="-1"
            :class="[
              // Sheet on mobile (full width, rounded at the top only), a
              // floating dialog on desktop. Radius matches the rest of the
              // design system (`rounded-lg`, same as `.nf-card`) instead of
              // the larger `2xl`/`xl` this used to carry on its own.
              'bg-surface w-full focus:outline-none shadow-xl',
              'rounded-t-lg sm:rounded-lg',
              'border-t border-x sm:border border-border',
              sizeClass[size],
            ]"
          >
            <header
              v-if="title || closable"
              class="flex items-start justify-between gap-4 px-6 pt-5 pb-1"
            >
              <h2 :id="titleId" class="text-lg font-semibold text-fg tracking-[-0.01em]">
                {{ title }}
              </h2>
              <button
                v-if="closable"
                type="button"
                class="-mr-1.5 -mt-0.5 inline-flex items-center justify-center w-8 h-8 rounded-md text-fg-subtle hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-soft"
                :aria-label="$t('common.close')"
                @click="$emit('close')"
              >
                <X class="w-4 h-4" />
              </button>
            </header>
            <div class="px-6 py-5">
              <slot />
            </div>
            <footer
              v-if="$slots.footer"
              class="px-6 py-4 border-t border-border bg-bg/60 rounded-b-lg"
            >
              <slot name="footer" />
            </footer>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

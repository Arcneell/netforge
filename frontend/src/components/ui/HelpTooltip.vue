<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue'
import { HelpCircle } from 'lucide-vue-next'

/**
 * Tiny "?" affordance that surfaces contextual help on hover, focus, or
 * tap. Use it next to a complex field label or section title to keep the
 * default UI uncluttered while still offering an explanation one
 * interaction away.
 *
 * Usage:
 *   <HelpTooltip :text="t('subnet.cidrHint')" />
 *
 * Long-form content (paragraphs) is supported via the default slot:
 *   <HelpTooltip>
 *     <p>First paragraph…</p>
 *     <p>Second paragraph…</p>
 *   </HelpTooltip>
 *
 * The tooltip is keyboard-accessible: focus the button to open it, blur
 * or press Escape to close. On touch devices a tap toggles open/close.
 */

const props = withDefaults(
  defineProps<{
    /** Short single-line text. Ignored when a default slot is provided. */
    text?: string
    /** Where to anchor the bubble relative to the trigger. */
    placement?: 'top' | 'bottom' | 'left' | 'right'
    /** Accessible label for the trigger — defaults to a generic "help". */
    label?: string
    /** Inline (default) sits flush with surrounding text; `block` adds a
     *  tiny left margin so it doesn't collide with form-field labels. */
    inline?: boolean
  }>(),
  {
    placement: 'top',
    inline: true,
  },
)

const open = ref(false)
const tooltipId = useId()
const triggerRef = ref<HTMLButtonElement | null>(null)

function show() {
  open.value = true
}
function hide() {
  open.value = false
}
function toggle() {
  open.value = !open.value
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) {
    e.stopPropagation()
    hide()
    triggerRef.value?.blur()
  }
}

// Close when clicking elsewhere — without this, tapping the trigger on
// touch leaves the bubble lingering until the next interaction.
function onDocClick(e: MouseEvent) {
  if (!open.value) return
  if (triggerRef.value && !triggerRef.value.contains(e.target as Node)) {
    hide()
  }
}
if (typeof window !== 'undefined') {
  window.addEventListener('click', onDocClick)
}
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('click', onDocClick)
  }
})

const placementClass = computed(() => {
  switch (props.placement) {
    case 'bottom':
      return 'top-full mt-2 left-1/2 -translate-x-1/2'
    case 'left':
      return 'right-full mr-2 top-1/2 -translate-y-1/2'
    case 'right':
      return 'left-full ml-2 top-1/2 -translate-y-1/2'
    case 'top':
    default:
      return 'bottom-full mb-2 left-1/2 -translate-x-1/2'
  }
})
</script>

<template>
  <span :class="['relative', inline ? 'inline-flex' : 'inline-flex ml-1']">
    <button
      ref="triggerRef"
      type="button"
      class="inline-flex items-center justify-center w-4 h-4 rounded-full text-fg-muted hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 transition-colors"
      :aria-label="label ?? 'Help'"
      :aria-describedby="open ? tooltipId : undefined"
      :aria-expanded="open"
      @mouseenter="show"
      @mouseleave="hide"
      @focus="show"
      @blur="hide"
      @click.stop="toggle"
      @keydown="onKey"
    >
      <HelpCircle class="w-3.5 h-3.5" aria-hidden="true" />
    </button>
    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition duration-75 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <span
        v-if="open"
        :id="tooltipId"
        role="tooltip"
        :class="[
          'absolute z-30 w-64 max-w-[16rem] p-2.5 rounded-md shadow-lg',
          'bg-zinc-900 text-zinc-50 dark:bg-zinc-800 dark:text-zinc-100',
          'text-xs leading-relaxed font-normal whitespace-normal text-left',
          'pointer-events-none',
          placementClass,
        ]"
      >
        <slot>{{ text }}</slot>
      </span>
    </Transition>
  </span>
</template>

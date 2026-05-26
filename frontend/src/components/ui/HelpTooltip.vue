<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
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
 * The tooltip bubble is portalled to `<body>` so it escapes any parent
 * stacking context — without this the AppTopbar (`position: sticky`,
 * which forces a stacking context) clipped tooltips anchored on page
 * headers. Position is computed from the trigger's bounding rect, so
 * the bubble follows the trigger even when teleported elsewhere in the
 * DOM tree.
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

// Absolute viewport coordinates for the portalled bubble. Computed from
// the trigger's getBoundingClientRect() the moment the tooltip opens,
// and updated again if the window resizes or the user scrolls while the
// bubble is open. We use `position: fixed`, so these are viewport
// coords directly — no document offset math needed.
const bubblePos = ref({ top: 0, left: 0 })

// Gap between trigger and bubble — matches the previous `mb-2 / mt-2`
// spacing so the visual feel doesn't change after the teleport.
const GAP_PX = 8

function updatePosition() {
  const trigger = triggerRef.value
  if (!trigger) return
  const r = trigger.getBoundingClientRect()
  switch (props.placement) {
    case 'bottom':
      bubblePos.value = {
        top: r.bottom + GAP_PX,
        left: r.left + r.width / 2,
      }
      return
    case 'left':
      bubblePos.value = { top: r.top + r.height / 2, left: r.left - GAP_PX }
      return
    case 'right':
      bubblePos.value = { top: r.top + r.height / 2, left: r.right + GAP_PX }
      return
    case 'top':
    default:
      bubblePos.value = {
        top: r.top - GAP_PX,
        left: r.left + r.width / 2,
      }
  }
}

// Re-anchor when the page reflows around an open tooltip (resize,
// scroll, sidebar collapse, etc). Listeners are only attached while the
// bubble is actually open so we don't burn cycles on every idle scroll.
function onReflow() {
  if (open.value) updatePosition()
}

watch(open, async (isOpen) => {
  if (isOpen) {
    await nextTick()
    updatePosition()
    if (typeof window !== 'undefined') {
      window.addEventListener('scroll', onReflow, true)
      window.addEventListener('resize', onReflow)
    }
  } else if (typeof window !== 'undefined') {
    window.removeEventListener('scroll', onReflow, true)
    window.removeEventListener('resize', onReflow)
  }
})

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
    window.removeEventListener('scroll', onReflow, true)
    window.removeEventListener('resize', onReflow)
  }
})

// Transform offset that recenters the bubble relative to its anchor
// point. The `top` placement uses `translate(-50%, -100%)` so the
// computed `left = trigger center`, `top = trigger top - gap` lands the
// bubble's bottom-centre on the gap; `bottom` mirrors that.
const bubbleTransform = computed(() => {
  switch (props.placement) {
    case 'bottom':
      return 'translate(-50%, 0)'
    case 'left':
      return 'translate(-100%, -50%)'
    case 'right':
      return 'translate(0, -50%)'
    case 'top':
    default:
      return 'translate(-50%, -100%)'
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
    <!-- Teleport to body so we render outside any sticky / transformed
         ancestor stacking context. Z-index 50 puts it above the topbar
         (z-10) and every modal backdrop currently in the design system. -->
    <Teleport to="body">
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
            'fixed z-50 w-64 max-w-[16rem] p-2.5 rounded-md shadow-lg',
            'bg-zinc-900 text-zinc-50 dark:bg-zinc-800 dark:text-zinc-100',
            'text-xs leading-relaxed font-normal whitespace-normal text-left',
            'pointer-events-none',
          ]"
          :style="{
            top: bubblePos.top + 'px',
            left: bubblePos.left + 'px',
            transform: bubbleTransform,
          }"
        >
          <slot>{{ text }}</slot>
        </span>
      </Transition>
    </Teleport>
  </span>
</template>

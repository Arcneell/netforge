<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { HelpCircle } from 'lucide-vue-next'

/**
 * Tiny "?" affordance that surfaces contextual help on hover, focus, or
 * tap. Use it next to a complex field label or section title to keep the
 * default UI uncluttered while still offering an explanation one
 * interaction away.
 *
 * Usage:
 *   <HelpTooltip :text="t('subnet.help.cidr')" />
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
    text: undefined,
    label: undefined,
    placement: 'top',
    inline: true,
  },
)

const open = ref(false)
const tooltipId = useId()
const triggerRef = ref<HTMLButtonElement | null>(null)

// Viewport coordinates for the portalled bubble + the effective
// placement (which may differ from the requested `placement` prop when
// auto-flipping near a viewport edge). Computed from the trigger's
// getBoundingClientRect() on open, refreshed on scroll / resize while
// the bubble is visible.
const bubblePos = ref({ top: 0, left: 0 })
const effectivePlacement = ref<'top' | 'bottom' | 'left' | 'right'>('top')

// Bubble dimensions — width matches the `w-64 max-w-[16rem]` Tailwind
// classes (256 px). Height is unknown until the content renders, but
// 220 px is a safe upper bound for the longest tooltip we have today
// and is only used to decide whether to flip top↔bottom.
const BUBBLE_W = 256
const APPROX_BUBBLE_H = 220
const GAP_PX = 8
const VIEWPORT_PAD = 8

function clampHorizontal(idealLeft: number, vw: number): number {
  // Keep the bubble's left edge inside the viewport. Errs on the
  // right-shift side when both clamps would fight (narrow viewport),
  // which matches what the user expects: tooltip stays visible.
  const minLeft = VIEWPORT_PAD
  const maxLeft = Math.max(minLeft, vw - BUBBLE_W - VIEWPORT_PAD)
  return Math.max(minLeft, Math.min(maxLeft, idealLeft))
}

function updatePosition() {
  const trigger = triggerRef.value
  if (!trigger) return
  const r = trigger.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  const centerX = r.left + r.width / 2

  let place = props.placement
  // Auto-flip top→bottom (and vice versa) when there isn't enough room
  // on the requested side. Left/right placement keeps the request — the
  // bubble would extend horizontally far enough that flipping rarely
  // helps in practice for our use cases.
  if (place === 'top' && r.top < APPROX_BUBBLE_H + GAP_PX + VIEWPORT_PAD) {
    place = 'bottom'
  } else if (place === 'bottom' && vh - r.bottom < APPROX_BUBBLE_H + GAP_PX + VIEWPORT_PAD) {
    place = 'top'
  }
  effectivePlacement.value = place

  switch (place) {
    case 'bottom':
      bubblePos.value = {
        top: r.bottom + GAP_PX,
        left: clampHorizontal(centerX - BUBBLE_W / 2, vw),
      }
      return
    case 'left':
      bubblePos.value = {
        top: r.top + r.height / 2,
        left: Math.max(VIEWPORT_PAD, r.left - GAP_PX - BUBBLE_W),
      }
      return
    case 'right':
      bubblePos.value = {
        top: r.top + r.height / 2,
        left: Math.min(vw - BUBBLE_W - VIEWPORT_PAD, r.right + GAP_PX),
      }
      return
    case 'top':
    default:
      bubblePos.value = {
        top: r.top - GAP_PX,
        left: clampHorizontal(centerX - BUBBLE_W / 2, vw),
      }
  }
}

// Re-anchor when the page reflows around an open tooltip (resize,
// scroll, sidebar collapse, etc). Listeners are only attached while the
// bubble is actually open so we don't burn cycles on every idle scroll.
function onReflow() {
  if (open.value) updatePosition()
}

// Idempotency flag for the reflow listeners. A fast hover-flicker can
// toggle `open` faster than Vue batches the watcher; without a guard,
// addEventListener can fire twice before removeEventListener catches
// up, accumulating one stale handler per cycle. Every page renders
// many HelpTooltips — at scale that adds measurable scroll work.
let reflowAttached = false

watch(open, async (isOpen) => {
  if (isOpen) {
    await nextTick()
    updatePosition()
    if (typeof window !== 'undefined' && !reflowAttached) {
      window.addEventListener('scroll', onReflow, true)
      window.addEventListener('resize', onReflow)
      reflowAttached = true
    }
  } else if (typeof window !== 'undefined' && reflowAttached) {
    window.removeEventListener('scroll', onReflow, true)
    window.removeEventListener('resize', onReflow)
    reflowAttached = false
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
// Register listeners on mount (paired with the onBeforeUnmount removal
// below) so we don't accumulate handlers on components that get
// constructed but never mounted — Suspense rejections, async-setup
// errors, and `<Transition>` race conditions all leave script-setup
// to run while the component never lands in the DOM. Every page has
// dozens of HelpTooltips, so an unpaired window-level click handler
// matters at scale.
onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener('click', onDocClick)
  }
})
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('click', onDocClick)
    if (reflowAttached) {
      window.removeEventListener('scroll', onReflow, true)
      window.removeEventListener('resize', onReflow)
      reflowAttached = false
    }
  }
})

// Transform offset that finishes positioning the bubble. `updatePosition`
// has already done the heavy lifting horizontally — `left` is the
// clamped left-edge coordinate, no transform needed on the X axis.
// Vertical: top placement raises the bubble by 100 % of its own
// height; left/right centre vertically on the trigger.
const bubbleTransform = computed(() => {
  switch (effectivePlacement.value) {
    case 'bottom':
      return 'translate(0, 0)'
    case 'left':
    case 'right':
      return 'translate(0, -50%)'
    case 'top':
    default:
      return 'translate(0, -100%)'
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
            'fixed z-50 w-64 max-w-[16rem] p-3 rounded-lg shadow-lg',
            // Dark chip on light, a bordered surface on dark — a near-black
            // bubble on a near-black page would disappear.
            'bg-zinc-900 text-zinc-100 dark:bg-surface dark:text-fg dark:border dark:border-border',
            'text-sm leading-relaxed font-normal whitespace-normal text-left',
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

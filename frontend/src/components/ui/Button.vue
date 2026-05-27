<script setup lang="ts">
import { computed } from 'vue'
import { Loader2 } from 'lucide-vue-next'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'
type Shape = 'rounded' | 'pill'

const props = withDefaults(
  defineProps<{
    variant?: Variant
    size?: Size
    /**
     * `pill` switches to a fully rounded capsule — the iOS look for primary
     * CTAs ("Create", "Save"). `rounded` keeps the standard 10 px corners
     * used by inline toolbar / icon buttons.
     */
    shape?: Shape
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    loading?: boolean
    block?: boolean
    ariaLabel?: string
  }>(),
  {
    variant: 'primary',
    size: 'md',
    shape: 'rounded',
    type: 'button',
    disabled: false,
    loading: false,
    block: false,
    ariaLabel: undefined,
  },
)

defineEmits<{ (e: 'click', ev: MouseEvent): void }>()

const variantClasses: Record<Variant, string> = {
  // Primary now uses a softer "gel" gradient + a tiny inner highlight for the
  // iOS pill feel. Active state scales down slightly for tactile feedback.
  primary:
    'bg-primary-600 hover:bg-primary-500 active:bg-primary-700 text-white border-primary-600/0 ' +
    'shadow-[0_1px_0_0_rgb(255_255_255_/_0.18)_inset,0_4px_12px_-4px_rgb(var(--color-primary-500)/_0.45)] ' +
    'hover:shadow-[0_1px_0_0_rgb(255_255_255_/_0.22)_inset,0_8px_18px_-4px_rgb(var(--color-primary-500)/_0.55)]',
  // Secondary is a soft surface tile — borderless on light mode (relies on
  // background contrast against bg) for the iOS "card" look.
  secondary:
    'bg-surface hover:bg-surface-hover active:bg-muted text-fg border-border/70 dark:border-border/40 shadow-sm',
  ghost:
    'bg-transparent hover:bg-surface-hover active:bg-muted text-fg-muted hover:text-fg border-transparent',
  danger:
    'bg-danger hover:bg-red-500 active:bg-red-700 text-white border-danger/0 ' +
    'shadow-[0_1px_0_0_rgb(255_255_255_/_0.18)_inset,0_4px_12px_-4px_rgb(var(--color-danger)/_0.45)]',
}

const sizeClasses: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-4 text-sm gap-2',
  lg: 'h-11 px-6 text-base gap-2',
}

const classes = computed(() => [
  'inline-flex items-center justify-center font-medium border',
  'transition-[background-color,border-color,box-shadow,color,transform] duration-150 ease-out',
  'active:scale-[0.98]',
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
  'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none disabled:active:scale-100',
  props.shape === 'pill' ? 'rounded-full' : 'rounded-md',
  variantClasses[props.variant],
  sizeClasses[props.size],
  props.block ? 'w-full' : '',
])
</script>

<template>
  <button
    :type="type"
    :class="classes"
    :disabled="disabled || loading"
    :aria-label="ariaLabel"
    :aria-busy="loading"
    @click="$emit('click', $event)"
  >
    <Loader2 v-if="loading" class="w-4 h-4 animate-spin" aria-hidden="true" />
    <slot />
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Loader2 } from 'lucide-vue-next'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const props = withDefaults(
  defineProps<{
    variant?: Variant
    size?: Size
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    loading?: boolean
    block?: boolean
    ariaLabel?: string
  }>(),
  {
    variant: 'primary',
    size: 'md',
    type: 'button',
    disabled: false,
    loading: false,
    block: false,
  },
)

defineEmits<{ (e: 'click', ev: MouseEvent): void }>()

const variantClasses: Record<Variant, string> = {
  // Primary uses a slight gradient + a subtle inset highlight so the indigo
  // doesn't look flat. The hover state pushes one stop darker rather than
  // shifting hue, which keeps the brand colour consistent across pages.
  primary:
    'bg-primary-600 hover:bg-primary-700 active:bg-primary-700 text-white border-primary-600 hover:border-primary-700 shadow-sm shadow-primary-600/20',
  // Secondary is hairline-bordered "ghost with edges" — sits well next to a
  // primary on a toolbar without competing visually.
  secondary: 'bg-surface hover:bg-surface-hover active:bg-muted text-fg border-border shadow-sm',
  // Ghost has no border or shadow; reserved for tertiary actions inside dense
  // tables (icon-only edit / delete) where chrome would be noise.
  ghost: 'bg-transparent hover:bg-surface-hover active:bg-muted text-fg border-transparent',
  // Danger mirrors primary's gradient strategy so confirm-destructive dialogs
  // get the same visual weight as a primary CTA.
  danger:
    'bg-danger hover:bg-red-600 active:bg-red-700 text-white border-danger shadow-sm shadow-danger/20',
}

const sizeClasses: Record<Size, string> = {
  // sm sits a hair under standard input height so an icon button next to an
  // Input doesn't look top-heavy. md matches Input (h-9).
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-3.5 text-sm gap-2',
  lg: 'h-11 px-5 text-base gap-2',
}

const classes = computed(() => [
  'inline-flex items-center justify-center font-medium rounded-md border',
  'transition-[background-color,border-color,box-shadow,color] duration-150 ease-out',
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
  'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none',
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

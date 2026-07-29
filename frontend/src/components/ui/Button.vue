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
    ariaLabel: undefined,
  },
)

defineEmits<{ (e: 'click', ev: MouseEvent): void }>()

// Square, flush, with a single line of light on the bottom lip — a panel
// button, not a floating pill. The accent is deep enough (primary-700) to carry
// white text at 7:1, which is what lets it stay the only saturated thing on a
// page full of grey.
const variantClasses: Record<Variant, string> = {
  primary:
    'bg-primary-700 hover:bg-primary-800 text-white border-transparent shadow-xs ' +
    'dark:bg-primary-600 dark:hover:bg-primary-500',
  secondary:
    'bg-surface hover:bg-surface-hover text-fg border-border-strong shadow-xs ' +
    'dark:bg-surface dark:hover:bg-surface-hover',
  ghost: 'bg-transparent hover:bg-surface-hover text-fg-muted hover:text-fg border-transparent',
  danger: 'bg-danger hover:brightness-95 text-white border-transparent shadow-xs',
}

const sizeClasses: Record<Size, string> = {
  sm: 'h-8 px-2.5 text-sm gap-1.5',
  md: 'h-9 px-3.5 text-base gap-2',
  lg: 'h-10 px-4 text-base gap-2',
}

const classes = computed(() => [
  'inline-flex items-center justify-center font-medium border rounded-md',
  'transition-[background-color,border-color,box-shadow,color,filter,transform] duration-150 ease-panel',
  // The press. A real button travels; 1px is enough to feel it and little
  // enough that it never disturbs the row it sits in.
  'active:translate-y-px active:shadow-none',
  'focus:outline-none focus-visible:outline-none focus-visible:shadow-ring focus-visible:border-primary-600',
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

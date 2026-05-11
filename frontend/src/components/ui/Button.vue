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
  primary:
    'bg-primary-600 hover:bg-primary-700 text-white border-primary-600 hover:border-primary-700',
  secondary: 'bg-surface hover:bg-surface-hover text-fg border-border',
  ghost: 'bg-transparent hover:bg-surface-hover text-fg border-transparent',
  danger: 'bg-danger hover:bg-red-600 text-white border-danger',
}

const sizeClasses: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-4 text-sm gap-2',
  lg: 'h-11 px-5 text-base gap-2',
}

const classes = computed(() => [
  'inline-flex items-center justify-center font-medium rounded-md border transition',
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-bg',
  'disabled:opacity-50 disabled:cursor-not-allowed',
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

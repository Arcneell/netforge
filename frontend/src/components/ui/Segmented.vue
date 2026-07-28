<script setup lang="ts" generic="T extends string | number">
import type { Component } from 'vue'

/**
 * Two-or-three-way view switch. The subnet, switch, insights and settings
 * pages each grew their own copy of this control; this is the one they all
 * use now, so a toggle looks and behaves the same wherever it appears.
 */
export interface SegmentedOption<V> {
  value: V
  label: string
  icon?: Component
  /** Optional trailing count, e.g. the number of rows behind the tab. */
  count?: number | string
}

defineProps<{
  modelValue: T
  options: SegmentedOption<T>[]
  ariaLabel?: string
}>()

defineEmits<{ (e: 'update:modelValue', v: T): void }>()
</script>

<template>
  <div class="nf-segmented" role="group" :aria-label="ariaLabel">
    <button
      v-for="opt in options"
      :key="String(opt.value)"
      type="button"
      :aria-pressed="modelValue === opt.value"
      :class="['nf-segmented-item', modelValue === opt.value ? 'nf-segmented-item-active' : '']"
      @click="$emit('update:modelValue', opt.value)"
    >
      <component
        :is="opt.icon"
        v-if="opt.icon"
        class="w-3.5 h-3.5 flex-shrink-0"
        :stroke-width="1.9"
        aria-hidden="true"
      />
      {{ opt.label }}
      <span v-if="opt.count !== undefined" class="text-fg-subtle tabular-nums">
        {{ opt.count }}
      </span>
    </button>
  </div>
</template>

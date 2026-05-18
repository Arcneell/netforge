<script setup lang="ts" generic="T extends string | number">
import { ChevronDown } from 'lucide-vue-next'

interface Option {
  value: T
  label: string
}

defineProps<{
  modelValue: T
  options: Option[]
  disabled?: boolean
  id?: string
  ariaLabel?: string
}>()

defineEmits<{ (e: 'update:modelValue', v: T): void }>()
</script>

<template>
  <div class="relative inline-block w-full">
    <select
      :id="id"
      :value="modelValue"
      :disabled="disabled"
      :aria-label="ariaLabel"
      class="nf-input appearance-none pr-9 cursor-pointer hover:border-fg-muted/40 transition-colors"
      @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value as T)"
    >
      <option v-for="opt in options" :key="String(opt.value)" :value="opt.value">
        {{ opt.label }}
      </option>
    </select>
    <ChevronDown
      class="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-muted pointer-events-none"
      aria-hidden="true"
    />
  </div>
</template>

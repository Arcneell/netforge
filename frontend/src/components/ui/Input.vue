<script setup lang="ts">
import { computed, useAttrs } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue?: string | number
    type?: string
    placeholder?: string
    disabled?: boolean
    invalid?: boolean
    id?: string
  }>(),
  {
    type: 'text',
    disabled: false,
    invalid: false,
  },
)

defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const attrs = useAttrs()

const classes = computed(() => [
  'nf-input',
  props.invalid ? 'border-danger focus:ring-danger/40 focus:border-danger' : '',
])
</script>

<template>
  <input
    :id="id"
    v-bind="attrs"
    :type="type"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :aria-invalid="invalid || undefined"
    :class="classes"
    @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>

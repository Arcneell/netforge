<script setup lang="ts">
import { useAttrs } from 'vue'

withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    disabled?: boolean
    rows?: number
    invalid?: boolean
    id?: string
  }>(),
  {
    modelValue: '',
    placeholder: undefined,
    disabled: false,
    invalid: false,
    rows: 3,
    id: undefined,
  },
)

defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const attrs = useAttrs()
</script>

<template>
  <textarea
    :id="id"
    v-bind="attrs"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :rows="rows"
    :aria-invalid="invalid || undefined"
    :class="['nf-input resize-y leading-relaxed', invalid ? 'nf-input-invalid' : '']"
    @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>

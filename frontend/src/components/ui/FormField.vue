<script setup lang="ts">
import { computed, useId } from 'vue'

const props = withDefaults(
  defineProps<{
    label?: string
    hint?: string
    error?: string | null
    required?: boolean
    /** Optional explicit id; otherwise we autogenerate via Vue's useId. */
    fieldId?: string
  }>(),
  { required: false },
)

const autoId = useId()
const id = computed(() => props.fieldId ?? `field-${autoId}`)
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <label
      v-if="label || $slots.help"
      :for="id"
      class="text-xs font-medium text-fg-muted flex items-center gap-1"
    >
      <span>{{ label }}</span>
      <span v-if="required" class="text-danger" aria-hidden="true">*</span>
      <!-- Optional `?` tooltip — used for fields whose syntax / semantics
           aren't obvious from the label alone (CIDR, event patterns, …). -->
      <slot name="help" />
    </label>
    <slot :id="id" :invalid="!!error" />
    <p v-if="error" class="text-xs text-danger" role="alert">{{ error }}</p>
    <p v-else-if="hint" class="text-xs text-fg-muted">{{ hint }}</p>
  </div>
</template>

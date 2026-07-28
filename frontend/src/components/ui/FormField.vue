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
  {
    label: undefined,
    hint: undefined,
    error: null,
    required: false,
    fieldId: undefined,
  },
)

const autoId = useId()
const id = computed(() => props.fieldId ?? `field-${autoId}`)
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <!-- Label + optional `?` tooltip live in the same flex row so they
         render side-by-side, but the tooltip's `<button>` trigger sits
         OUTSIDE the `<label>` element. Nesting the trigger inside the
         label made clicking `?` also focus the associated input (label's
         default behaviour), which in Safari blurs the tooltip immediately
         and on other browsers steals focus from the help bubble. -->
    <div v-if="label || $slots.help" class="flex items-center gap-1 text-base font-medium text-fg">
      <label v-if="label" :for="id" class="flex items-center gap-1">
        <span>{{ label }}</span>
        <span v-if="required" class="text-danger" aria-hidden="true">*</span>
      </label>
      <slot name="help" />
    </div>
    <slot :id="id" :invalid="!!error" />
    <p v-if="error" class="text-xs text-danger" role="alert">{{ error }}</p>
    <p v-else-if="hint" class="text-xs text-fg-muted">{{ hint }}</p>
  </div>
</template>

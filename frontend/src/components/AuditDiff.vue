<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  changes: Record<string, unknown> | null
}>()

const { t } = useI18n()

interface FieldDiff {
  field: string
  before: unknown
  after: unknown
}

/**
 * The audit `changes` payload is loosely typed (the backend writes whatever it
 * recorded — typically `{ field: { before, after } }`). Normalize what we can
 * and fall back to a JSON view for unknown shapes.
 */
const diffs = computed<FieldDiff[]>(() => {
  if (!props.changes || typeof props.changes !== 'object') return []
  const out: FieldDiff[] = []
  for (const [field, value] of Object.entries(props.changes)) {
    if (
      value &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      ('before' in value || 'after' in value)
    ) {
      const v = value as { before?: unknown; after?: unknown }
      out.push({ field, before: v.before, after: v.after })
    } else {
      // For create/delete entries, "changes" may be the full row — treat each
      // top-level key as a single-sided change (no before / new after).
      out.push({ field, before: undefined, after: value })
    }
  }
  return out
})

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}
</script>

<template>
  <div v-if="diffs.length === 0" class="text-sm text-fg-muted italic">
    {{ t('audit.noChanges') }}
  </div>
  <div v-else class="space-y-2">
    <div
      v-for="d in diffs"
      :key="d.field"
      class="grid grid-cols-[8rem_1fr_1fr] gap-2 text-sm border border-border rounded p-2"
    >
      <span class="font-mono text-xs text-fg-muted self-center">{{ d.field }}</span>
      <div class="flex flex-col gap-0.5 min-w-0">
        <span class="text-[10px] uppercase tracking-wide text-fg-muted">
          {{ t('audit.before') }}
        </span>
        <span class="font-mono text-xs text-fg break-words whitespace-pre-wrap">
          {{ fmt(d.before) }}
        </span>
      </div>
      <div class="flex flex-col gap-0.5 min-w-0">
        <span class="text-[10px] uppercase tracking-wide text-fg-muted">
          {{ t('audit.after') }}
        </span>
        <span class="font-mono text-xs text-fg break-words whitespace-pre-wrap">
          {{ fmt(d.after) }}
        </span>
      </div>
    </div>
  </div>
</template>

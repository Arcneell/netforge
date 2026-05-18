<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight } from 'lucide-vue-next'
import type { AuditAction } from '@/api'

const props = withDefaults(
  defineProps<{
    changes: Record<string, unknown> | null
    /**
     * Drives the layout: 'create' only highlights the "after" side, 'delete'
     * only the "before" side, and 'update' shows both with the change arrow.
     * When omitted we infer from the shape of each row (a row with no `before`
     * key is treated as a create-side, etc.).
     */
    action?: AuditAction
  }>(),
  { action: undefined },
)

const { t } = useI18n()

interface FieldDiff {
  field: string
  hasBefore: boolean
  hasAfter: boolean
  before: unknown
  after: unknown
}

/**
 * Normalize the loosely-typed `changes` payload. The backend writes one of:
 *   - `{ field: { before, after } }`  (an update)
 *   - `{ field: value }`              (single-sided: create or delete row)
 *
 * Each row exposes `hasBefore` / `hasAfter` so the template can hide a side
 * cleanly instead of rendering "—" placeholders.
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
      out.push({
        field,
        hasBefore: 'before' in v,
        hasAfter: 'after' in v,
        before: v.before,
        after: v.after,
      })
    } else {
      // Single-sided: assume "after" for create, "before" for delete; fall back
      // to "after" when action is unknown — that matches the previous behaviour.
      const side: 'before' | 'after' = props.action === 'delete' ? 'before' : 'after'
      out.push({
        field,
        hasBefore: side === 'before',
        hasAfter: side === 'after',
        before: side === 'before' ? value : undefined,
        after: side === 'after' ? value : undefined,
      })
    }
  }
  return out
})

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  // Objects / arrays — pretty-print so multi-line payloads stay readable.
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

// When the whole payload is single-sided (every row only has `after`, or only
// `before`), suppress the arrow column so the visible side fills the row.
const onlyCreate = computed(() => diffs.value.every((d) => d.hasAfter && !d.hasBefore))
const onlyDelete = computed(() => diffs.value.every((d) => d.hasBefore && !d.hasAfter))
const isSingleSided = computed(() => onlyCreate.value || onlyDelete.value)
</script>

<template>
  <div v-if="diffs.length === 0" class="text-sm text-fg-muted italic">
    {{ t('audit.noChanges') }}
  </div>
  <div v-else class="space-y-2">
    <div
      v-for="d in diffs"
      :key="d.field"
      class="nf-card overflow-hidden"
      :class="isSingleSided ? '' : ''"
    >
      <!-- Field name header -->
      <div class="px-3 py-1.5 bg-muted/60 border-b border-border flex items-center justify-between">
        <span class="font-mono text-xs text-fg">{{ d.field }}</span>
      </div>

      <!-- Diff body. Two columns + arrow on >= md, stacked under that. -->
      <div
        class="grid gap-0 divide-y md:divide-y-0 md:divide-x divide-border"
        :class="
          isSingleSided ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-[1fr_auto_1fr] md:items-stretch'
        "
      >
        <!-- BEFORE -->
        <div
          v-if="d.hasBefore || !isSingleSided"
          class="p-3 min-w-0"
          :class="
            d.hasBefore ? 'bg-danger/5 dark:bg-danger/10 border-l-2 border-danger/40' : 'bg-surface'
          "
        >
          <p
            class="text-[10px] uppercase tracking-wide mb-1"
            :class="d.hasBefore ? 'text-danger/80' : 'text-fg-muted'"
          >
            {{ t('audit.before') }}
          </p>
          <pre
            v-if="d.hasBefore"
            class="font-mono text-xs text-fg whitespace-pre-wrap break-words m-0"
            >{{ fmt(d.before) }}</pre
          >
          <span v-else class="text-fg-muted text-xs italic">—</span>
        </div>

        <!-- Arrow -->
        <div
          v-if="!isSingleSided"
          class="hidden md:flex items-center justify-center px-2 bg-surface text-fg-muted"
          aria-hidden="true"
        >
          <ArrowRight class="w-4 h-4" />
        </div>

        <!-- AFTER -->
        <div
          v-if="d.hasAfter || !isSingleSided"
          class="p-3 min-w-0"
          :class="
            d.hasAfter
              ? 'bg-success/5 dark:bg-success/10 border-l-2 border-success/40'
              : 'bg-surface'
          "
        >
          <p
            class="text-[10px] uppercase tracking-wide mb-1"
            :class="d.hasAfter ? 'text-success/90' : 'text-fg-muted'"
          >
            {{ t('audit.after') }}
          </p>
          <pre
            v-if="d.hasAfter"
            class="font-mono text-xs text-fg whitespace-pre-wrap break-words m-0"
            >{{ fmt(d.after) }}</pre
          >
          <span v-else class="text-fg-muted text-xs italic">—</span>
        </div>
      </div>
    </div>
  </div>
</template>

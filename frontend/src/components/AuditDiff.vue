<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight } from '@lucide/vue'
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

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}

/**
 * Normalize the loosely-typed `changes` payload. The backend (see
 * `backend/app/services/audit.py`) writes one of:
 *   - create: `{ "after":  { col_a: val, col_b: val, ... } }`
 *   - update: `{ "before": { col_a: old, ... }, "after": { col_a: new, ... } }`
 *   - delete: `{ "before": { col_a: val, ... } }`
 *
 * The top-level keys are `before` / `after`, NOT field names — we pivot the
 * payload so each row is keyed by the changed column with its before / after
 * pulled from the matching map.
 *
 * For backwards compatibility we still accept the legacy per-field shape
 * (`{ field: { before, after } }`) and a flat single-sided shape
 * (`{ field: value }`).
 */
const diffs = computed<FieldDiff[]>(() => {
  if (!isPlainObject(props.changes)) return []

  const payload = props.changes
  const topLevelBefore = isPlainObject(payload.before) ? payload.before : null
  const topLevelAfter = isPlainObject(payload.after) ? payload.after : null

  // Real backend shape: top-level `before` / `after` maps. Pivot column-wise.
  if (topLevelBefore || topLevelAfter) {
    const keys = new Set<string>()
    if (topLevelBefore) for (const k of Object.keys(topLevelBefore)) keys.add(k)
    if (topLevelAfter) for (const k of Object.keys(topLevelAfter)) keys.add(k)
    const out: FieldDiff[] = []
    for (const field of keys) {
      const hasBefore = !!topLevelBefore && field in topLevelBefore
      const hasAfter = !!topLevelAfter && field in topLevelAfter
      const before = hasBefore ? topLevelBefore![field] : undefined
      const after = hasAfter ? topLevelAfter![field] : undefined
      // Suppress rows where both sides were recorded but the value did not
      // actually change — the backend already filters these for `_on_update`,
      // but full snapshots from create / delete legacy rows may still include
      // unchanged scalar columns; nothing useful to display in that case.
      if (hasBefore && hasAfter && JSON.stringify(before) === JSON.stringify(after)) continue
      out.push({ field, hasBefore, hasAfter, before, after })
    }
    return out
  }

  // Legacy fallbacks. Each top-level entry is either a per-field { before,
  // after } envelope or a flat single-sided value.
  const out: FieldDiff[] = []
  for (const [field, value] of Object.entries(payload)) {
    if (isPlainObject(value) && ('before' in value || 'after' in value)) {
      out.push({
        field,
        hasBefore: 'before' in value,
        hasAfter: 'after' in value,
        before: value.before,
        after: value.after,
      })
    } else {
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

  <!-- One card holding every changed field, hairline-separated. Reading a diff
       is a scan down a single column of field names, not a stack of six
       floating cards. -->
  <div v-else class="nf-card overflow-hidden">
    <div
      v-for="(d, i) in diffs"
      :key="d.field"
      :class="i > 0 ? 'border-t border-border' : ''"
      class="min-w-0"
    >
      <!-- Field name header -->
      <div class="px-3 py-1.5 bg-muted flex items-center gap-2">
        <span class="font-mono text-xs text-fg break-all">{{ d.field }}</span>
      </div>

      <!-- Diff body. Two columns + arrow on >= md, stacked under that.
           Both sides are tinted with the status tokens at low alpha so the
           payload text keeps its contrast on the dark theme. -->
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
            d.hasBefore
              ? 'bg-danger/5 dark:bg-danger/10 border-l-2 border-danger/50'
              : 'bg-surface border-l-2 border-transparent'
          "
        >
          <p
            class="nf-label mb-1.5 uppercase tracking-wide"
            :class="d.hasBefore ? 'text-danger' : 'text-fg-subtle'"
          >
            {{ t('audit.before') }}
          </p>
          <pre
            v-if="d.hasBefore"
            class="font-mono text-xs text-fg whitespace-pre-wrap break-words m-0 max-h-64 overflow-auto"
            >{{ fmt(d.before) }}</pre
          >
          <span v-else class="text-fg-subtle text-xs italic">—</span>
        </div>

        <!-- Arrow -->
        <div
          v-if="!isSingleSided"
          class="hidden md:flex items-center justify-center px-2 bg-surface text-fg-subtle"
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
              ? 'bg-success/5 dark:bg-success/10 border-l-2 border-success/50'
              : 'bg-surface border-l-2 border-transparent'
          "
        >
          <p
            class="nf-label mb-1.5 uppercase tracking-wide"
            :class="d.hasAfter ? 'text-success' : 'text-fg-subtle'"
          >
            {{ t('audit.after') }}
          </p>
          <pre
            v-if="d.hasAfter"
            class="font-mono text-xs text-fg whitespace-pre-wrap break-words m-0 max-h-64 overflow-auto"
            >{{ fmt(d.after) }}</pre
          >
          <span v-else class="text-fg-subtle text-xs italic">—</span>
        </div>
      </div>
    </div>
  </div>
</template>

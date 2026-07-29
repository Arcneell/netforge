<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import Badge from '@/components/ui/Badge.vue'
import type { ImportErrorRow } from '@/api'

/**
 * Line-by-line rejection list: which row, which column, which value, why.
 * `dense` is the tighter spacing used when the table is nested under a
 * per-file heading in a bulk report.
 */
withDefaults(
  defineProps<{
    rows: ImportErrorRow[]
    dense?: boolean
  }>(),
  { dense: false },
)

const { t } = useI18n()
</script>

<template>
  <div class="overflow-x-auto">
    <table class="w-full text-base">
      <thead>
        <tr class="border-b border-border">
          <th class="nf-label text-right px-4 sm:px-5 w-20" :class="dense ? 'py-2' : 'py-2.5'">
            {{ t('import.report.columns.line') }}
          </th>
          <th class="nf-label text-left px-3 w-36" :class="dense ? 'py-2' : 'py-2.5'">
            {{ t('import.report.columns.column') }}
          </th>
          <th class="nf-label text-left px-3 w-44" :class="dense ? 'py-2' : 'py-2.5'">
            {{ t('import.report.columns.value') }}
          </th>
          <th class="nf-label text-left px-4 sm:px-5" :class="dense ? 'py-2' : 'py-2.5'">
            {{ t('import.report.columns.error') }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(err, i) in rows"
          :key="i"
          class="border-b border-border last:border-0 align-top"
        >
          <td class="px-4 sm:px-5 text-right" :class="dense ? 'py-2' : 'py-2.5'">
            <span class="font-mono text-sm text-fg-muted tabular-nums">{{ err.line }}</span>
          </td>
          <td class="px-3" :class="dense ? 'py-2' : 'py-2.5'">
            <Badge v-if="err.column" tone="neutral" monospace>{{ err.column }}</Badge>
            <span v-else class="text-fg-subtle">—</span>
          </td>
          <td class="px-3 font-mono text-sm text-fg break-all" :class="dense ? 'py-2' : 'py-2.5'">
            <span v-if="err.value">{{ err.value }}</span>
            <span v-else class="text-fg-subtle">—</span>
          </td>
          <td class="px-4 sm:px-5 text-fg" :class="dense ? 'py-2' : 'py-2.5'">
            {{ err.error }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Sparkles, Wand2 } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'
import { aiApi, type CsvMappingResponse, type ImportEntity } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

/**
 * AI-assisted mapping for incoming CSVs whose column names don't match
 * NetForge's canonical headers. The user pastes the first few lines of
 * their CSV; the LLM proposes a `csv_column → netforge_field` mapping.
 *
 * The actual import pipeline still expects canonical headers — this view
 * is informational only. The user rewrites their CSV headers based on the
 * suggestions and runs the existing import.
 */
const props = defineProps<{
  open: boolean
  /** Initial entity to map against. The user can still switch from the
   *  modal's own select. */
  entity: ImportEntity
}>()
const emit = defineEmits<{
  (e: 'close'): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError } = useToast()

const entity = ref<ImportEntity>(props.entity)
const csvText = ref('')
const delimiter = ref<';' | ',' | '\t'>(';')
const running = ref(false)
const result = ref<CsvMappingResponse | null>(null)

watch(
  () => props.open,
  (open) => {
    if (open) {
      entity.value = props.entity
      result.value = null
    }
  },
)

const ENTITIES: ImportEntity[] = [
  'sites',
  'rooms',
  'vlans',
  'subnets',
  'devices',
  'switches',
  'ips',
  'ports',
  'links',
]

/**
 * Parse the pasted CSV body. We pick the first three non-empty lines: line
 * 1 is the header row, the rest are sample rows. We don't run a full RFC-
 * 4180 parser — the operator only needs a *suggestion*, not a complete
 * import. Quoted cells with embedded delimiters can confuse this; the
 * mapping value is still useful because the LLM is robust to noisy input.
 */
const parsed = computed<{ headers: string[]; samples: string[][] } | null>(() => {
  const lines = csvText.value
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  if (!lines.length) return null
  const split = (line: string) => line.split(delimiter.value).map((c) => c.trim())
  const headers = split(lines[0])
  const samples = lines.slice(1, 4).map(split)
  return { headers, samples }
})

const canRun = computed(() => !!parsed.value && parsed.value.headers.length >= 1 && !running.value)

async function run() {
  if (!parsed.value) return
  running.value = true
  result.value = null
  try {
    result.value = await aiApi.suggestCsvMapping({
      entity: entity.value,
      csv_columns: parsed.value.headers,
      sample_rows: parsed.value.samples,
    })
  } catch (err) {
    toastError(describe(err))
  } finally {
    running.value = false
  }
}

function confidenceTone(c: number): 'success' | 'primary' | 'warning' {
  if (c >= 0.8) return 'success'
  if (c >= 0.5) return 'primary'
  return 'warning'
}
</script>

<template>
  <Modal :open="open" :title="t('ai.csvMapping.title')" size="xl" @close="emit('close')">
    <div class="space-y-4">
      <p class="text-sm text-fg-muted leading-relaxed">{{ t('ai.csvMapping.description') }}</p>

      <!-- Entity + delimiter pickers -->
      <div class="grid grid-cols-2 gap-3">
        <label class="text-sm">
          <span class="block text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1">
            {{ t('ai.csvMapping.entity') }}
          </span>
          <select v-model="entity" class="w-full h-9 px-2 rounded border border-border bg-surface">
            <option v-for="e in ENTITIES" :key="e" :value="e">{{ e }}</option>
          </select>
        </label>
        <label class="text-sm">
          <span class="block text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1">
            {{ t('ai.csvMapping.delimiter') }}
          </span>
          <select
            v-model="delimiter"
            class="w-full h-9 px-2 rounded border border-border bg-surface font-mono"
          >
            <option value=";">; (semicolon)</option>
            <option value=",">, (comma)</option>
            <option value="	">↦ (tab)</option>
          </select>
        </label>
      </div>

      <!-- Paste area -->
      <label class="text-sm block">
        <span class="block text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1">
          {{ t('ai.csvMapping.pasteLabel') }}
        </span>
        <textarea
          v-model="csvText"
          rows="6"
          class="w-full p-2 rounded border border-border bg-surface font-mono text-xs leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary-500"
          :placeholder="t('ai.csvMapping.pastePlaceholder')"
        />
      </label>

      <!-- Action -->
      <div class="flex items-center justify-between gap-3 flex-wrap">
        <p v-if="parsed" class="text-xs text-fg-muted tabular-nums">
          {{
            t('ai.csvMapping.parsedHint', {
              cols: parsed.headers.length,
              rows: parsed.samples.length,
            })
          }}
        </p>
        <Button variant="primary" shape="pill" :disabled="!canRun" :loading="running" @click="run">
          <Wand2 class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.csvMapping.suggest') }}
        </Button>
      </div>

      <!-- Result -->
      <div
        v-if="result"
        class="mt-3 pt-3 border-t border-border/70 dark:border-border/40 space-y-3"
      >
        <p class="text-[11px] text-fg-muted tabular-nums">
          {{
            t('ai.csvMapping.resultMeta', {
              provider: result.provider,
              model: result.model,
              latency: result.latency_ms,
            })
          }}
        </p>
        <table class="w-full text-sm">
          <thead>
            <tr class="text-[11px] uppercase tracking-wider text-fg-muted">
              <th class="text-left font-semibold py-1.5">{{ t('ai.csvMapping.colCsv') }}</th>
              <th class="text-left font-semibold py-1.5">{{ t('ai.csvMapping.colTarget') }}</th>
              <th class="text-left font-semibold py-1.5">{{ t('ai.csvMapping.colConfidence') }}</th>
              <th class="text-left font-semibold py-1.5">{{ t('ai.csvMapping.colNotes') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="col in result.columns"
              :key="col.csv_column"
              class="border-t border-border/50 align-top"
            >
              <td class="py-2 font-mono text-xs">{{ col.csv_column }}</td>
              <td class="py-2">
                <span v-if="col.suggested_field" class="font-mono text-xs">
                  {{ col.suggested_field }}
                </span>
                <Badge v-else tone="muted">{{ t('ai.csvMapping.unmapped') }}</Badge>
              </td>
              <td class="py-2">
                <Badge :tone="confidenceTone(col.confidence)">
                  {{ Math.round(col.confidence * 100) }}%
                </Badge>
              </td>
              <td class="py-2 text-xs text-fg-muted">{{ col.notes }}</td>
            </tr>
          </tbody>
        </table>
        <p
          v-if="result.missing_required_fields.length"
          class="text-xs text-warning p-3 rounded bg-warning/10 border border-warning/20"
        >
          <Sparkles class="w-3 h-3 inline-block mr-1" aria-hidden="true" />
          {{
            t('ai.csvMapping.missingFields', {
              fields: result.missing_required_fields.join(', '),
            })
          }}
        </p>
      </div>

      <EmptyState
        v-else-if="!running && !result"
        :icon="Wand2"
        :title="t('ai.csvMapping.emptyTitle')"
        :description="t('ai.csvMapping.emptyDescription')"
        size="sm"
      />
    </div>
  </Modal>
</template>

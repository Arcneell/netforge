<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, Sparkles, Wand2 } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import Select from '@/components/ui/Select.vue'
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
  /** Operator validated the mapping and wants it applied to their next
   *  import. The parent stores the dict and forwards it to the backend
   *  as `column_map` (server-side CSV header rewrite). */
  (e: 'apply', mapping: Record<string, string | null>, entity: ImportEntity): void
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

// Both pickers feed the shared <Select>, which takes a flat options array.
// Computed rather than const so the labels re-derive on a locale switch —
// the entity names are the import API's own identifiers and the delimiter
// glyphs are literal, so nothing translates today, but the arrays stay in
// the right shape if that changes.
const entityOptions = computed<{ value: ImportEntity; label: string }[]>(() =>
  ENTITIES.map((e) => ({ value: e, label: e })),
)

const delimiterOptions = computed<{ value: ';' | ',' | '\t'; label: string }[]>(() => [
  { value: ';', label: '; (semicolon)' },
  { value: ',', label: ', (comma)' },
  { value: '\t', label: '↦ (tab)' },
])

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

function severityTone(s: 'info' | 'warning' | 'critical'): 'danger' | 'warning' | 'primary' {
  return s === 'critical' ? 'danger' : s === 'warning' ? 'warning' : 'primary'
}

/**
 * Pack the current mapping into the `column_map` dict the import endpoint
 * accepts and hand it up. Unmapped columns are stored as `null` so the
 * server-side rewrite drops them — that matches the visible behaviour of
 * the modal (a "—" / muted "unmapped" badge).
 */
function applyMapping() {
  if (!result.value) return
  const mapping: Record<string, string | null> = {}
  for (const c of result.value.columns) {
    mapping[c.csv_column] = c.suggested_field
  }
  emit('apply', mapping, entity.value)
  emit('close')
}
</script>

<template>
  <Modal :open="open" :title="t('ai.csvMapping.title')" size="xl" @close="emit('close')">
    <div class="space-y-4">
      <p class="text-sm text-fg-muted leading-relaxed">{{ t('ai.csvMapping.description') }}</p>

      <!-- Entity + delimiter pickers -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label class="block">
          <span class="nf-label block mb-1">
            {{ t('ai.csvMapping.entity') }}
          </span>
          <Select v-model="entity" :options="entityOptions" />
        </label>
        <label class="block">
          <span class="nf-label block mb-1">
            {{ t('ai.csvMapping.delimiter') }}
          </span>
          <Select v-model="delimiter" :options="delimiterOptions" class="font-mono" />
        </label>
      </div>

      <!-- Paste area -->
      <label class="block">
        <span class="nf-label block mb-1">
          {{ t('ai.csvMapping.pasteLabel') }}
        </span>
        <textarea
          v-model="csvText"
          rows="6"
          class="nf-input font-mono text-xs leading-relaxed resize-y"
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
        <Button variant="primary" :disabled="!canRun" :loading="running" @click="run">
          <Wand2 class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.csvMapping.suggest') }}
        </Button>
      </div>

      <!-- Result -->
      <div v-if="result" class="mt-3 pt-3 border-t border-border space-y-3">
        <p class="text-2xs text-fg-muted tabular-nums">
          {{
            t('ai.csvMapping.resultMeta', {
              provider: result.provider,
              model: result.model,
              latency: result.latency_ms,
            })
          }}
        </p>
        <div class="rounded-lg border border-border overflow-hidden overflow-x-auto">
          <table class="w-full text-base">
            <thead>
              <tr class="bg-muted border-b border-border">
                <th class="nf-label text-left px-3 py-2">{{ t('ai.csvMapping.colCsv') }}</th>
                <th class="nf-label text-left px-3 py-2">{{ t('ai.csvMapping.colTarget') }}</th>
                <th class="nf-label text-left px-3 py-2 w-28">
                  {{ t('ai.csvMapping.colConfidence') }}
                </th>
                <th class="nf-label text-left px-3 py-2">{{ t('ai.csvMapping.colNotes') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="col in result.columns"
                :key="col.csv_column"
                class="border-b border-border last:border-0 align-top"
              >
                <td class="px-3 py-2 font-mono text-sm text-fg break-all">{{ col.csv_column }}</td>
                <td class="px-3 py-2">
                  <span v-if="col.suggested_field" class="font-mono text-sm text-fg">
                    {{ col.suggested_field }}
                  </span>
                  <Badge v-else tone="muted">{{ t('ai.csvMapping.unmapped') }}</Badge>
                </td>
                <td class="px-3 py-2">
                  <Badge :tone="confidenceTone(col.confidence)">
                    {{ Math.round(col.confidence * 100) }}%
                  </Badge>
                </td>
                <td class="px-3 py-2 text-sm text-fg-muted">{{ col.notes }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p
          v-if="result.missing_required_fields.length"
          class="text-xs text-warning p-3 rounded-md bg-warning/10 border border-warning/20"
        >
          <Sparkles class="w-3 h-3 inline-block mr-1" aria-hidden="true" />
          {{
            t('ai.csvMapping.missingFields', {
              fields: result.missing_required_fields.join(', '),
            })
          }}
        </p>

        <!-- Data-quality observations: deterministic checks + LLM hints -->
        <div v-if="result.data_quality.length" class="border-t border-border pt-3 space-y-2">
          <p class="nf-label">
            {{ t('ai.csvMapping.dataQualityTitle') }}
          </p>
          <ul class="space-y-2">
            <li
              v-for="(issue, idx) in result.data_quality"
              :key="idx"
              class="p-3 rounded-lg border border-border bg-surface flex items-start gap-2.5"
            >
              <AlertTriangle
                class="w-4 h-4 mt-0.5 flex-shrink-0"
                :class="
                  issue.severity === 'critical'
                    ? 'text-danger'
                    : issue.severity === 'warning'
                      ? 'text-warning'
                      : 'text-primary-500'
                "
                aria-hidden="true"
              />
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 flex-wrap">
                  <Badge :tone="severityTone(issue.severity)">{{ issue.severity }}</Badge>
                  <span v-if="issue.column" class="font-mono text-sm text-fg">
                    {{ issue.column }}
                  </span>
                  <span class="text-base font-medium text-fg">{{ issue.issue }}</span>
                  <span class="text-2xs text-fg-subtle uppercase tracking-wider">
                    {{ issue.source }}
                  </span>
                </div>
                <p class="text-sm text-fg-muted mt-1">{{ issue.details }}</p>
                <p
                  v-if="issue.sample_values.length"
                  class="text-2xs text-fg-subtle mt-1 font-mono truncate"
                >
                  {{ t('ai.csvMapping.dataQualitySample') }}:
                  {{ issue.sample_values.join(' · ') }}
                </p>
              </div>
            </li>
          </ul>
        </div>

        <!-- Apply: send the mapping back to ImportView; it will be passed
             as `column_map` on the next CSV upload (server rewrites the
             header row in-flight). -->
        <div class="flex justify-end pt-2">
          <Button variant="primary" @click="applyMapping">
            <Wand2 class="w-4 h-4" aria-hidden="true" />
            {{ t('ai.csvMapping.applyButton') }}
          </Button>
        </div>
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

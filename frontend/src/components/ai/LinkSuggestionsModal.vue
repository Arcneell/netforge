<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Sparkles, X as XIcon } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { aiApi, type LinkSuggestion, type ScanReport } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

/**
 * Lists AI-suggested links and lets the admin accept / reject each one.
 * Labels (port / switch) are denormalised server-side — no client-side
 * lookup needed.
 */
const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'accepted'): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError, success: toastSuccess } = useToast()

const loading = ref(true)
const scanning = ref(false)
const suggestions = ref<LinkSuggestion[]>([])
const lastReport = ref<ScanReport | null>(null)
const acceptingId = ref<number | null>(null)
const rejectingId = ref<number | null>(null)

async function refreshList() {
  loading.value = true
  try {
    suggestions.value = await aiApi.listSuggestions()
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

async function runScan() {
  scanning.value = true
  try {
    const report = await aiApi.scanLinks()
    lastReport.value = report
    toastSuccess(
      t('ai.scanDoneToast', {
        persisted: report.persisted_count,
        raw: report.raw_count,
      }),
    )
    await refreshList()
  } catch (err) {
    toastError(describe(err))
  } finally {
    scanning.value = false
  }
}

async function accept(id: number) {
  acceptingId.value = id
  try {
    await aiApi.acceptSuggestion(id)
    toastSuccess(t('ai.acceptedToast'))
    suggestions.value = suggestions.value.filter((s) => s.id !== id)
    emit('accepted')
  } catch (err) {
    toastError(describe(err))
  } finally {
    acceptingId.value = null
  }
}

async function reject(id: number) {
  rejectingId.value = id
  try {
    await aiApi.rejectSuggestion(id)
    suggestions.value = suggestions.value.filter((s) => s.id !== id)
  } catch (err) {
    toastError(describe(err))
  } finally {
    rejectingId.value = null
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      lastReport.value = null
      refreshList()
    }
  },
)

function endpointLabel(
  switchName: string | null,
  portLabel: string | null,
  fallbackPortId: number,
): string {
  if (!switchName && !portLabel) return `port #${fallbackPortId}`
  const sw = switchName ?? '?'
  const port = portLabel ?? `port #${fallbackPortId}`
  return `${sw} · ${port}`
}

function confidenceTone(c: number): 'success' | 'primary' | 'warning' {
  if (c >= 0.8) return 'success'
  if (c >= 0.5) return 'primary'
  return 'warning'
}

function confidenceWidth(c: number): string {
  return `${Math.round(Math.max(0, Math.min(1, c)) * 100)}%`
}

const hasSuggestions = computed(() => suggestions.value.length > 0)
</script>

<template>
  <Modal :open="open" :title="t('ai.suggestLinks.title')" size="xl" @close="emit('close')">
    <div class="space-y-4">
      <!-- Action strip — explains what the scan does + triggers it -->
      <div class="flex items-start gap-3 p-4 rounded-lg bg-primary-50 dark:bg-primary-400/10">
        <span
          class="inline-flex items-center justify-center w-9 h-9 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 text-white flex-shrink-0"
        >
          <Sparkles class="w-4 h-4" aria-hidden="true" />
        </span>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-semibold text-fg">{{ t('ai.suggestLinks.heading') }}</p>
          <p class="text-xs text-fg-muted mt-1 leading-relaxed">
            {{ t('ai.suggestLinks.description') }}
          </p>
          <p v-if="lastReport" class="text-[11px] text-fg-muted mt-2 tabular-nums">
            {{
              t('ai.suggestLinks.lastRun', {
                persisted: lastReport.persisted_count,
                raw: lastReport.raw_count,
                latency: lastReport.latency_ms,
              })
            }}
          </p>
        </div>
        <Button variant="primary" shape="pill" :loading="scanning" @click="runScan">
          <Sparkles class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.suggestLinks.scan') }}
        </Button>
      </div>

      <!-- Suggestion list -->
      <div v-if="loading" class="space-y-2">
        <div v-for="i in 3" :key="i" class="nf-card p-4 space-y-2">
          <Skeleton width="60%" height="1rem" />
          <Skeleton width="40%" height="0.75rem" />
          <Skeleton width="80%" height="0.75rem" />
        </div>
      </div>
      <EmptyState
        v-else-if="!hasSuggestions"
        :icon="Sparkles"
        :title="t('ai.suggestLinks.emptyTitle')"
        :description="t('ai.suggestLinks.emptyDescription')"
        size="sm"
      />
      <ul v-else class="space-y-2.5 max-h-[28rem] overflow-y-auto pr-1 -mr-1">
        <li v-for="s in suggestions" :key="s.id" class="nf-card p-4 flex flex-col gap-3">
          <div class="flex items-start justify-between gap-3 flex-wrap">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 flex-wrap text-sm">
                <span class="font-mono text-fg">
                  {{ endpointLabel(s.switch_a_name, s.port_a_label, s.port_a_id) }}
                </span>
                <span class="text-fg-muted">↔</span>
                <span class="font-mono text-fg">
                  {{ endpointLabel(s.switch_b_name, s.port_b_label, s.port_b_id) }}
                </span>
                <Badge :tone="confidenceTone(s.confidence)" class="ml-1">
                  {{ Math.round(s.confidence * 100) }}%
                </Badge>
                <Badge tone="muted" monospace>{{ s.link_type }}</Badge>
              </div>
              <p v-if="s.reasoning" class="text-xs text-fg-muted mt-1.5 leading-relaxed">
                {{ s.reasoning }}
              </p>
              <!-- Visual confidence bar — same hue as the badge -->
              <div class="mt-2 h-1 bg-muted rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all"
                  :class="{
                    'bg-success': s.confidence >= 0.8,
                    'bg-primary-500': s.confidence >= 0.5 && s.confidence < 0.8,
                    'bg-warning': s.confidence < 0.5,
                  }"
                  :style="{ width: confidenceWidth(s.confidence) }"
                />
              </div>
            </div>
            <div class="flex items-center gap-2 flex-shrink-0">
              <Button
                variant="ghost"
                size="sm"
                :loading="rejectingId === s.id"
                :disabled="acceptingId !== null"
                @click="reject(s.id)"
              >
                <XIcon class="w-4 h-4" aria-hidden="true" />
                {{ t('ai.suggestLinks.reject') }}
              </Button>
              <Button
                variant="primary"
                size="sm"
                shape="pill"
                :loading="acceptingId === s.id"
                :disabled="rejectingId !== null"
                @click="accept(s.id)"
              >
                <Check class="w-4 h-4" aria-hidden="true" />
                {{ t('ai.suggestLinks.accept') }}
              </Button>
            </div>
          </div>
        </li>
      </ul>
    </div>
  </Modal>
</template>

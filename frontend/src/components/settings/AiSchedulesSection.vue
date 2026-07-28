<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CalendarClock, Webhook, Save } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import Select from '@/components/ui/Select.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import {
  aiApi,
  type AISchedule,
  type AIScheduleKind,
  type AIScheduleUpsert,
  type InsightSeverity,
} from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError, success: toastSuccess } = useToast()

// Two kinds today. `suggest_links` is exposed but the webhook is currently
// silent for it (the server-side scheduler runs it but doesn't notify); we
// still surface the row so the operator can opt into the periodic scan.
const KINDS: AIScheduleKind[] = ['advisor', 'suggest_links']
const INTERVAL_OPTIONS = [15, 30, 60, 360, 1440, 10080] as const
const SEVERITIES: InsightSeverity[] = ['info', 'warning', 'critical']

interface Form extends AIScheduleUpsert {
  saving: boolean
}

const forms = ref<Record<AIScheduleKind, Form>>({
  advisor: {
    enabled: false,
    interval_minutes: 1440,
    webhook_url: null,
    webhook_severity_threshold: 'warning',
    saving: false,
  },
  suggest_links: {
    enabled: false,
    interval_minutes: 1440,
    webhook_url: null,
    webhook_severity_threshold: 'warning',
    saving: false,
  },
})
const lastRunAt = ref<Record<AIScheduleKind, string | null>>({
  advisor: null,
  suggest_links: null,
})
const loading = ref(true)

function applyFromServer(s: AISchedule) {
  forms.value[s.kind] = {
    enabled: s.enabled,
    interval_minutes: s.interval_minutes,
    webhook_url: s.webhook_url,
    webhook_severity_threshold: s.webhook_severity_threshold,
    saving: false,
  }
  lastRunAt.value[s.kind] = s.last_run_at
}

async function load() {
  loading.value = true
  try {
    const rows = await aiApi.listSchedules()
    for (const s of rows) {
      if (s.kind === 'advisor' || s.kind === 'suggest_links') {
        applyFromServer(s)
      }
    }
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

async function save(kind: AIScheduleKind) {
  const f = forms.value[kind]
  f.saving = true
  try {
    const updated = await aiApi.upsertSchedule(kind, {
      enabled: f.enabled,
      interval_minutes: f.interval_minutes,
      webhook_url: (f.webhook_url || '').trim() || null,
      webhook_severity_threshold: f.webhook_severity_threshold,
    })
    applyFromServer(updated)
    toastSuccess(t('ai.schedules.savedToast'))
  } catch (err) {
    toastError(describe(err))
  } finally {
    f.saving = false
  }
}

onMounted(load)

function intervalLabel(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) {
    return t('ai.schedules.intervalDays', { n: minutes / 1440 })
  }
  if (minutes >= 60 && minutes % 60 === 0) {
    return t('ai.schedules.intervalHours', { n: minutes / 60 })
  }
  return t('ai.schedules.intervalMinutes', { n: minutes })
}

// The three pickers feed the shared <Select>. Computed so every label
// re-derives when the operator switches the UI locale.
const enabledOptions = computed<{ value: boolean; label: string }[]>(() => [
  { value: true, label: t('common.yes') },
  { value: false, label: t('common.no') },
])

// `value: m as number` widens the `as const` literal back to `number` so it
// matches `interval_minutes` on the form.
const intervalOptions = computed<{ value: number; label: string }[]>(() =>
  INTERVAL_OPTIONS.map((m) => ({ value: m as number, label: intervalLabel(m) })),
)

const severityOptions = computed<{ value: InsightSeverity; label: string }[]>(() =>
  SEVERITIES.map((s) => ({ value: s, label: t(`ai.advisor.severity.${s}`) })),
)

const kindLabel: Record<AIScheduleKind, string> = {
  advisor: 'ai.schedules.kinds.advisor',
  suggest_links: 'ai.schedules.kinds.suggestLinks',
}

const lastRunDisplay = computed(() => (kind: AIScheduleKind): string => {
  const iso = lastRunAt.value[kind]
  if (!iso) return t('ai.schedules.neverRun')
  const ts = new Date(iso)
  return t('ai.schedules.lastRunAt', { at: ts.toLocaleString() })
})
</script>

<template>
  <section class="nf-card p-5 sm:p-6">
    <header class="flex items-start gap-3 mb-5">
      <span
        class="inline-flex items-center justify-center w-9 h-9 rounded-md bg-primary-600 text-white flex-shrink-0 shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.18)]"
      >
        <CalendarClock class="w-4 h-4" aria-hidden="true" />
      </span>
      <div class="min-w-0 flex-1">
        <h3 class="nf-section-title">{{ t('ai.schedules.title') }}</h3>
        <p class="text-sm text-fg-muted mt-1 max-w-2xl">
          {{ t('ai.schedules.description') }}
        </p>
      </div>
    </header>

    <div v-if="loading" class="space-y-4" aria-busy="true">
      <div v-for="i in 2" :key="i" class="rounded-lg border border-border p-4 space-y-3">
        <Skeleton width="30%" height="1rem" />
        <Skeleton width="100%" height="2.25rem" />
      </div>
    </div>

    <div v-else class="space-y-4">
      <article v-for="kind in KINDS" :key="kind" class="rounded-lg border border-border p-4">
        <div class="flex items-center justify-between gap-3 flex-wrap mb-3">
          <div class="inline-flex items-center gap-2 min-w-0">
            <h4 class="text-base font-semibold text-fg">{{ t(kindLabel[kind]) }}</h4>
            <Badge :tone="forms[kind].enabled ? 'success' : 'neutral'">
              {{ forms[kind].enabled ? t('ai.settings.enabled') : t('ai.settings.disabled') }}
            </Badge>
          </div>
          <p class="text-xs text-fg-subtle tabular-nums">{{ lastRunDisplay(kind) }}</p>
        </div>

        <!-- Cadence: when and how often the scan runs. -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="nf-label block mb-1.5">{{ t('ai.schedules.fieldEnabled') }}</span>
            <Select v-model="forms[kind].enabled" :options="enabledOptions" />
          </label>
          <label class="block">
            <span class="nf-label block mb-1.5">{{ t('ai.schedules.fieldInterval') }}</span>
            <Select v-model="forms[kind].interval_minutes" :options="intervalOptions" />
          </label>
        </div>

        <!-- Turning a scan off is a quiet change with loud consequences —
             name them where the switch is, not in a toast afterwards. -->
        <p v-if="!forms[kind].enabled" class="text-sm text-fg-muted mt-2.5">
          {{ t('ai.schedules.disabledHint') }}
        </p>

        <!-- Notification: only the advisor pushes findings out today. -->
        <div
          v-if="kind === 'advisor'"
          class="mt-4 pt-4 border-t border-border grid grid-cols-1 sm:grid-cols-2 gap-3"
        >
          <label class="block sm:col-span-2">
            <span class="nf-label mb-1.5 flex items-center gap-1.5">
              <Webhook class="w-3 h-3" aria-hidden="true" />
              {{ t('ai.schedules.fieldWebhook') }}
            </span>
            <input
              v-model="forms[kind].webhook_url"
              type="url"
              placeholder="https://hooks.slack.com/services/…"
              class="nf-input nf-input-control font-mono text-sm"
            />
            <span class="block text-xs text-fg-muted mt-1.5">
              {{ t('ai.schedules.webhookHint') }} {{ t('ai.schedules.webhookTargetHint') }}
            </span>
          </label>
          <label class="block">
            <span class="nf-label block mb-1.5">{{ t('ai.schedules.fieldThreshold') }}</span>
            <Select v-model="forms[kind].webhook_severity_threshold" :options="severityOptions" />
          </label>
        </div>

        <div class="flex justify-end pt-4">
          <Button variant="primary" size="sm" :loading="forms[kind].saving" @click="save(kind)">
            <Save class="w-4 h-4" aria-hidden="true" />
            {{ t('common.save') }}
          </Button>
        </div>
      </article>
    </div>
  </section>
</template>

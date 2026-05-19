<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CalendarClock, Webhook, Save } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
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
    <div class="flex items-start gap-3 mb-4">
      <span
        class="inline-flex items-center justify-center w-9 h-9 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 text-white flex-shrink-0"
      >
        <CalendarClock class="w-4 h-4" aria-hidden="true" />
      </span>
      <div class="min-w-0 flex-1">
        <h3 class="text-base font-semibold tracking-tight">{{ t('ai.schedules.title') }}</h3>
        <p class="text-xs text-fg-muted mt-1 max-w-xl leading-relaxed">
          {{ t('ai.schedules.description') }}
        </p>
      </div>
    </div>

    <div v-if="loading" class="text-sm text-fg-muted">{{ t('common.loading') }}</div>

    <div v-else class="space-y-5">
      <fieldset
        v-for="kind in KINDS"
        :key="kind"
        class="border border-border/70 dark:border-border/40 rounded-lg p-4 space-y-3"
      >
        <legend class="px-2 -mt-7 bg-surface inline-flex items-center gap-2">
          <span class="text-sm font-semibold">{{ t(kindLabel[kind]) }}</span>
          <Badge :tone="forms[kind].enabled ? 'success' : 'muted'">
            {{ forms[kind].enabled ? t('ai.settings.enabled') : t('ai.settings.disabled') }}
          </Badge>
        </legend>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <label class="text-sm">
            <span
              class="block text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1"
            >
              {{ t('ai.schedules.fieldEnabled') }}
            </span>
            <select
              v-model="forms[kind].enabled"
              class="w-full h-9 px-2 rounded border border-border bg-surface"
            >
              <option :value="true">{{ t('common.yes') }}</option>
              <option :value="false">{{ t('common.no') }}</option>
            </select>
          </label>
          <label class="text-sm">
            <span
              class="block text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1"
            >
              {{ t('ai.schedules.fieldInterval') }}
            </span>
            <select
              v-model.number="forms[kind].interval_minutes"
              class="w-full h-9 px-2 rounded border border-border bg-surface"
            >
              <option v-for="m in INTERVAL_OPTIONS" :key="m" :value="m">
                {{ intervalLabel(m) }}
              </option>
            </select>
          </label>
          <label v-if="kind === 'advisor'" class="text-sm">
            <span
              class="block text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1"
            >
              {{ t('ai.schedules.fieldThreshold') }}
            </span>
            <select
              v-model="forms[kind].webhook_severity_threshold"
              class="w-full h-9 px-2 rounded border border-border bg-surface"
            >
              <option v-for="s in SEVERITIES" :key="s" :value="s">
                {{ t(`ai.advisor.severity.${s}`) }}
              </option>
            </select>
          </label>
        </div>

        <label v-if="kind === 'advisor'" class="text-sm block">
          <span
            class="block text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1 flex items-center gap-1"
          >
            <Webhook class="w-3 h-3" aria-hidden="true" />
            {{ t('ai.schedules.fieldWebhook') }}
          </span>
          <input
            v-model="forms[kind].webhook_url"
            type="url"
            placeholder="https://hooks.slack.com/services/…"
            class="w-full h-9 px-2 rounded border border-border bg-surface font-mono text-xs"
          />
          <span class="block text-[11px] text-fg-muted mt-1">
            {{ t('ai.schedules.webhookHint') }}
          </span>
        </label>

        <div class="flex items-center justify-between gap-3 flex-wrap pt-1">
          <p class="text-[11px] text-fg-muted tabular-nums">
            {{ lastRunDisplay(kind) }}
          </p>
          <Button
            variant="primary"
            size="sm"
            shape="pill"
            :loading="forms[kind].saving"
            @click="save(kind)"
          >
            <Save class="w-4 h-4" aria-hidden="true" />
            {{ t('common.save') }}
          </Button>
        </div>
      </fieldset>
    </div>
  </section>
</template>

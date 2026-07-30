<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, CheckCircle2, XCircle, Zap } from '@lucide/vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import AiSchedulesSection from '@/components/settings/AiSchedulesSection.vue'
import AiUsageSection from '@/components/settings/AiUsageSection.vue'
import { aiApi, type AIStatus, type AITestResult } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError } = useToast()

const status = ref<AIStatus | null>(null)
const loading = ref(true)
const testing = ref(false)
const lastTest = ref<AITestResult | null>(null)

async function loadStatus() {
  loading.value = true
  try {
    status.value = await aiApi.status()
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

async function runTest() {
  testing.value = true
  lastTest.value = null
  try {
    lastTest.value = await aiApi.test()
  } catch (err) {
    toastError(describe(err))
  } finally {
    testing.value = false
  }
}

onMounted(loadStatus)

const providerLabel = computed(() => {
  if (!status.value) return ''
  const map: Record<string, string> = {
    anthropic: 'Anthropic Claude',
    openai: 'OpenAI',
    gemini: 'Google Gemini',
  }
  return map[status.value.provider] ?? status.value.provider
})

const isDisabled = computed(() => !loading.value && status.value?.enabled === false)
</script>

<template>
  <section class="space-y-5">
    <!-- Same anatomy as every other settings section: what it is, what it
         controls, and its current state. -->
    <div class="nf-toolbar items-start justify-between mb-0">
      <div class="min-w-0">
        <h2 class="nf-section-title">{{ t('ai.settings.title') }}</h2>
        <p class="text-sm text-fg-muted mt-1 max-w-2xl inline-flex items-start gap-1.5">
          <span>{{ t('ai.settings.description') }}</span>
          <HelpTooltip :text="t('ai.settings.help.section')" placement="bottom" />
        </p>
      </div>
      <Badge :tone="status?.enabled ? 'success' : 'neutral'" size="md">
        {{ status?.enabled ? t('ai.settings.enabled') : t('ai.settings.disabled') }}
      </Badge>
    </div>

    <div class="nf-card p-5 sm:p-6">
      <!-- What is configured right now. Read-only: the provider is an env
           decision, and the block at the bottom says how to change it. -->
      <dl class="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div>
          <dt class="nf-label">{{ t('ai.settings.provider') }}</dt>
          <dd class="text-base font-medium text-fg mt-1.5">
            <Skeleton v-if="loading" width="8rem" height="1rem" />
            <span v-else>{{ providerLabel || '—' }}</span>
          </dd>
        </div>
        <div>
          <dt class="nf-label">{{ t('ai.settings.model') }}</dt>
          <dd class="text-base font-mono text-fg mt-1.5">
            <Skeleton v-if="loading" width="12rem" height="1rem" />
            <span v-else>{{ status?.model || '—' }}</span>
          </dd>
        </div>
      </dl>

      <!-- AI off is not an error, but it silently removes features from the
           whole app — say what it costs and where the switch lives. -->
      <p
        v-if="isDisabled"
        class="mt-5 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/[0.06] px-3 py-2.5 text-sm text-fg"
      >
        <AlertTriangle class="w-4 h-4 text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
        <span>{{ t('ai.settings.envHint') }}</span>
      </p>

      <!-- Connection test -->
      <div class="mt-5 pt-5 border-t border-border">
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <div class="min-w-0">
            <p class="text-base font-medium text-fg inline-flex items-center gap-1.5">
              <span>{{ t('ai.settings.testTitle') }}</span>
              <HelpTooltip :text="t('ai.settings.help.test')" />
            </p>
            <p class="text-sm text-fg-muted mt-1 max-w-2xl">
              {{ t('ai.settings.testDescription') }}
            </p>
          </div>
          <Button
            variant="secondary"
            :loading="testing"
            :disabled="!status?.enabled"
            @click="runTest"
          >
            <Zap class="w-4 h-4" aria-hidden="true" />
            {{ t('ai.settings.runTest') }}
          </Button>
        </div>

        <div
          v-if="lastTest"
          class="mt-4 p-3 rounded-md flex items-start gap-3"
          :class="
            lastTest.ok
              ? 'bg-success/5 border border-success/25'
              : 'bg-danger/5 border border-danger/25'
          "
          role="status"
        >
          <CheckCircle2
            v-if="lastTest.ok"
            class="w-5 h-5 text-success flex-shrink-0 mt-0.5"
            aria-hidden="true"
          />
          <XCircle v-else class="w-5 h-5 text-danger flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="text-base font-medium" :class="lastTest.ok ? 'text-success' : 'text-danger'">
              {{ lastTest.ok ? t('ai.settings.testOk') : t('ai.settings.testKo') }}
              <span class="font-normal text-fg-muted ml-2 tabular-nums">
                · {{ lastTest.latency_ms }} ms
              </span>
            </p>
            <p v-if="lastTest.error" class="text-xs text-fg-muted mt-1 font-mono break-words">
              {{ lastTest.error }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Usage dashboard — historical view of AI calls + estimated cost -->
    <AiUsageSection />

    <!-- Scheduled runs — periodic advisor / suggest-links + webhook notification.
         Hidden when the scheduler is disabled at the env level. -->
    <AiSchedulesSection v-if="status?.scheduler_enabled !== false" />

    <!-- How-to-change note -->
    <div class="nf-card p-5 sm:p-6">
      <h3 class="nf-section-title">{{ t('ai.settings.howToChange') }}</h3>
      <p class="text-sm text-fg-muted mt-1 max-w-2xl leading-relaxed">
        {{ t('ai.settings.envHint') }}
      </p>
      <ul
        class="mt-3 rounded-md border border-border bg-muted/40 px-3 py-2.5 space-y-1 font-mono text-xs text-fg-muted"
      >
        <li>AI_ENABLED=true</li>
        <li>AI_PROVIDER=anthropic | openai | gemini</li>
        <li>AI_MODEL=&lt;optional override&gt;</li>
        <li>AI_ANTHROPIC_API_KEY=…</li>
        <li>AI_OPENAI_API_KEY=…</li>
        <li>AI_GEMINI_API_KEY=…</li>
      </ul>
    </div>
  </section>
</template>

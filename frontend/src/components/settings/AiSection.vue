<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircle2, Sparkles, XCircle, Zap } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
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
</script>

<template>
  <section class="space-y-4">
    <!-- Hero card explaining what's configured + how to change it -->
    <div class="nf-card p-5 sm:p-6">
      <div class="flex items-start gap-4">
        <span
          class="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 text-white flex-shrink-0"
        >
          <Sparkles class="w-5 h-5" aria-hidden="true" />
        </span>
        <div class="flex-1 min-w-0">
          <h2 class="text-lg font-semibold tracking-tight">{{ t('ai.settings.title') }}</h2>
          <p class="text-sm text-fg-muted mt-1 max-w-2xl leading-relaxed">
            {{ t('ai.settings.description') }}
          </p>
        </div>
        <Badge :tone="status?.enabled ? 'success' : 'muted'" class="flex-shrink-0">
          {{ status?.enabled ? t('ai.settings.enabled') : t('ai.settings.disabled') }}
        </Badge>
      </div>

      <!-- Provider summary grid -->
      <dl
        class="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6 pt-5 border-t border-border/70 dark:border-border/40"
      >
        <div>
          <dt class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
            {{ t('ai.settings.provider') }}
          </dt>
          <dd class="text-sm font-medium text-fg mt-1">
            <span v-if="loading" class="text-fg-muted">—</span>
            <span v-else>{{ providerLabel || '—' }}</span>
          </dd>
        </div>
        <div>
          <dt class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
            {{ t('ai.settings.model') }}
          </dt>
          <dd class="text-sm font-mono text-fg mt-1">
            <span v-if="loading" class="text-fg-muted">—</span>
            <span v-else>{{ status?.model || '—' }}</span>
          </dd>
        </div>
      </dl>

      <!-- Connection test -->
      <div class="mt-6 pt-5 border-t border-border/70 dark:border-border/40">
        <div class="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <p class="text-sm font-semibold">{{ t('ai.settings.testTitle') }}</p>
            <p class="text-xs text-fg-muted mt-1">{{ t('ai.settings.testDescription') }}</p>
          </div>
          <Button
            variant="primary"
            shape="pill"
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
          class="mt-4 p-3 rounded-lg flex items-start gap-3"
          :class="
            lastTest.ok
              ? 'bg-success/5 border border-success/20'
              : 'bg-danger/5 border border-danger/20'
          "
        >
          <CheckCircle2
            v-if="lastTest.ok"
            class="w-5 h-5 text-success flex-shrink-0 mt-0.5"
            aria-hidden="true"
          />
          <XCircle v-else class="w-5 h-5 text-danger flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium" :class="lastTest.ok ? 'text-success' : 'text-danger'">
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

    <!-- How-to-change note -->
    <div class="nf-card p-5 text-sm text-fg-muted leading-relaxed">
      <p class="font-medium text-fg mb-2">{{ t('ai.settings.howToChange') }}</p>
      <p>{{ t('ai.settings.envHint') }}</p>
      <ul class="mt-3 space-y-1 font-mono text-xs">
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

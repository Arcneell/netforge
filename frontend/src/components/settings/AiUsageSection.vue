<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Activity, Coins, Gauge, TrendingUp } from 'lucide-vue-next'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import { aiApi, type UsageReport, type UsageBucket } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const { t, locale } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError } = useToast()

const days = ref<7 | 30 | 90>(30)
const report = ref<UsageReport | null>(null)
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    report.value = await aiApi.usage(days.value)
  } catch (err) {
    toastError(describe(err))
    report.value = null
  } finally {
    loading.value = false
  }
}

watch(days, load)
onMounted(load)

const totalsEmpty = computed(() => (report.value?.total.calls ?? 0) === 0)

/** Format a USD amount with locale-aware grouping. Below $0.01 we keep 4
 *  decimals so a "$0.0003" call doesn't display as "$0.00". */
function formatUsd(amount: number): string {
  const fmt = new Intl.NumberFormat(locale.value === 'fr' ? 'fr-FR' : 'en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: amount < 0.01 ? 4 : 2,
  })
  return fmt.format(amount)
}

function formatNumber(n: number): string {
  return new Intl.NumberFormat(locale.value === 'fr' ? 'fr-FR' : 'en-US').format(n)
}

/** Day sparkline — a minimal inline SVG so we don't pull a chart library for
 *  one dashboard. Returns an SVG path "M x y L x y …" plus the y-axis range
 *  used to align the line in its viewbox. */
const sparkline = computed(() => {
  const bucks = report.value?.by_day ?? []
  if (bucks.length < 2) return null
  const values = bucks.map((b) => b.totals.calls)
  const max = Math.max(...values, 1)
  const min = 0
  const width = 240
  const height = 48
  const xStep = width / (bucks.length - 1)
  const points = bucks
    .map((b, i) => {
      const x = i * xStep
      const range = max - min || 1
      const y = height - ((b.totals.calls - min) / range) * height
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
  return { d: points, width, height, max, min }
})

const kindLabel: Record<string, string> = {
  suggest_links: 'ai.usage.kinds.suggestLinks',
  advisor: 'ai.usage.kinds.advisor',
  nl_query: 'ai.usage.kinds.nlQuery',
}

function bucketLabel(b: UsageBucket, dimension: 'kind' | 'provider'): string {
  if (dimension === 'kind') {
    return t(kindLabel[b.key] ?? b.key)
  }
  return b.key
}
</script>

<template>
  <section class="nf-card p-5 sm:p-6">
    <div class="flex items-start justify-between gap-3 flex-wrap mb-4">
      <div class="min-w-0">
        <h3 class="text-base font-semibold tracking-tight">{{ t('ai.usage.title') }}</h3>
        <p class="text-xs text-fg-muted mt-1 max-w-xl leading-relaxed">
          {{ t('ai.usage.description') }}
        </p>
      </div>
      <div
        class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface text-xs"
        role="group"
        :aria-label="t('ai.usage.windowLabel')"
      >
        <button
          v-for="opt in [7, 30, 90] as const"
          :key="opt"
          type="button"
          :aria-pressed="days === opt"
          class="px-2.5 h-7 rounded font-medium transition tabular-nums"
          :class="
            days === opt
              ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
              : 'text-fg-muted hover:bg-surface-hover hover:text-fg'
          "
          @click="days = opt"
        >
          {{ t('ai.usage.daysOption', { n: opt }) }}
        </button>
      </div>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="grid grid-cols-2 sm:grid-cols-4 gap-3" aria-busy="true">
      <div v-for="i in 4" :key="i" class="space-y-2">
        <Skeleton width="60%" height="0.75rem" />
        <Skeleton width="80%" height="1.5rem" />
      </div>
    </div>

    <!-- Empty -->
    <EmptyState
      v-else-if="totalsEmpty"
      :icon="TrendingUp"
      :title="t('ai.usage.emptyTitle')"
      :description="t('ai.usage.emptyDescription')"
      size="sm"
    />

    <!-- Stats -->
    <template v-else-if="report">
      <dl class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <dt
            class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold flex items-center gap-1"
          >
            <Activity class="w-3 h-3" aria-hidden="true" />
            {{ t('ai.usage.calls') }}
          </dt>
          <dd class="text-2xl font-semibold tabular-nums mt-1">
            {{ formatNumber(report.total.calls) }}
          </dd>
          <p class="text-[11px] text-fg-muted tabular-nums mt-0.5">
            {{
              t('ai.usage.successFailure', {
                ok: report.total.success,
                ko: report.total.failure,
              })
            }}
          </p>
        </div>
        <div>
          <dt
            class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold flex items-center gap-1"
          >
            <Coins class="w-3 h-3" aria-hidden="true" />
            {{ t('ai.usage.cost') }}
          </dt>
          <dd class="text-2xl font-semibold tabular-nums mt-1">
            {{ formatUsd(report.total.cost_usd) }}
          </dd>
          <p class="text-[11px] text-fg-muted mt-0.5">{{ t('ai.usage.costHint') }}</p>
        </div>
        <div>
          <dt class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
            {{ t('ai.usage.tokens') }}
          </dt>
          <dd class="text-2xl font-semibold tabular-nums mt-1">
            {{ formatNumber(report.total.prompt_tokens + report.total.completion_tokens) }}
          </dd>
          <p class="text-[11px] text-fg-muted tabular-nums mt-0.5">
            {{ formatNumber(report.total.prompt_tokens) }} in ·
            {{ formatNumber(report.total.completion_tokens) }} out
          </p>
        </div>
        <div>
          <dt
            class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold flex items-center gap-1"
          >
            <Gauge class="w-3 h-3" aria-hidden="true" />
            {{ t('ai.usage.latency') }}
          </dt>
          <dd class="text-2xl font-semibold tabular-nums mt-1">
            {{ formatNumber(report.total.avg_latency_ms) }}<span class="text-sm">ms</span>
          </dd>
          <p class="text-[11px] text-fg-muted mt-0.5">{{ t('ai.usage.latencyHint') }}</p>
        </div>
      </dl>

      <!-- Sparkline + per-day daily peak -->
      <div
        v-if="sparkline"
        class="mt-5 pt-5 border-t border-border/70 dark:border-border/40 flex items-center gap-4 flex-wrap"
      >
        <svg
          :viewBox="`0 0 ${sparkline.width} ${sparkline.height}`"
          :width="sparkline.width"
          :height="sparkline.height"
          class="text-primary-500"
          aria-hidden="true"
        >
          <path
            :d="sparkline.d"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <p class="text-xs text-fg-muted">
          {{ t('ai.usage.peakDay', { n: sparkline.max }) }}
        </p>
      </div>

      <!-- By kind + by provider tables -->
      <div class="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-6">
        <div v-if="report.by_kind.length">
          <h4 class="text-xs uppercase tracking-wider text-fg-muted font-semibold mb-2">
            {{ t('ai.usage.byKind') }}
          </h4>
          <ul class="space-y-1.5">
            <li
              v-for="b in report.by_kind"
              :key="b.key"
              class="flex items-center justify-between gap-3 text-sm"
            >
              <span class="font-medium">{{ bucketLabel(b, 'kind') }}</span>
              <span class="tabular-nums text-fg-muted">
                {{ formatNumber(b.totals.calls) }} ·
                <span class="text-fg">{{ formatUsd(b.totals.cost_usd) }}</span>
              </span>
            </li>
          </ul>
        </div>
        <div v-if="report.by_provider.length">
          <h4 class="text-xs uppercase tracking-wider text-fg-muted font-semibold mb-2">
            {{ t('ai.usage.byProvider') }}
          </h4>
          <ul class="space-y-1.5">
            <li
              v-for="b in report.by_provider"
              :key="b.key"
              class="flex items-center justify-between gap-3 text-sm"
            >
              <span class="font-medium">{{ bucketLabel(b, 'provider') }}</span>
              <span class="tabular-nums text-fg-muted">
                {{ formatNumber(b.totals.calls) }} ·
                <span class="text-fg">{{ formatUsd(b.totals.cost_usd) }}</span>
              </span>
            </li>
          </ul>
        </div>
      </div>

      <p class="mt-5 pt-4 border-t border-border/50 text-[11px] text-fg-muted">
        {{ t('ai.usage.disclaimer') }}
      </p>
    </template>
  </section>
</template>

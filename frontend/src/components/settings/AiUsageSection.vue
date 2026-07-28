<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Activity, AlertTriangle, Coins, Gauge, Hash, TrendingUp } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Segmented from '@/components/ui/Segmented.vue'
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
// A failed fetch used to fall through to the "no AI calls" empty state, which
// told the admin something false. Track it separately so the panel can say
// "couldn't load" and offer a retry.
const loadFailed = ref(false)

// Monotonic request token — when the admin flips 7 → 30 → 90 quickly, every
// in-flight call resolves but only the LATEST one is allowed to update
// `report.value`. Without this the slowest response wins, leaving the badge
// in disagreement with the data shown.
let requestSeq = 0

async function load() {
  loading.value = true
  const myToken = ++requestSeq
  try {
    const r = await aiApi.usage(days.value)
    if (myToken !== requestSeq) {
      // A newer call has already started — drop this stale answer on the floor.
      return
    }
    report.value = r
    loadFailed.value = false
  } catch (err) {
    if (myToken !== requestSeq) return
    toastError(describe(err))
    report.value = null
    loadFailed.value = true
  } finally {
    if (myToken === requestSeq) {
      loading.value = false
    }
  }
}

watch(days, load)
onMounted(load)

const totalsEmpty = computed(() => (report.value?.total.calls ?? 0) === 0)

const windowOptions = computed(() =>
  ([7, 30, 90] as const).map((n) => ({ value: n, label: t('ai.usage.daysOption', { n }) })),
)

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

/** Latency comes back as a float average. Sub-millisecond digits are noise
 *  from the averaging, not measurement — round rather than imply precision. */
function formatMs(n: number): string {
  return formatNumber(Math.round(n))
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
    <header class="flex items-start justify-between gap-3 flex-wrap mb-5">
      <div class="min-w-0">
        <h3 class="nf-section-title">{{ t('ai.usage.title') }}</h3>
        <p class="text-sm text-fg-muted mt-1 max-w-2xl">
          {{ t('ai.usage.description') }}
        </p>
      </div>
      <Segmented v-model="days" :options="windowOptions" :aria-label="t('ai.usage.windowLabel')" />
    </header>

    <!-- Loading skeleton -->
    <div v-if="loading" class="grid grid-cols-2 lg:grid-cols-4 gap-3" aria-busy="true">
      <div v-for="i in 4" :key="i" class="rounded-lg border border-border p-3.5 space-y-2">
        <Skeleton width="60%" height="0.75rem" />
        <Skeleton width="80%" height="1.5rem" />
      </div>
    </div>

    <!-- Fetch failed — say so, and offer the way out. -->
    <EmptyState
      v-else-if="loadFailed"
      :icon="AlertTriangle"
      :title="t('ai.usage.errorTitle')"
      :description="t('ai.usage.errorDescription')"
      size="sm"
    >
      <template #action>
        <Button variant="secondary" @click="load">{{ t('common.refresh') }}</Button>
      </template>
    </EmptyState>

    <!-- Empty -->
    <EmptyState
      v-else-if="totalsEmpty"
      :icon="TrendingUp"
      :title="t('ai.usage.emptyTitle')"
      :description="t('ai.usage.emptyDescription')"
      size="sm"
    />

    <!-- Stats. Four tiles, one shape: label, figure, unit, one line of
         qualification. Every figure carries its unit so nothing is guessed. -->
    <template v-else-if="report">
      <dl class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div class="rounded-lg border border-border p-3.5">
          <dt class="nf-label flex items-center gap-1.5">
            <Activity class="w-3 h-3" aria-hidden="true" />
            {{ t('ai.usage.calls') }}
          </dt>
          <dd class="mt-1.5 flex items-baseline gap-1.5">
            <span class="text-2xl font-semibold tabular-nums text-fg">
              {{ formatNumber(report.total.calls) }}
            </span>
            <span class="text-xs text-fg-subtle">{{ t('ai.usage.callsUnit') }}</span>
          </dd>
          <p class="text-xs text-fg-muted tabular-nums mt-1">
            {{
              t('ai.usage.successFailure', {
                ok: report.total.success,
                ko: report.total.failure,
              })
            }}
          </p>
        </div>

        <div class="rounded-lg border border-border p-3.5">
          <dt class="nf-label flex items-center gap-1.5">
            <Coins class="w-3 h-3" aria-hidden="true" />
            {{ t('ai.usage.cost') }}
          </dt>
          <dd class="mt-1.5 flex items-baseline gap-1.5">
            <span class="text-2xl font-semibold tabular-nums text-fg">
              {{ formatUsd(report.total.cost_usd) }}
            </span>
            <span class="text-xs text-fg-subtle">{{ t('ai.usage.costCurrency') }}</span>
          </dd>
          <p class="text-xs text-fg-muted mt-1">{{ t('ai.usage.costHint') }}</p>
        </div>

        <div class="rounded-lg border border-border p-3.5">
          <dt class="nf-label flex items-center gap-1.5">
            <Hash class="w-3 h-3" aria-hidden="true" />
            {{ t('ai.usage.tokens') }}
          </dt>
          <dd class="mt-1.5 flex items-baseline gap-1.5">
            <span class="text-2xl font-semibold tabular-nums text-fg">
              {{ formatNumber(report.total.prompt_tokens + report.total.completion_tokens) }}
            </span>
            <span class="text-xs text-fg-subtle">{{ t('ai.usage.tokensUnit') }}</span>
          </dd>
          <p class="text-xs text-fg-muted tabular-nums mt-1">
            {{
              t('ai.usage.tokensBreakdown', {
                in: formatNumber(report.total.prompt_tokens),
                out: formatNumber(report.total.completion_tokens),
              })
            }}
          </p>
        </div>

        <div class="rounded-lg border border-border p-3.5">
          <dt class="nf-label flex items-center gap-1.5">
            <Gauge class="w-3 h-3" aria-hidden="true" />
            {{ t('ai.usage.latency') }}
          </dt>
          <dd class="mt-1.5 flex items-baseline gap-1.5">
            <span class="text-2xl font-semibold tabular-nums text-fg">
              {{ formatMs(report.total.avg_latency_ms) }}
            </span>
            <span class="text-xs text-fg-subtle">{{ t('ai.usage.latencyUnit') }}</span>
          </dd>
          <p class="text-xs text-fg-muted mt-1">{{ t('ai.usage.latencyHint') }}</p>
        </div>
      </dl>

      <!-- Calls per day. A shape, not a chart — the peak is spelled out below
           it because a sparkline has no axis to read a value off. -->
      <div v-if="sparkline" class="mt-6 pt-5 border-t border-border">
        <p class="nf-label">{{ t('ai.usage.sparklineLabel') }}</p>
        <div class="mt-2 flex items-center gap-4 flex-wrap">
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
          <p class="text-sm text-fg-muted tabular-nums">
            {{ t('ai.usage.peakDay', { n: sparkline.max }) }}
          </p>
        </div>
      </div>

      <!-- Breakdowns. Same row shape on both sides: name left, calls and cost
           right, so the two lists can be compared without re-reading headers. -->
      <div class="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div v-if="report.by_kind.length">
          <h4 class="nf-label mb-2">{{ t('ai.usage.byKind') }}</h4>
          <ul class="rounded-lg border border-border divide-y divide-border overflow-hidden">
            <li
              v-for="b in report.by_kind"
              :key="b.key"
              class="nf-list-row justify-between !py-2.5"
            >
              <span class="text-base font-medium text-fg min-w-0 truncate">
                {{ bucketLabel(b, 'kind') }}
              </span>
              <span class="text-sm tabular-nums text-fg-muted whitespace-nowrap">
                {{ formatNumber(b.totals.calls) }} {{ t('ai.usage.callsUnit') }}
                <span class="text-fg-subtle" aria-hidden="true">·</span>
                <span class="text-fg font-medium">{{ formatUsd(b.totals.cost_usd) }}</span>
              </span>
            </li>
          </ul>
        </div>
        <div v-if="report.by_provider.length">
          <h4 class="nf-label mb-2">{{ t('ai.usage.byProvider') }}</h4>
          <ul class="rounded-lg border border-border divide-y divide-border overflow-hidden">
            <li
              v-for="b in report.by_provider"
              :key="b.key"
              class="nf-list-row justify-between !py-2.5"
            >
              <span class="text-base font-medium text-fg min-w-0 truncate">
                {{ bucketLabel(b, 'provider') }}
              </span>
              <span class="text-sm tabular-nums text-fg-muted whitespace-nowrap">
                {{ formatNumber(b.totals.calls) }} {{ t('ai.usage.callsUnit') }}
                <span class="text-fg-subtle" aria-hidden="true">·</span>
                <span class="text-fg font-medium">{{ formatUsd(b.totals.cost_usd) }}</span>
              </span>
            </li>
          </ul>
        </div>
      </div>

      <p class="mt-5 pt-4 border-t border-border text-xs text-fg-muted leading-relaxed">
        {{ t('ai.usage.disclaimer') }}
      </p>
    </template>
  </section>
</template>

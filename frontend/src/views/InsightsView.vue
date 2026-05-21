<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  AlertOctagon,
  AlertTriangle,
  Download,
  Info,
  Lightbulb,
  Network,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
  Tags,
  Router as RouterIcon,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import {
  aiApi,
  type AIStatus,
  type AdvisorReport,
  type Insight,
  type InsightCategory,
  type InsightEntityRef,
  type InsightSeverity,
  type IntegrityIssue,
} from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError, success: toastSuccess } = useToast()

const status = ref<AIStatus | null>(null)
const insights = ref<Insight[]>([])
const runId = ref<number | null>(null)
const runCreatedAt = ref<string | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const lastReport = ref<AdvisorReport | null>(null)

const tab = ref<'advisor' | 'integrity'>('advisor')
const integrityIssues = ref<IntegrityIssue[]>([])
const integrityLoading = ref(false)
const integrityLoaded = ref(false)

async function loadIntegrity() {
  integrityLoading.value = true
  try {
    const r = await aiApi.integrityChecks()
    integrityIssues.value = r.issues
    integrityLoaded.value = true
  } catch (err) {
    toastError(describe(err))
  } finally {
    integrityLoading.value = false
  }
}

/**
 * Open the rendered PDF in a new tab. The backend always sends back an
 * `attachment` Content-Disposition, so the browser will offer "save" — but
 * users routinely Cmd-Click the action and expect a preview tab.
 */
function exportPdf() {
  window.open('/api/ai/insights/export.pdf', '_blank', 'noopener')
}

function selectTab(t: 'advisor' | 'integrity') {
  tab.value = t
  // Lazy-load integrity on first visit — the deterministic check is cheap,
  // but avoids running it for users who only ever look at the LLM advisor.
  if (t === 'integrity' && !integrityLoaded.value) {
    loadIntegrity()
  }
}

async function loadAll() {
  loading.value = true
  try {
    const [st, list] = await Promise.all([aiApi.status(), aiApi.getInsights()])
    status.value = st
    insights.value = list.insights
    runId.value = list.run_id
    runCreatedAt.value = list.run_created_at
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

async function refresh() {
  refreshing.value = true
  try {
    const report = await aiApi.refreshInsights()
    lastReport.value = report
    toastSuccess(
      t('ai.advisor.refreshedToast', {
        count: report.persisted_count,
        latency: report.latency_ms,
      }),
    )
    const list = await aiApi.getInsights()
    insights.value = list.insights
    runId.value = list.run_id
    runCreatedAt.value = list.run_created_at
  } catch (err) {
    toastError(describe(err))
  } finally {
    refreshing.value = false
  }
}

/**
 * Localised "generated X ago" hint. We avoid pulling a `dayjs`/`luxon`
 * dependency just for this: the precision needed is "minutes / hours / days",
 * fluent in both UI locales via i18n plural rules.
 */
function ageLabel(iso: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 60) return t('ai.advisor.ageJustNow')
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return t('ai.advisor.ageMinutes', { n: minutes })
  const hours = Math.round(minutes / 60)
  if (hours < 48) return t('ai.advisor.ageHours', { n: hours })
  const days = Math.round(hours / 24)
  return t('ai.advisor.ageDays', { n: days })
}

const stale = computed(() => {
  if (!runCreatedAt.value) return false
  const then = new Date(runCreatedAt.value).getTime()
  if (Number.isNaN(then)) return false
  // Anything older than 7 days is flagged as worth re-running.
  return Date.now() - then > 7 * 24 * 3600 * 1000
})

onMounted(loadAll)

const grouped = computed(() => {
  const buckets: Record<InsightSeverity, Insight[]> = {
    critical: [],
    warning: [],
    info: [],
  }
  for (const i of insights.value) {
    buckets[i.severity]?.push(i)
  }
  return buckets
})

const counts = computed(() => ({
  critical: grouped.value.critical.length,
  warning: grouped.value.warning.length,
  info: grouped.value.info.length,
  total: insights.value.length,
}))

const severityIcon = {
  critical: AlertOctagon,
  warning: AlertTriangle,
  info: Info,
} as const

const severityTone: Record<InsightSeverity, 'danger' | 'warning' | 'primary'> = {
  critical: 'danger',
  warning: 'warning',
  info: 'primary',
}

const categoryLabelKey: Record<InsightCategory, string> = {
  spof: 'ai.advisor.categories.spof',
  capacity: 'ai.advisor.categories.capacity',
  security: 'ai.advisor.categories.security',
  segmentation: 'ai.advisor.categories.segmentation',
  naming: 'ai.advisor.categories.naming',
  redundancy: 'ai.advisor.categories.redundancy',
  other: 'ai.advisor.categories.other',
}

function severityLabel(s: InsightSeverity): string {
  return t(`ai.advisor.severity.${s}`)
}

const entityIcon: Record<string, typeof Server> = {
  switch: RouterIcon,
  port: RouterIcon,
  device: Server,
  vlan: Tags,
  subnet: Network,
}

function entityRoute(e: InsightEntityRef): string | null {
  switch (e.type) {
    case 'switch':
      return `/switches/${e.id}`
    case 'subnet':
      return `/subnets/${e.id}`
    case 'vlan':
      return '/vlans'
    case 'device':
      return '/devices'
    default:
      return null
  }
}

function entityLabel(e: InsightEntityRef): string {
  return e.name || `${e.type} #${e.id}`
}
</script>

<template>
  <div class="p-4 sm:p-8 max-w-7xl mx-auto">
    <PageHeader :title="t('nav.insights')" :subtitle="t('ai.advisor.subtitle')">
      <template #help>
        <HelpTooltip
          :text="tab === 'advisor' ? t('ai.advisor.help') : t('ai.integrity.help')"
          placement="bottom"
        />
      </template>
      <template #actions>
        <Button
          v-if="tab === 'advisor' && runId !== null"
          variant="ghost"
          size="sm"
          @click="exportPdf"
        >
          <Download class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.advisor.exportPdf') }}
        </Button>
        <Button
          v-if="tab === 'advisor' && status?.enabled"
          variant="primary"
          shape="pill"
          :loading="refreshing"
          @click="refresh"
        >
          <RefreshCw class="w-4 h-4" aria-hidden="true" />
          {{ runId === null ? t('ai.advisor.runFirst') : t('ai.advisor.refresh') }}
        </Button>
        <Button
          v-if="tab === 'integrity'"
          variant="ghost"
          size="sm"
          shape="pill"
          :loading="integrityLoading"
          @click="loadIntegrity"
        >
          <RefreshCw class="w-4 h-4" aria-hidden="true" />
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <!-- Tabs — switch between LLM advisor and deterministic integrity checks. -->
    <div
      class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface mb-4"
      role="tablist"
    >
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'advisor'"
        :class="[
          'px-3 h-8 rounded text-sm font-medium transition flex items-center gap-1.5',
          tab === 'advisor'
            ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
            : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
        ]"
        @click="selectTab('advisor')"
      >
        <Sparkles class="w-3.5 h-3.5" aria-hidden="true" />
        {{ t('ai.advisor.tab') }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'integrity'"
        :class="[
          'px-3 h-8 rounded text-sm font-medium transition flex items-center gap-1.5',
          tab === 'integrity'
            ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
            : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
        ]"
        @click="selectTab('integrity')"
      >
        <ShieldCheck class="w-3.5 h-3.5" aria-hidden="true" />
        {{ t('ai.integrity.tab') }}
      </button>
    </div>

    <!-- ============================== ADVISOR TAB ============================== -->
    <div v-if="tab === 'advisor'">
      <!-- Run freshness banner — surfaces the age of the latest run and nudges
         the operator to re-run when older than a week. -->
      <p
        v-if="!loading && runCreatedAt"
        class="text-xs text-fg-muted -mt-2 mb-6 flex items-center gap-2"
        :class="{ 'text-warning': stale }"
      >
        <RefreshCw class="w-3 h-3" aria-hidden="true" />
        <span>{{ t('ai.advisor.runAge', { age: ageLabel(runCreatedAt) }) }}</span>
        <span v-if="stale" class="font-medium">· {{ t('ai.advisor.staleHint') }}</span>
      </p>

      <!-- Stat strip — same iOS Today-widget feel as Dashboard -->
      <section v-if="!loading && runId !== null" class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        <div class="nf-card p-4">
          <p class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
            {{ t('ai.advisor.severity.critical') }}
          </p>
          <p class="text-3xl font-semibold tabular-nums text-danger mt-1">{{ counts.critical }}</p>
        </div>
        <div class="nf-card p-4">
          <p class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
            {{ t('ai.advisor.severity.warning') }}
          </p>
          <p class="text-3xl font-semibold tabular-nums text-warning mt-1">{{ counts.warning }}</p>
        </div>
        <div class="nf-card p-4">
          <p class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
            {{ t('ai.advisor.severity.info') }}
          </p>
          <p class="text-3xl font-semibold tabular-nums text-primary-600 mt-1">{{ counts.info }}</p>
        </div>
        <div class="nf-card p-4">
          <p class="text-[11px] uppercase tracking-wider text-fg-muted font-semibold">
            {{ t('ai.advisor.total') }}
          </p>
          <p class="text-3xl font-semibold tabular-nums text-fg mt-1">{{ counts.total }}</p>
        </div>
      </section>

      <!-- Loading -->
      <div v-if="loading" class="space-y-3" aria-busy="true">
        <div v-for="i in 3" :key="i" class="nf-card p-5 space-y-2">
          <Skeleton width="40%" height="1rem" />
          <Skeleton width="80%" height="0.75rem" />
          <Skeleton width="60%" height="0.75rem" />
        </div>
      </div>

      <!-- Empty: never run -->
      <EmptyState
        v-else-if="runId === null"
        :icon="Sparkles"
        :title="t('ai.advisor.emptyTitle')"
        :description="t('ai.advisor.emptyDescription')"
      >
        <template v-if="status?.enabled" #action>
          <Button variant="primary" shape="pill" :loading="refreshing" @click="refresh">
            <RefreshCw class="w-4 h-4" aria-hidden="true" />
            {{ t('ai.advisor.runFirst') }}
          </Button>
        </template>
      </EmptyState>

      <!-- Empty: clean infra (no insights returned) -->
      <EmptyState
        v-else-if="counts.total === 0"
        :icon="Lightbulb"
        :title="t('ai.advisor.cleanTitle')"
        :description="t('ai.advisor.cleanDescription')"
      />

      <!-- Insight list grouped by severity -->
      <template v-else>
        <section
          v-for="severity in ['critical', 'warning', 'info'] as InsightSeverity[]"
          :key="severity"
        >
          <div v-if="grouped[severity].length" class="mb-8">
            <h2 class="text-xl font-semibold tracking-tight mb-3 flex items-center gap-2">
              <component
                :is="severityIcon[severity]"
                class="w-5 h-5"
                :class="{
                  'text-danger': severity === 'critical',
                  'text-warning': severity === 'warning',
                  'text-primary-600': severity === 'info',
                }"
                aria-hidden="true"
              />
              {{ severityLabel(severity) }}
              <span class="text-sm font-normal text-fg-muted tabular-nums">
                · {{ grouped[severity].length }}
              </span>
            </h2>
            <ul class="space-y-3">
              <li v-for="ins in grouped[severity]" :key="ins.id" class="nf-card p-5">
                <div class="flex items-start justify-between gap-3 flex-wrap mb-2">
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                      <Badge :tone="severityTone[ins.severity]">
                        {{ severityLabel(ins.severity) }}
                      </Badge>
                      <Badge tone="muted">{{ t(categoryLabelKey[ins.category] ?? '') }}</Badge>
                      <Badge
                        v-if="ins.streak_count && ins.streak_count >= 2"
                        tone="danger"
                        :title="t('ai.advisor.streakTooltip', { n: ins.streak_count })"
                      >
                        {{ t('ai.advisor.recurringBadge', { n: ins.streak_count }) }}
                      </Badge>
                    </div>
                    <h3 class="text-base font-semibold tracking-tight mt-2">{{ ins.title }}</h3>
                  </div>
                </div>
                <p class="text-sm text-fg-muted leading-relaxed mt-1">{{ ins.description }}</p>
                <p
                  v-if="ins.recommendation"
                  class="text-sm text-fg mt-3 p-3 rounded-lg bg-muted/60 border-l-2 border-primary-500"
                >
                  <span class="font-medium text-primary-700 dark:text-primary-300 mr-1">
                    {{ t('ai.advisor.recommendation') }}:
                  </span>
                  {{ ins.recommendation }}
                </p>
                <div
                  v-if="ins.affected_entities && ins.affected_entities.length"
                  class="mt-3 flex flex-wrap gap-1.5"
                >
                  <RouterLink
                    v-for="(e, idx) in ins.affected_entities"
                    :key="`${e.type}-${e.id}-${idx}`"
                    v-slot="{ href, navigate }"
                    :to="entityRoute(e) ?? ''"
                    custom
                  >
                    <a
                      :href="entityRoute(e) ? href : undefined"
                      :class="[
                        'nf-pill bg-muted/70',
                        entityRoute(e)
                          ? 'hover:bg-primary-50 hover:text-primary-700 cursor-pointer'
                          : 'cursor-default text-fg-muted',
                      ]"
                      @click="entityRoute(e) ? navigate($event) : null"
                    >
                      <component
                        :is="entityIcon[e.type] ?? Server"
                        class="w-3 h-3"
                        aria-hidden="true"
                      />
                      {{ entityLabel(e) }}
                    </a>
                  </RouterLink>
                </div>
              </li>
            </ul>
          </div>
        </section>
      </template>
    </div>

    <!-- ============================ INTEGRITY TAB ============================ -->
    <div v-else-if="tab === 'integrity'">
      <p class="text-xs text-fg-muted -mt-2 mb-6 leading-relaxed">
        {{ t('ai.integrity.description') }}
      </p>

      <div v-if="integrityLoading && !integrityIssues.length" class="space-y-3" aria-busy="true">
        <div v-for="i in 3" :key="i" class="nf-card p-5 space-y-2">
          <Skeleton width="40%" height="1rem" />
          <Skeleton width="80%" height="0.75rem" />
        </div>
      </div>

      <EmptyState
        v-else-if="integrityLoaded && integrityIssues.length === 0"
        :icon="ShieldCheck"
        :title="t('ai.integrity.cleanTitle')"
        :description="t('ai.integrity.cleanDescription')"
      />

      <ul v-else-if="integrityIssues.length" class="space-y-3">
        <li v-for="(iss, idx) in integrityIssues" :key="idx" class="nf-card p-5">
          <div class="flex items-center gap-2 flex-wrap">
            <Badge :tone="severityTone[iss.severity]">{{ severityLabel(iss.severity) }}</Badge>
            <Badge tone="muted">{{ t(categoryLabelKey[iss.category] ?? '') }}</Badge>
          </div>
          <h3 class="text-base font-semibold tracking-tight mt-2">{{ iss.title }}</h3>
          <p class="text-sm text-fg-muted leading-relaxed mt-1">{{ iss.description }}</p>
          <p
            v-if="iss.recommendation"
            class="text-sm text-fg mt-3 p-3 rounded-lg bg-muted/60 border-l-2 border-primary-500"
          >
            <span class="font-medium text-primary-700 dark:text-primary-300 mr-1">
              {{ t('ai.advisor.recommendation') }}:
            </span>
            {{ iss.recommendation }}
          </p>
          <div
            v-if="iss.affected_entities && iss.affected_entities.length"
            class="mt-3 flex flex-wrap gap-1.5"
          >
            <RouterLink
              v-for="(e, eIdx) in iss.affected_entities"
              :key="`${e.type}-${e.id}-${eIdx}`"
              v-slot="{ href, navigate }"
              :to="entityRoute(e) ?? ''"
              custom
            >
              <a
                :href="entityRoute(e) ? href : undefined"
                :class="[
                  'nf-pill bg-muted/70',
                  entityRoute(e)
                    ? 'hover:bg-primary-50 hover:text-primary-700 cursor-pointer'
                    : 'cursor-default text-fg-muted',
                ]"
                @click="entityRoute(e) ? navigate($event) : null"
              >
                <component :is="entityIcon[e.type] ?? Server" class="w-3 h-3" aria-hidden="true" />
                {{ entityLabel(e) }}
              </a>
            </RouterLink>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

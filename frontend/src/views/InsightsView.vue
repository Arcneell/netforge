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
import Segmented from '@/components/ui/Segmented.vue'
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

function selectTab(next: 'advisor' | 'integrity') {
  tab.value = next
  // Lazy-load integrity on first visit — the deterministic check is cheap,
  // but avoids running it for users who only ever look at the LLM advisor.
  if (next === 'integrity' && !integrityLoaded.value) {
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

const SEVERITY_ORDER = ['critical', 'warning', 'info'] as const

/**
 * Advisor insights and integrity issues carry the same shape once you strip
 * the persistence fields, and they render identically. Normalising them into
 * one view model means a single card template instead of two that drift.
 */
interface Finding {
  key: string
  severity: InsightSeverity
  category: InsightCategory
  title: string
  description: string
  recommendation: string
  entities: InsightEntityRef[]
  streak: number
}

const findings = computed<Finding[]>(() => {
  if (tab.value === 'integrity') {
    return integrityIssues.value.map((iss, idx) => ({
      key: `integrity-${idx}`,
      severity: iss.severity,
      category: iss.category,
      title: iss.title,
      description: iss.description,
      recommendation: iss.recommendation,
      entities: iss.affected_entities ?? [],
      streak: 0,
    }))
  }
  return insights.value.map((ins) => ({
    key: `insight-${ins.id}`,
    severity: ins.severity,
    category: ins.category,
    title: ins.title,
    description: ins.description,
    recommendation: ins.recommendation,
    entities: ins.affected_entities ?? [],
    streak: ins.streak_count ?? 0,
  }))
})

const grouped = computed(() => {
  const buckets: Record<InsightSeverity, Finding[]> = { critical: [], warning: [], info: [] }
  for (const f of findings.value) buckets[f.severity]?.push(f)
  return buckets
})

/** Only the severities that actually have findings, worst first. */
const visibleGroups = computed(() =>
  SEVERITY_ORDER.filter((s) => grouped.value[s].length).map((s) => ({
    severity: s,
    items: grouped.value[s],
  })),
)

const counts = computed(() => ({
  critical: grouped.value.critical.length,
  warning: grouped.value.warning.length,
  info: grouped.value.info.length,
  total: findings.value.length,
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

/** Text colour per severity — the only colour spent on the findings list. */
const severityText: Record<InsightSeverity, string> = {
  critical: 'text-danger',
  warning: 'text-warning',
  info: 'text-primary-600 dark:text-primary-400',
}

/** Matching hairline used as the card's left rail. */
const severityRail: Record<InsightSeverity, string> = {
  critical: 'border-l-danger',
  warning: 'border-l-warning',
  info: 'border-l-primary-500',
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

const tabOptions = computed(() => [
  { value: 'advisor' as const, label: t('ai.advisor.tab'), icon: Sparkles },
  { value: 'integrity' as const, label: t('ai.integrity.tab'), icon: ShieldCheck },
])

/** The compact severity strip that replaced four full-height stat cards. */
const summary = computed(() =>
  SEVERITY_ORDER.map((s) => ({
    severity: s,
    label: severityLabel(s),
    count: counts.value[s],
  })),
)

/**
 * Shown once there is something to summarise. A row of zeroes next to the
 * "nothing found" empty state would be noise.
 */
const hasSummary = computed(() => {
  if (counts.value.total === 0) return false
  return tab.value === 'advisor' ? !loading.value && runId.value !== null : integrityLoaded.value
})

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
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
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
          :loading="integrityLoading"
          @click="loadIntegrity"
        >
          <RefreshCw class="w-4 h-4" aria-hidden="true" />
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <!-- Source switch: the LLM advisor vs. the deterministic integrity pass.
         Same control as everywhere else in the app. -->
    <div class="nf-toolbar">
      <Segmented
        :model-value="tab"
        :options="tabOptions"
        :aria-label="t('nav.insights')"
        @update:model-value="selectTab"
      />
      <p
        v-if="tab === 'advisor' && !loading && runCreatedAt"
        class="text-xs flex items-center gap-1.5"
        :class="stale ? 'text-warning' : 'text-fg-muted'"
      >
        <RefreshCw class="w-3 h-3 flex-shrink-0" aria-hidden="true" />
        <span>{{ t('ai.advisor.runAge', { age: ageLabel(runCreatedAt) }) }}</span>
        <span v-if="stale" class="font-medium">· {{ t('ai.advisor.staleHint') }}</span>
      </p>
      <p v-else-if="tab === 'integrity'" class="text-xs text-fg-muted">
        {{ t('ai.integrity.description') }}
      </p>
    </div>

    <!-- Compact severity strip. The findings below are the page; this is a
         one-line read of how bad it is, not four hero numbers. -->
    <section
      v-if="hasSummary"
      class="nf-card px-4 py-3 mb-6 flex flex-wrap items-center gap-x-7 gap-y-3"
      :aria-label="t('ai.advisor.summaryLabel')"
    >
      <div v-for="s in summary" :key="s.severity" class="flex items-center gap-2">
        <component
          :is="severityIcon[s.severity]"
          class="w-4 h-4 flex-shrink-0"
          :class="severityText[s.severity]"
          :stroke-width="1.9"
          aria-hidden="true"
        />
        <span
          class="text-lg font-semibold tabular-nums leading-none"
          :class="severityText[s.severity]"
        >
          {{ s.count }}
        </span>
        <span class="text-sm text-fg-muted">{{ s.label }}</span>
      </div>
      <div class="sm:ml-auto flex items-center gap-2">
        <span class="text-lg font-semibold tabular-nums leading-none text-fg">
          {{ counts.total }}
        </span>
        <span class="text-sm text-fg-muted">{{ t('ai.advisor.total') }}</span>
      </div>
    </section>

    <!-- ============================== FINDINGS ============================== -->
    <section>
      <!-- Loading (advisor first paint, or integrity's first pass) -->
      <div
        v-if="tab === 'advisor' ? loading : integrityLoading && !integrityIssues.length"
        class="space-y-3"
        aria-busy="true"
      >
        <div v-for="i in 3" :key="i" class="nf-card p-5 space-y-2.5">
          <Skeleton width="30%" height="1rem" />
          <Skeleton width="80%" height="0.75rem" />
          <Skeleton width="60%" height="0.75rem" />
        </div>
      </div>

      <!-- Advisor never run -->
      <EmptyState
        v-else-if="tab === 'advisor' && runId === null"
        :icon="Sparkles"
        :title="t('ai.advisor.emptyTitle')"
        :description="
          status?.enabled ? t('ai.advisor.emptyDescription') : t('ai.advisor.disabledDescription')
        "
      >
        <template v-if="status?.enabled" #action>
          <Button variant="primary" :loading="refreshing" @click="refresh">
            <RefreshCw class="w-4 h-4" aria-hidden="true" />
            {{ t('ai.advisor.runFirst') }}
          </Button>
        </template>
      </EmptyState>

      <!-- Advisor ran, nothing to report -->
      <EmptyState
        v-else-if="tab === 'advisor' && counts.total === 0"
        :icon="Lightbulb"
        :title="t('ai.advisor.cleanTitle')"
        :description="t('ai.advisor.cleanDescription')"
      >
        <template v-if="status?.enabled" #action>
          <Button variant="secondary" :loading="refreshing" @click="refresh">
            <RefreshCw class="w-4 h-4" aria-hidden="true" />
            {{ t('ai.advisor.refresh') }}
          </Button>
        </template>
      </EmptyState>

      <!-- Integrity clean -->
      <EmptyState
        v-else-if="tab === 'integrity' && integrityLoaded && counts.total === 0"
        :icon="ShieldCheck"
        :title="t('ai.integrity.cleanTitle')"
        :description="t('ai.integrity.cleanDescription')"
      />

      <!-- Integrity not started yet (load failed, or the lazy fetch is queued) -->
      <EmptyState
        v-else-if="tab === 'integrity' && !integrityLoaded"
        :icon="ShieldCheck"
        :title="t('ai.integrity.tab')"
        :description="t('ai.integrity.notRunDescription')"
      >
        <template #action>
          <Button variant="primary" :loading="integrityLoading" @click="loadIntegrity">
            <RefreshCw class="w-4 h-4" aria-hidden="true" />
            {{ t('ai.integrity.run') }}
          </Button>
        </template>
      </EmptyState>

      <!-- The list. Grouped by severity, worst first. -->
      <div v-else class="space-y-8">
        <div v-for="group in visibleGroups" :key="group.severity">
          <h2 class="nf-section-title flex items-center gap-2 mb-3">
            <component
              :is="severityIcon[group.severity]"
              class="w-4 h-4 flex-shrink-0"
              :class="severityText[group.severity]"
              :stroke-width="1.9"
              aria-hidden="true"
            />
            {{ severityLabel(group.severity) }}
            <span class="text-sm font-normal text-fg-subtle tabular-nums">
              {{ group.items.length }}
            </span>
          </h2>

          <ul class="space-y-3">
            <li
              v-for="f in group.items"
              :key="f.key"
              class="nf-card border-l-[3px] p-5"
              :class="severityRail[f.severity]"
            >
              <!-- 1. What kind of problem this is -->
              <div class="flex items-center gap-2 flex-wrap">
                <Badge :tone="severityTone[f.severity]">{{ severityLabel(f.severity) }}</Badge>
                <Badge tone="muted">{{ t(categoryLabelKey[f.category] ?? '') }}</Badge>
                <Badge
                  v-if="f.streak >= 2"
                  tone="danger"
                  :title="t('ai.advisor.streakTooltip', { n: f.streak })"
                >
                  {{ t('ai.advisor.recurringBadge', { n: f.streak }) }}
                </Badge>
              </div>

              <!-- 2. The finding itself -->
              <h3 class="text-md font-semibold text-fg tracking-[-0.01em] mt-2.5">
                {{ f.title }}
              </h3>
              <p class="text-base text-fg-muted leading-relaxed mt-1 max-w-[80ch]">
                {{ f.description }}
              </p>

              <!-- 3. What to do about it -->
              <div
                v-if="f.recommendation"
                class="mt-3.5 rounded-md bg-muted/60 border border-border px-3.5 py-3"
              >
                <p class="nf-label uppercase tracking-wide">
                  {{ t('ai.advisor.recommendation') }}
                </p>
                <p class="text-base text-fg leading-relaxed mt-1 max-w-[80ch]">
                  {{ f.recommendation }}
                </p>
              </div>

              <!-- 4. Where to go next -->
              <div v-if="f.entities.length" class="mt-3.5">
                <p class="nf-label mb-1.5">{{ t('ai.advisor.affectedTitle') }}</p>
                <div class="flex flex-wrap gap-1.5">
                  <RouterLink
                    v-for="(e, idx) in f.entities"
                    :key="`${e.type}-${e.id}-${idx}`"
                    v-slot="{ href, navigate }"
                    :to="entityRoute(e) ?? ''"
                    custom
                  >
                    <a
                      :href="entityRoute(e) ? href : undefined"
                      :class="[
                        'inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border text-xs font-medium',
                        'transition-colors duration-150 ease-soft',
                        entityRoute(e)
                          ? 'border-border bg-surface text-fg hover:border-primary-500 hover:text-primary-600 dark:hover:text-primary-400 cursor-pointer'
                          : 'border-transparent bg-muted text-fg-subtle cursor-default',
                      ]"
                      @click="entityRoute(e) ? navigate($event) : null"
                    >
                      <component
                        :is="entityIcon[e.type] ?? Server"
                        class="w-3 h-3 flex-shrink-0"
                        aria-hidden="true"
                      />
                      {{ entityLabel(e) }}
                    </a>
                  </RouterLink>
                </div>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </section>
  </div>
</template>

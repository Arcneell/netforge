<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, Check, ClipboardList, Send, X as XIcon } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { aiApi, type ActionDraft, type ActionDraftStatus } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'
import { formatDate } from '@/utils/formatters'

const { t, te } = useI18n()
const { describe } = useApiErrorMessage()

function draftErrorMessage(d: ActionDraft): string {
  // Prefer the stable code stored on the row so the card translates with
  // the active locale. Fall back to the raw `error_message` for older rows
  // (or unknown codes) — better than an empty bubble.
  const code = d.error_code
  if (code) {
    const key = `errorCodes.${code}`
    if (te(key)) return t(key)
  }
  return d.error_message ?? ''
}
const { error: toastError, success: toastSuccess } = useToast()

const prompt = ref('')
const drafting = ref(false)
const drafts = ref<ActionDraft[]>([])
const loading = ref(true)
const busyId = ref<number | null>(null)
// The draft the operator is about to apply. Apply writes to the inventory
// and NetForge has no undo for it, so it goes through a confirmation.
const confirming = ref<ActionDraft | null>(null)

async function load() {
  loading.value = true
  try {
    drafts.value = await aiApi.listDrafts()
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

async function createDraft() {
  if (!prompt.value.trim() || drafting.value) return
  drafting.value = true
  try {
    const d = await aiApi.createDraft(prompt.value.trim())
    drafts.value.unshift(d)
    prompt.value = ''
    toastSuccess(t('ai.drafts.draftedToast'))
  } catch (err) {
    toastError(describe(err))
  } finally {
    drafting.value = false
  }
}

async function applyDraft(id: number) {
  busyId.value = id
  try {
    const updated = await aiApi.applyDraft(id)
    const i = drafts.value.findIndex((d) => d.id === id)
    if (i >= 0) drafts.value[i] = updated
    toastSuccess(t('ai.drafts.appliedToast'))
  } catch (err) {
    // The apply route either returns the updated row (failed status) or
    // raises — refresh either way so the UI shows the latest state.
    toastError(describe(err))
    void load()
  } finally {
    busyId.value = null
  }
}

/** Confirmation gate in front of `applyDraft` — the write is not undoable. */
async function confirmApply() {
  const target = confirming.value
  if (!target) return
  await applyDraft(target.id)
  confirming.value = null
}

/** Backdrop / Escape / Cancel — ignored while the apply is in flight. */
function cancelApply() {
  if (busyId.value !== null) return
  confirming.value = null
}

async function rejectDraft(id: number) {
  busyId.value = id
  try {
    const updated = await aiApi.rejectDraft(id)
    const i = drafts.value.findIndex((d) => d.id === id)
    if (i >= 0) drafts.value[i] = updated
  } catch (err) {
    toastError(describe(err))
  } finally {
    busyId.value = null
  }
}

onMounted(load)

const statusTone: Record<ActionDraftStatus, 'warning' | 'success' | 'muted' | 'danger'> = {
  pending: 'warning',
  applied: 'success',
  rejected: 'muted',
  failed: 'danger',
}

/** Left rail colour — lets the eye find the undecided drafts in one pass. */
const statusRail: Record<ActionDraftStatus, string> = {
  pending: 'border-l-warning',
  applied: 'border-l-success',
  rejected: 'border-l-border-strong',
  failed: 'border-l-danger',
}

const intentLabel: Record<string, string> = {
  create_site: 'ai.drafts.intents.createSite',
  create_room: 'ai.drafts.intents.createRoom',
  create_vlan: 'ai.drafts.intents.createVlan',
  create_subnet: 'ai.drafts.intents.createSubnet',
}

function intentDisplay(intent: string): string {
  return t(intentLabel[intent] ?? intent)
}

function payloadString(p: Record<string, unknown>): string {
  // Compact JSON preview; the <pre> CSS keeps it readable inside the card.
  return JSON.stringify(p, null, 2)
}

/**
 * The payload is what the operator is actually approving, so it is rendered
 * as a field/value list rather than a JSON blob. Scalars print as-is;
 * nested structures fall back to compact JSON so nothing is hidden. The raw
 * document stays one disclosure away.
 */
interface PayloadField {
  key: string
  value: string
}

function payloadFields(p: Record<string, unknown>): PayloadField[] {
  return Object.entries(p ?? {}).map(([key, raw]) => {
    let value: string
    if (raw === null || raw === undefined) value = '—'
    else if (typeof raw === 'object') value = JSON.stringify(raw)
    else value = String(raw)
    return { key, value }
  })
}

const pendingCount = computed(() => drafts.value.filter((d) => d.status === 'pending').length)
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('ai.drafts.title')" :subtitle="t('ai.drafts.subtitle')">
      <template #help>
        <HelpTooltip :text="t('ai.drafts.help')" placement="bottom" />
      </template>
    </PageHeader>

    <!-- Composer -->
    <form class="nf-card p-4 mb-6 max-w-3xl" @submit.prevent="createDraft">
      <label class="block">
        <span class="nf-label block mb-1.5">{{ t('ai.drafts.composerLabel') }}</span>
        <textarea
          v-model="prompt"
          rows="2"
          class="nf-input resize-none"
          :placeholder="t('ai.drafts.composerPlaceholder')"
        />
      </label>
      <div class="flex items-center justify-between gap-3 flex-wrap mt-3">
        <p class="text-xs text-fg-muted max-w-md">{{ t('ai.drafts.safetyHint') }}</p>
        <Button type="submit" variant="primary" :loading="drafting" :disabled="!prompt.trim()">
          <Send class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.drafts.draftButton') }}
        </Button>
      </div>
    </form>

    <section>
      <div v-if="loading" class="space-y-3" aria-busy="true">
        <div v-for="i in 3" :key="i" class="nf-card p-5 space-y-2.5">
          <Skeleton width="30%" height="1rem" />
          <Skeleton width="70%" height="0.75rem" />
          <Skeleton width="50%" height="0.75rem" />
        </div>
      </div>

      <EmptyState
        v-else-if="drafts.length === 0"
        :icon="ClipboardList"
        :title="t('ai.drafts.emptyTitle')"
        :description="t('ai.drafts.emptyDescription')"
      />

      <template v-else>
        <div class="nf-toolbar">
          <h2 class="nf-section-title">{{ t('ai.drafts.listTitle') }}</h2>
          <Badge v-if="pendingCount > 0" tone="warning" size="md">
            {{ t('ai.drafts.pendingHint', { n: pendingCount }) }}
          </Badge>
        </div>

        <ul class="space-y-4">
          <li
            v-for="d in drafts"
            :key="d.id"
            class="nf-card border-l-[3px] overflow-hidden"
            :class="statusRail[d.status]"
          >
            <!-- What was asked for -->
            <div class="p-5">
              <div class="flex items-center gap-2 flex-wrap">
                <Badge :tone="statusTone[d.status]">{{ t(`ai.drafts.status.${d.status}`) }}</Badge>
                <Badge tone="muted">{{ intentDisplay(d.intent) }}</Badge>
                <span class="text-xs text-fg-subtle tabular-nums">
                  {{ formatDate(d.created_at) }}
                </span>
              </div>
              <p class="text-md text-fg leading-snug mt-2.5 max-w-[80ch]">{{ d.prompt }}</p>
            </div>

            <!-- What will actually be written -->
            <div class="border-t border-border bg-muted/40 px-5 py-4">
              <p class="nf-label uppercase tracking-wide">{{ t('ai.drafts.payloadTitle') }}</p>
              <dl class="mt-2 grid gap-x-8 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
                <div v-for="f in payloadFields(d.payload)" :key="f.key" class="min-w-0">
                  <dt class="nf-label truncate">{{ f.key }}</dt>
                  <dd class="text-base font-mono text-fg break-words">{{ f.value }}</dd>
                </div>
              </dl>
              <details class="mt-3">
                <summary
                  class="text-xs text-fg-muted hover:text-fg cursor-pointer select-none w-fit transition-colors duration-150 ease-soft"
                >
                  {{ t('ai.drafts.rawPayload') }}
                </summary>
                <pre
                  class="mt-2 p-3 rounded-md bg-surface border border-border text-xs font-mono leading-relaxed overflow-x-auto"
                ><code>{{ payloadString(d.payload) }}</code></pre>
              </details>
            </div>

            <!-- The decision. Only a pending draft has one to make. -->
            <div
              v-if="d.status === 'pending'"
              class="border-t border-border px-5 py-4 flex flex-wrap items-center justify-between gap-3"
            >
              <p class="text-xs text-fg-muted flex items-start gap-1.5 max-w-md">
                <AlertTriangle
                  class="w-3.5 h-3.5 text-warning flex-shrink-0 mt-px"
                  :stroke-width="1.9"
                  aria-hidden="true"
                />
                <span>{{ t('ai.drafts.decisionHint') }}</span>
              </p>
              <div class="flex items-center gap-2 ml-auto">
                <Button
                  variant="secondary"
                  :loading="busyId === d.id"
                  :disabled="busyId !== null && busyId !== d.id"
                  @click="rejectDraft(d.id)"
                >
                  <XIcon class="w-4 h-4" aria-hidden="true" />
                  {{ t('ai.drafts.reject') }}
                </Button>
                <Button
                  variant="primary"
                  :loading="busyId === d.id"
                  :disabled="busyId !== null && busyId !== d.id"
                  @click="confirming = d"
                >
                  <Check class="w-4 h-4" aria-hidden="true" />
                  {{ t('ai.drafts.apply') }}
                </Button>
              </div>
            </div>

            <!-- Outcome of a decision already taken -->
            <div
              v-else-if="d.applied_resource"
              class="border-t border-border px-5 py-3 flex items-center gap-2 flex-wrap"
            >
              <span class="nf-label">{{ t('ai.drafts.appliedResourceLabel') }}</span>
              <span class="text-base font-mono text-fg">{{ d.applied_resource }}</span>
            </div>

            <div
              v-if="d.error_message || d.error_code"
              class="border-t border-border bg-danger/5 px-5 py-3 flex items-start gap-2"
            >
              <AlertTriangle
                class="w-3.5 h-3.5 text-danger flex-shrink-0 mt-0.5"
                :stroke-width="1.9"
                aria-hidden="true"
              />
              <div class="min-w-0">
                <p class="text-sm text-danger break-words">{{ draftErrorMessage(d) }}</p>
                <p class="text-xs text-fg-muted mt-0.5">{{ t('ai.drafts.failedHint') }}</p>
              </div>
            </div>
          </li>
        </ul>
      </template>
    </section>

    <!-- Apply is a real write with no rollback — name that before the click. -->
    <ConfirmDialog
      :open="confirming !== null"
      :title="t('ai.drafts.confirmApplyTitle')"
      :confirm-label="t('ai.drafts.apply')"
      :loading="confirming !== null && busyId === confirming.id"
      @cancel="cancelApply"
      @confirm="confirmApply"
    >
      <p v-if="confirming" class="text-base text-fg">
        {{ t('ai.drafts.confirmApplyMessage', { intent: intentDisplay(confirming.intent) }) }}
      </p>
      <dl v-if="confirming" class="mt-3 space-y-1.5">
        <div
          v-for="f in payloadFields(confirming.payload)"
          :key="f.key"
          class="flex items-baseline gap-3"
        >
          <dt class="nf-label flex-shrink-0 w-32 truncate">{{ f.key }}</dt>
          <dd class="text-base font-mono text-fg break-words min-w-0">{{ f.value }}</dd>
        </div>
      </dl>
      <p
        class="mt-4 text-sm text-warning bg-warning/10 rounded-md px-3 py-2 flex items-start gap-2"
      >
        <AlertTriangle
          class="w-3.5 h-3.5 flex-shrink-0 mt-0.5"
          :stroke-width="1.9"
          aria-hidden="true"
        />
        <span>{{ t('ai.drafts.confirmApplyWarning') }}</span>
      </p>
    </ConfirmDialog>
  </div>
</template>

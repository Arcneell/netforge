<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, ClipboardList, Send, X as XIcon } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { aiApi, type ActionDraft, type ActionDraftStatus } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

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
  // Compact JSON preview; the textarea CSS keeps it readable inside the card.
  return JSON.stringify(p, null, 2)
}

const pendingCount = computed(() => drafts.value.filter((d) => d.status === 'pending').length)
</script>

<template>
  <div class="p-4 sm:p-8 max-w-5xl mx-auto">
    <PageHeader :title="t('ai.drafts.title')" :subtitle="t('ai.drafts.subtitle')">
      <template #help>
        <HelpTooltip :text="t('ai.drafts.help')" placement="bottom" />
      </template>
    </PageHeader>

    <!-- Composer -->
    <form class="nf-card p-4 mb-6 space-y-3" @submit.prevent="createDraft">
      <label class="block">
        <span class="block text-[11px] uppercase tracking-wider text-fg-muted font-semibold mb-1">
          {{ t('ai.drafts.composerLabel') }}
        </span>
        <textarea
          v-model="prompt"
          rows="2"
          class="w-full px-3 py-2 rounded border border-border bg-surface text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          :placeholder="t('ai.drafts.composerPlaceholder')"
        />
      </label>
      <div class="flex items-center justify-between gap-3 flex-wrap">
        <p class="text-xs text-fg-muted">{{ t('ai.drafts.safetyHint') }}</p>
        <Button
          type="submit"
          variant="primary"
          shape="pill"
          :loading="drafting"
          :disabled="!prompt.trim()"
        >
          <Send class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.drafts.draftButton') }}
        </Button>
      </div>
    </form>

    <div v-if="loading" class="space-y-3" aria-busy="true">
      <div v-for="i in 3" :key="i" class="nf-card p-5 space-y-2">
        <Skeleton width="40%" height="1rem" />
        <Skeleton width="80%" height="0.75rem" />
      </div>
    </div>

    <EmptyState
      v-else-if="drafts.length === 0"
      :icon="ClipboardList"
      :title="t('ai.drafts.emptyTitle')"
      :description="t('ai.drafts.emptyDescription')"
    />

    <template v-else>
      <p v-if="pendingCount > 0" class="text-xs text-fg-muted mb-3 tabular-nums">
        {{ t('ai.drafts.pendingHint', { n: pendingCount }) }}
      </p>
      <ul class="space-y-3">
        <li v-for="d in drafts" :key="d.id" class="nf-card p-5">
          <div class="flex items-start justify-between gap-3 flex-wrap mb-2">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 flex-wrap">
                <Badge :tone="statusTone[d.status]">{{ t(`ai.drafts.status.${d.status}`) }}</Badge>
                <Badge tone="muted">{{ intentDisplay(d.intent) }}</Badge>
                <span v-if="d.applied_resource" class="text-[11px] font-mono text-fg-muted">
                  → {{ d.applied_resource }}
                </span>
              </div>
              <p class="text-sm font-medium mt-2 leading-snug">{{ d.prompt }}</p>
            </div>
            <div v-if="d.status === 'pending'" class="flex items-center gap-2 flex-shrink-0">
              <Button
                variant="ghost"
                size="sm"
                :loading="busyId === d.id"
                :disabled="busyId !== null && busyId !== d.id"
                @click="rejectDraft(d.id)"
              >
                <XIcon class="w-4 h-4" aria-hidden="true" />
                {{ t('ai.drafts.reject') }}
              </Button>
              <Button
                variant="primary"
                size="sm"
                shape="pill"
                :loading="busyId === d.id"
                :disabled="busyId !== null && busyId !== d.id"
                @click="applyDraft(d.id)"
              >
                <Check class="w-4 h-4" aria-hidden="true" />
                {{ t('ai.drafts.apply') }}
              </Button>
            </div>
          </div>

          <pre
            class="mt-2 p-3 rounded-md bg-muted/60 text-xs font-mono leading-relaxed overflow-x-auto"
          ><code>{{ payloadString(d.payload) }}</code></pre>

          <p
            v-if="d.error_message || d.error_code"
            class="text-xs text-danger mt-2 p-2 rounded bg-danger/5 border border-danger/20"
          >
            {{ draftErrorMessage(d) }}
          </p>
        </li>
      </ul>
    </template>
  </div>
</template>

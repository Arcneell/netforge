<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Check,
  Copy,
  History,
  KeyRound,
  Pencil,
  Plus,
  RotateCcw,
  Send,
  Trash2,
  AlertTriangle,
} from '@lucide/vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import Input from '@/components/ui/Input.vue'
import Modal from '@/components/ui/Modal.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { webhooksApi } from '@/api'
import type { Webhook, WebhookCreated, WebhookDelivery } from '@/api'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { formatDate } from '@/utils/formatters'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { describe } = useApiErrorMessage()

const webhooks = ref<Webhook[]>([])
const loading = ref(false)

const editorOpen = ref(false)
const editing = ref<Webhook | null>(null)
const form = ref({ name: '', url: '', events: '*', enabled: true })
const saving = ref(false)
const formError = ref<string | null>(null)

const justCreated = ref<WebhookCreated | null>(null)
const copied = ref(false)

const toDelete = ref<Webhook | null>(null)
const deleting = ref(false)

// Rotating invalidates the secret the receiver is already verifying against,
// so it goes through the same confirm gate as a delete instead of firing on
// the first click.
const toRotate = ref<Webhook | null>(null)
const rotating = ref(false)

const deliveriesOpen = ref(false)
const deliveriesFor = ref<Webhook | null>(null)
const deliveries = ref<WebhookDelivery[]>([])
const deliveriesLoading = ref(false)

// Wrap in computed so labels follow the i18n locale.
const columns = computed<DataTableColumn[]>(() => [
  { key: 'name', label: t('webhooks.fields.name'), cellClass: 'font-medium' },
  { key: 'url', label: t('webhooks.fields.url'), cellClass: 'font-mono text-xs truncate max-w-md' },
  { key: 'events', label: t('webhooks.fields.events'), cellClass: 'text-xs' },
  { key: 'status', label: t('webhooks.fields.status'), cellClass: 'w-32' },
  { key: 'stats', label: t('webhooks.fields.stats'), cellClass: 'w-40 text-xs' },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-48' },
])

const deliveryColumns = computed<DataTableColumn[]>(() => [
  { key: 'created_at', label: t('webhooks.delivery.when'), cellClass: 'w-44 whitespace-nowrap' },
  { key: 'event', label: t('webhooks.delivery.event'), cellClass: 'font-mono text-xs' },
  { key: 'status_code', label: t('webhooks.delivery.status'), cellClass: 'w-20' },
  { key: 'latency_ms', label: t('webhooks.delivery.latency'), cellClass: 'w-20' },
  { key: 'error', label: t('webhooks.delivery.error') },
])

async function load() {
  loading.value = true
  try {
    webhooks.value = await webhooksApi.list()
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openCreate() {
  editing.value = null
  form.value = { name: '', url: '', events: '*', enabled: true }
  formError.value = null
  justCreated.value = null
  copied.value = false
  editorOpen.value = true
}

function openEdit(row: Webhook) {
  editing.value = row
  form.value = {
    name: row.name,
    url: row.url,
    events: row.events.join(', '),
    enabled: row.enabled,
  }
  formError.value = null
  editorOpen.value = true
}

// Re-pointing an existing webhook silently redirects live traffic. Surface it
// in the form, before the save, rather than as a toast afterwards.
const urlChanged = computed(() => !!editing.value && form.value.url.trim() !== editing.value.url)
const beingDisabled = computed(() => !form.value.enabled)

function parseEvents(): string[] {
  return form.value.events
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

async function submitForm(e: Event) {
  e.preventDefault()
  if (saving.value) return
  if (!form.value.name.trim() || !form.value.url.trim()) {
    formError.value = t('common.validation.required')
    return
  }
  const events = parseEvents()
  if (events.length === 0) {
    formError.value = t('webhooks.errors.eventsRequired')
    return
  }
  saving.value = true
  formError.value = null
  try {
    if (editing.value) {
      await webhooksApi.update(editing.value.id, {
        name: form.value.name.trim(),
        url: form.value.url.trim(),
        events,
        enabled: form.value.enabled,
      })
      success(t('common.success'))
      editorOpen.value = false
    } else {
      const created = await webhooksApi.create({
        name: form.value.name.trim(),
        url: form.value.url.trim(),
        events,
        enabled: form.value.enabled,
      })
      justCreated.value = created
      editorOpen.value = false
    }
    await load()
  } catch (err) {
    formError.value = describe(err)
  } finally {
    saving.value = false
  }
}

async function copySecret() {
  if (!justCreated.value) return
  try {
    await navigator.clipboard.writeText(justCreated.value.secret)
    copied.value = true
    success(t('webhooks.secretCopied'))
  } catch {
    toastError(t('webhooks.copyFailed'))
  }
}

function closeBanner() {
  justCreated.value = null
  copied.value = false
}

async function confirmDelete() {
  if (!toDelete.value) return
  deleting.value = true
  try {
    await webhooksApi.delete(toDelete.value.id)
    success(t('common.success'))
    toDelete.value = null
    await load()
  } catch (err) {
    toastError(describe(err))
  } finally {
    deleting.value = false
  }
}

async function confirmRotate() {
  if (!toRotate.value) return
  rotating.value = true
  try {
    const result = await webhooksApi.rotateSecret(toRotate.value.id)
    justCreated.value = result
    copied.value = false
    success(t('webhooks.secretRotated'))
    toRotate.value = null
  } catch (err) {
    toastError(describe(err))
  } finally {
    rotating.value = false
  }
}

async function sendTest(row: Webhook) {
  try {
    const delivery = await webhooksApi.test(row.id)
    if (delivery.success) {
      success(t('webhooks.testOk', { code: delivery.status_code }))
    } else {
      toastError(t('webhooks.testFailed', { error: delivery.error ?? 'unknown' }))
    }
    await load()
  } catch (err) {
    toastError(describe(err))
  }
}

async function viewDeliveries(row: Webhook) {
  deliveriesFor.value = row
  deliveriesOpen.value = true
  deliveriesLoading.value = true
  try {
    deliveries.value = await webhooksApi.listDeliveries(row.id, 50)
  } catch (err) {
    toastError(describe(err))
  } finally {
    deliveriesLoading.value = false
  }
}

const editorTitle = computed(() => (editing.value ? t('webhooks.edit') : t('webhooks.new')))
</script>

<template>
  <section>
    <!-- Shown-once signing secret (fresh webhook or rotation). Amber, not
         green: this is a deadline, not a congratulation. -->
    <div
      v-if="justCreated"
      class="nf-card border-warning/45 bg-warning/[0.06] p-5 mb-6"
      role="alert"
    >
      <div class="flex items-start gap-3">
        <span
          class="inline-flex items-center justify-center w-9 h-9 rounded-md bg-warning/15 text-warning flex-shrink-0"
        >
          <KeyRound class="w-4 h-4" aria-hidden="true" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <p class="text-md font-semibold text-fg">{{ t('webhooks.secretTitle') }}</p>
            <Badge tone="warning">{{ t('webhooks.shownOnce') }}</Badge>
          </div>
          <p class="text-sm text-fg-muted mt-1 max-w-2xl">{{ t('webhooks.secretHint') }}</p>

          <code
            class="block mt-3 px-3 py-2.5 rounded-md border border-border-strong bg-surface font-mono text-sm text-fg break-all select-all"
          >
            {{ justCreated.secret }}
          </code>

          <div class="mt-3 flex items-center gap-2 flex-wrap">
            <Button variant="primary" @click="copySecret">
              <Check v-if="copied" class="w-4 h-4" aria-hidden="true" />
              <Copy v-else class="w-4 h-4" aria-hidden="true" />
              {{ copied ? t('common.copied') : t('common.copy') }}
            </Button>
            <Button variant="secondary" @click="closeBanner">
              {{ t('webhooks.secretStored') }}
            </Button>
          </div>
        </div>
      </div>
    </div>

    <div class="nf-toolbar items-start justify-between">
      <div class="min-w-0">
        <h2 class="nf-section-title">{{ t('settings.webhooksTab') }}</h2>
        <p class="text-sm text-fg-muted mt-1 max-w-2xl inline-flex items-start gap-1.5">
          <span>{{ t('webhooks.subtitle') }}</span>
          <HelpTooltip :text="t('webhooks.help.section')" placement="bottom" />
        </p>
      </div>
      <Button variant="primary" @click="openCreate">
        <Plus class="w-4 h-4" aria-hidden="true" />
        {{ t('webhooks.new') }}
      </Button>
    </div>

    <DataTable
      :columns="columns"
      :rows="webhooks"
      :loading="loading"
      :empty-title="t('webhooks.empty.title')"
      :empty-description="t('webhooks.empty.description')"
    >
      <template #empty-action>
        <Button variant="primary" @click="openCreate">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('webhooks.new') }}
        </Button>
      </template>
      <template #cell-events="{ row }">
        <span class="font-mono text-xs">{{ row.events.join(', ') }}</span>
      </template>
      <template #cell-status="{ row }">
        <Badge :tone="row.enabled ? 'success' : 'neutral'">
          {{ row.enabled ? t('webhooks.status.enabled') : t('webhooks.status.disabled') }}
        </Badge>
      </template>
      <template #cell-stats="{ row }">
        <div class="flex flex-col gap-0.5">
          <span class="tabular-nums" :class="row.total_failures > 0 ? 'text-warning' : 'text-fg'">
            {{ row.total_deliveries }} / {{ row.total_failures }} {{ t('webhooks.failuresShort') }}
          </span>
          <span v-if="row.last_delivery_at" class="text-fg-subtle">
            {{ formatDate(row.last_delivery_at) }}
          </span>
        </div>
      </template>
      <template #cell-actions="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            :aria-label="`${t('webhooks.viewDeliveries')} — ${row.name}`"
            :title="t('webhooks.viewDeliveries')"
            @click.stop="viewDeliveries(row)"
          >
            <History class="w-4 h-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="`${t('webhooks.sendTest')} — ${row.name}`"
            :title="t('webhooks.sendTest')"
            @click.stop="sendTest(row)"
          >
            <Send class="w-4 h-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="`${t('common.edit')} ${row.name}`"
            :title="t('common.edit')"
            @click.stop="openEdit(row)"
          >
            <Pencil class="w-4 h-4" aria-hidden="true" />
          </Button>
          <!-- Everything past this hairline breaks a working integration. -->
          <span class="w-px h-5 bg-border" aria-hidden="true" />
          <Button
            variant="ghost"
            size="sm"
            :aria-label="`${t('webhooks.rotateSecret')} — ${row.name}`"
            :title="t('webhooks.rotateSecret')"
            @click.stop="toRotate = row"
          >
            <RotateCcw class="w-4 h-4 text-warning" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="`${t('common.delete')} ${row.name}`"
            :title="t('common.delete')"
            @click.stop="toDelete = row"
          >
            <Trash2 class="w-4 h-4 text-danger" aria-hidden="true" />
          </Button>
        </div>
      </template>
    </DataTable>

    <Modal :open="editorOpen" :title="editorTitle" size="md" @close="editorOpen = false">
      <form class="flex flex-col gap-4" @submit="submitForm">
        <FormField :label="t('webhooks.fields.name')" :error="formError" required>
          <template #default="{ id, invalid }">
            <Input
              :id="id"
              v-model="form.name"
              :invalid="invalid"
              :placeholder="t('webhooks.namePlaceholder')"
              maxlength="100"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('webhooks.fields.url')" required>
          <template #help>
            <HelpTooltip :text="t('webhooks.help.url')" />
          </template>
          <template #default="{ id }">
            <Input
              :id="id"
              v-model="form.url"
              type="url"
              placeholder="https://example.com/hook"
              maxlength="500"
              autocomplete="off"
            />
          </template>
        </FormField>

        <!-- Re-targeting a live webhook: say so before Save, not after. -->
        <p
          v-if="urlChanged"
          class="-mt-2 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/[0.06] px-3 py-2.5 text-sm text-fg"
          role="status"
        >
          <AlertTriangle class="w-4 h-4 text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
          <span>{{ t('webhooks.urlChangedWarning') }}</span>
        </p>

        <FormField :label="t('webhooks.fields.events')" :hint="t('webhooks.eventsHint')" required>
          <template #help>
            <HelpTooltip :text="t('webhooks.help.events')" />
          </template>
          <template #default="{ id }">
            <Input
              :id="id"
              v-model="form.events"
              placeholder="*, port.create, site.*"
              autocomplete="off"
            />
          </template>
        </FormField>

        <div class="rounded-md border border-border bg-muted/40 px-3 py-2.5">
          <label class="flex items-center gap-2 text-base font-medium text-fg">
            <input
              v-model="form.enabled"
              type="checkbox"
              class="rounded border-border-strong text-primary-600 focus:ring-0"
            />
            {{ t('webhooks.fields.enabled') }}
          </label>
          <p v-if="beingDisabled" class="text-sm text-fg-muted mt-1.5">
            {{ t('webhooks.disabledHint') }}
          </p>
        </div>
      </form>
      <template #footer>
        <div class="flex justify-end gap-2">
          <Button variant="secondary" :disabled="saving" @click="editorOpen = false">
            {{ t('common.cancel') }}
          </Button>
          <Button variant="primary" :loading="saving" @click="submitForm">
            {{ t('common.save') }}
          </Button>
        </div>
      </template>
    </Modal>

    <Modal
      :open="deliveriesOpen"
      :title="t('webhooks.deliveriesTitle', { name: deliveriesFor?.name ?? '' })"
      size="lg"
      @close="deliveriesOpen = false"
    >
      <DataTable
        :columns="deliveryColumns"
        :rows="deliveries"
        :loading="deliveriesLoading"
        :empty-title="t('webhooks.delivery.empty')"
        :empty-description="t('webhooks.delivery.emptyHint')"
      >
        <template #cell-created_at="{ row }">
          <span class="text-fg-muted">{{ formatDate(row.created_at) }}</span>
        </template>
        <template #cell-status_code="{ row }">
          <Badge :tone="row.success ? 'success' : 'danger'" monospace>
            {{ row.status_code || '—' }}
          </Badge>
        </template>
        <template #cell-latency_ms="{ row }">
          <span class="text-fg-muted tabular-nums">{{ row.latency_ms }} ms</span>
        </template>
        <template #cell-error="{ row }">
          <span class="text-fg-muted text-xs truncate block max-w-md">
            {{ row.error || '—' }}
          </span>
        </template>
      </DataTable>
    </Modal>

    <ConfirmDialog
      :open="!!toRotate"
      :title="t('webhooks.confirmRotateTitle', { name: toRotate?.name ?? '' })"
      :message="t('webhooks.confirmRotateMessage')"
      :confirm-label="t('webhooks.rotateSecret')"
      variant="danger"
      :loading="rotating"
      @confirm="confirmRotate"
      @cancel="toRotate = null"
    />

    <ConfirmDialog
      :open="!!toDelete"
      :title="t('webhooks.confirmDeleteTitle', { name: toDelete?.name ?? '' })"
      :message="t('webhooks.confirmDeleteMessage')"
      :confirm-label="t('common.delete')"
      variant="danger"
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="toDelete = null"
    />
  </section>
</template>

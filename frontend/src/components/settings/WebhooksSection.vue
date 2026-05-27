<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Copy, Plus, Pencil, Trash2, CheckCircle2, Send, RotateCcw } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
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
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-40' },
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

async function rotateSecret(row: Webhook) {
  try {
    const result = await webhooksApi.rotateSecret(row.id)
    justCreated.value = result
    success(t('webhooks.secretRotated'))
  } catch (err) {
    toastError(describe(err))
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
    <!-- Plaintext secret banner -->
    <div
      v-if="justCreated"
      class="nf-card border-success/40 bg-success/5 p-4 mb-4 flex items-start gap-3"
      role="status"
    >
      <CheckCircle2 class="w-5 h-5 text-success flex-shrink-0 mt-0.5" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <p class="text-sm font-medium text-fg">{{ t('webhooks.secretTitle') }}</p>
        <p class="text-xs text-fg-muted mt-0.5">{{ t('webhooks.secretHint') }}</p>
        <div class="mt-2 flex items-center gap-2">
          <code
            class="flex-1 min-w-0 truncate font-mono text-xs px-2 py-1.5 rounded border border-border bg-surface"
          >
            {{ justCreated.secret }}
          </code>
          <Button variant="secondary" size="sm" @click="copySecret">
            <Copy class="w-4 h-4" aria-hidden="true" />
            {{ copied ? t('common.copied') : t('common.copy') }}
          </Button>
          <Button variant="ghost" size="sm" @click="closeBanner">
            {{ t('common.close') }}
          </Button>
        </div>
      </div>
    </div>

    <div class="flex items-start justify-between gap-3 mb-3">
      <p class="text-xs text-fg-muted max-w-2xl inline-flex items-center gap-1.5">
        {{ t('webhooks.subtitle') }}
        <HelpTooltip :text="t('webhooks.help.section')" placement="bottom" />
      </p>
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
      <template #cell-events="{ row }">
        <span class="font-mono text-xs">{{ row.events.join(', ') }}</span>
      </template>
      <template #cell-status="{ row }">
        <span :class="row.enabled ? 'text-success' : 'text-fg-muted'">
          {{ row.enabled ? t('webhooks.status.enabled') : t('webhooks.status.disabled') }}
        </span>
      </template>
      <template #cell-stats="{ row }">
        <div class="flex flex-col">
          <span class="text-fg-muted">
            {{ row.total_deliveries }} / {{ row.total_failures }} {{ t('webhooks.failuresShort') }}
          </span>
          <span v-if="row.last_delivery_at" class="text-fg-muted">
            {{ formatDate(row.last_delivery_at) }}
          </span>
        </div>
      </template>
      <template #cell-actions="{ row }">
        <div class="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('webhooks.viewDeliveries')"
            :title="t('webhooks.viewDeliveries')"
            @click.stop="viewDeliveries(row)"
          >
            <Send class="w-4 h-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('webhooks.sendTest')"
            :title="t('webhooks.sendTest')"
            @click.stop="sendTest(row)"
          >
            <CheckCircle2 class="w-4 h-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('webhooks.rotateSecret')"
            :title="t('webhooks.rotateSecret')"
            @click.stop="rotateSecret(row)"
          >
            <RotateCcw class="w-4 h-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('common.edit')"
            @click.stop="openEdit(row)"
          >
            <Pencil class="w-4 h-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('common.delete')"
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

        <FormField :label="t('webhooks.fields.events')" required>
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
        <p class="text-xs text-fg-muted -mt-2">{{ t('webhooks.eventsHint') }}</p>

        <label class="flex items-center gap-2 text-sm">
          <input v-model="form.enabled" type="checkbox" class="rounded border-border" />
          {{ t('webhooks.fields.enabled') }}
        </label>
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
          <span :class="row.success ? 'text-success' : 'text-danger'">
            {{ row.status_code || '—' }}
          </span>
        </template>
        <template #cell-latency_ms="{ row }">
          <span class="text-fg-muted">{{ row.latency_ms }} ms</span>
        </template>
        <template #cell-error="{ row }">
          <span class="text-fg-muted text-xs truncate block max-w-md">
            {{ row.error || '—' }}
          </span>
        </template>
      </DataTable>
    </Modal>

    <ConfirmDialog
      :open="!!toDelete"
      :title="t('webhooks.confirmDeleteTitle', { name: toDelete?.name ?? '' })"
      :message="t('webhooks.confirmDeleteMessage')"
      variant="danger"
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="toDelete = null"
    />
  </section>
</template>

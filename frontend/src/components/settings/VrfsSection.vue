<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2 } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Modal from '@/components/ui/Modal.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { vrfsApi } from '@/api/endpoints/vrfs'
import type { Vrf } from '@/api/endpoints/vrfs'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { describe } = useApiErrorMessage()

const vrfs = ref<Vrf[]>([])
const loading = ref(false)

const editorOpen = ref(false)
const editing = ref<Vrf | null>(null)
const form = ref({ name: '', rd: '', description: '' })
const saving = ref(false)
const formError = ref<string | null>(null)

const toDelete = ref<Vrf | null>(null)
const deleting = ref(false)

// Wrap in computed so labels follow the i18n locale.
const columns = computed<DataTableColumn[]>(() => [
  { key: 'name', label: t('vrf.fields.name'), cellClass: 'font-medium' },
  { key: 'rd', label: t('vrf.fields.rd'), cellClass: 'font-mono text-xs' },
  { key: 'description', label: t('vrf.fields.description'), hideOnSm: true },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-24' },
])

async function load() {
  loading.value = true
  try {
    vrfs.value = await vrfsApi.list()
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openCreate() {
  editing.value = null
  form.value = { name: '', rd: '', description: '' }
  formError.value = null
  editorOpen.value = true
}

function openEdit(row: Vrf) {
  editing.value = row
  form.value = {
    name: row.name,
    rd: row.rd ?? '',
    description: row.description ?? '',
  }
  formError.value = null
  editorOpen.value = true
}

async function submitForm(e: Event) {
  e.preventDefault()
  if (saving.value) return
  if (!form.value.name.trim()) {
    formError.value = t('common.validation.required')
    return
  }
  saving.value = true
  formError.value = null
  const body = {
    name: form.value.name.trim(),
    rd: form.value.rd.trim() || null,
    description: form.value.description.trim() || null,
  }
  try {
    if (editing.value) {
      await vrfsApi.update(editing.value.id, body)
    } else {
      await vrfsApi.create(body)
    }
    success(t('common.success'))
    editorOpen.value = false
    await load()
  } catch (err) {
    formError.value = describe(err)
  } finally {
    saving.value = false
  }
}

async function confirmDelete() {
  if (!toDelete.value) return
  deleting.value = true
  try {
    await vrfsApi.delete(toDelete.value.id)
    success(t('common.success'))
    toDelete.value = null
    await load()
  } catch (err) {
    toastError(describe(err))
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <section>
    <div class="nf-toolbar items-start justify-between">
      <div class="min-w-0">
        <h2 class="nf-section-title">{{ t('vrf.labelPlural') }}</h2>
        <p class="text-sm text-fg-muted mt-1 max-w-2xl inline-flex items-start gap-1.5">
          <span>{{ t('vrf.subtitle') }}</span>
          <HelpTooltip :text="t('vrf.help.section')" placement="bottom" />
        </p>
      </div>
      <Button variant="primary" @click="openCreate">
        <Plus class="w-4 h-4" aria-hidden="true" />
        {{ t('vrf.new') }}
      </Button>
    </div>

    <DataTable
      :columns="columns"
      :rows="vrfs"
      :loading="loading"
      :empty-title="t('vrf.empty.title')"
      :empty-description="t('vrf.empty.description')"
    >
      <template #empty-action>
        <Button variant="primary" @click="openCreate">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('vrf.new') }}
        </Button>
      </template>
      <template #cell-rd="{ row }">
        <span class="text-fg-muted">{{ row.rd || '—' }}</span>
      </template>
      <template #cell-description="{ row }">
        <span class="text-fg-muted">{{ row.description || '—' }}</span>
      </template>
      <template #cell-actions="{ row }">
        <div class="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            :aria-label="`${t('common.edit')} ${row.name}`"
            :title="t('common.edit')"
            @click.stop="openEdit(row)"
          >
            <Pencil class="w-4 h-4" aria-hidden="true" />
          </Button>
          <!-- Hairline before the destructive action so it is never the button
               you hit by momentum after Edit. -->
          <span class="w-px h-5 bg-border" aria-hidden="true" />
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

    <Modal
      :open="editorOpen"
      :title="editing ? t('vrf.edit') : t('vrf.new')"
      size="md"
      @close="editorOpen = false"
    >
      <form class="flex flex-col gap-4" @submit="submitForm">
        <FormField :label="t('vrf.fields.name')" :error="formError" required>
          <template #default="{ id, invalid }">
            <Input
              :id="id"
              v-model="form.name"
              :invalid="invalid"
              maxlength="64"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('vrf.fields.rd')" :hint="t('vrf.rdHint')">
          <template #help>
            <HelpTooltip :text="t('vrf.help.rd')" />
          </template>
          <template #default="{ id }">
            <Input
              :id="id"
              v-model="form.rd"
              maxlength="32"
              placeholder="65000:42"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('vrf.fields.description')">
          <template #default="{ id }">
            <Input :id="id" v-model="form.description" autocomplete="off" />
          </template>
        </FormField>
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

    <ConfirmDialog
      :open="!!toDelete"
      :title="t('vrf.confirmDeleteTitle', { name: toDelete?.name ?? '' })"
      :message="t('vrf.confirmDeleteMessage')"
      :confirm-label="t('common.delete')"
      variant="danger"
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="toDelete = null"
    />
  </section>
</template>

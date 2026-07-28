<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import FormPage from '@/components/FormPage.vue'
import FormSection from '@/components/FormSection.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { devicesApi, fetchAllPages, roomsApi } from '@/api'
import type { DeviceCreate, DeviceType, DeviceUpdate, Room } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { describe, notify } = useApiErrorMessage()
const { success } = useToast()

// `/devices/new` has no id param; `/devices/:id/edit` does. One component
// serves both so the two forms can never drift apart.
const id = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => id.value !== null)

const DEVICE_TYPES: DeviceType[] = [
  'server',
  'desktop',
  'laptop',
  'printer',
  'phone',
  'ap',
  'camera',
  'ups',
  'other',
]

interface Form {
  name: string
  type: DeviceType
  vendor: string
  model: string
  serial: string
  room_id: number | null
  asset_tag: string
  warranty_expires_at: string
  eol_date: string
  description: string
}

const form = reactive<Form>({
  name: '',
  type: 'server',
  vendor: '',
  model: '',
  serial: '',
  room_id: null,
  asset_tag: '',
  warranty_expires_at: '',
  eol_date: '',
  description: '',
})
const errors = reactive<Partial<Record<keyof Form, string | null>>>({})
const submitError = ref<string | null>(null)
const saving = ref(false)
const loading = ref(false)
const rooms = ref<Room[]>([])

onMounted(async () => {
  // Rooms populate the location select in both modes; they are not part of
  // the entity load, so a slow /rooms never blocks the create form.
  fetchAllPages((p) => roomsApi.list(p)).then((r) => (rooms.value = r))
  if (!isEdit.value) return
  loading.value = true
  try {
    const d = await devicesApi.get(id.value!)
    form.name = d.name
    form.type = d.type
    form.vendor = d.vendor ?? ''
    form.model = d.model ?? ''
    form.serial = d.serial ?? ''
    form.room_id = d.room_id ?? null
    form.asset_tag = d.asset_tag ?? ''
    form.warranty_expires_at = d.warranty_expires_at ?? ''
    form.eol_date = d.eol_date ?? ''
    form.description = d.description ?? ''
  } catch (err) {
    notify(err)
    router.replace({ name: 'devices' })
  } finally {
    loading.value = false
  }
})

const typeOptions = computed(() =>
  DEVICE_TYPES.map((tp) => ({ value: tp, label: t(`device.types.${tp}`) })),
)
const roomOptions = computed(() => [
  { value: 0, label: t('common.none') },
  ...rooms.value.map((r) => ({ value: r.id, label: r.code })),
])

function validate(): boolean {
  errors.name = null
  if (!form.name.trim()) {
    errors.name = t('common.validation.required')
    return false
  }
  return true
}

function goBack() {
  router.push({ name: 'devices' })
}

async function onSubmit() {
  if (saving.value || !validate()) return
  saving.value = true
  submitError.value = null
  try {
    const payload = {
      name: form.name.trim(),
      type: form.type,
      vendor: form.vendor.trim() || null,
      model: form.model.trim() || null,
      serial: form.serial.trim() || null,
      room_id: form.room_id && form.room_id !== 0 ? form.room_id : null,
      asset_tag: form.asset_tag.trim() || null,
      warranty_expires_at: form.warranty_expires_at || null,
      eol_date: form.eol_date || null,
      description: form.description.trim() || null,
    }
    if (isEdit.value) {
      const update: DeviceUpdate = payload
      await devicesApi.update(id.value!, update)
    } else {
      const create: DeviceCreate = payload
      await devicesApi.create(create)
    }
    success(t('common.success'))
    goBack()
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    saving.value = false
  }
}

const breadcrumb = computed(() => [
  { label: t('device.labelPlural'), to: { name: 'devices' } },
  { label: isEdit.value ? t('device.edit') : t('device.new') },
])
</script>

<template>
  <FormPage
    :title="isEdit ? t('device.edit') : t('device.new')"
    :subtitle="t('device.formSubtitle')"
    :breadcrumb="breadcrumb"
    :error="submitError"
    :saving="saving"
    @submit="onSubmit"
    @cancel="goBack"
  >
    <FormSection
      :title="t('device.section.identity')"
      :description="t('device.section.identityHelp')"
    >
      <template v-if="loading">
        <Skeleton class="sm:col-span-2 lg:col-span-3" width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField
          class="sm:col-span-2 lg:col-span-3"
          :label="t('device.fields.name')"
          :error="errors.name"
          required
        >
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
              v-model="form.name"
              :invalid="invalid"
              placeholder="srv-app-01"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('device.fields.type')" required>
          <template #help>
            <HelpTooltip :text="t('device.help.type')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.type"
              :options="typeOptions"
              @update:model-value="(v) => (form.type = v as DeviceType)"
            />
          </template>
        </FormField>
        <FormField :label="t('device.fields.room')">
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.room_id ?? 0"
              :options="roomOptions"
              @update:model-value="(v) => (form.room_id = v === 0 ? null : Number(v))"
            />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('device.section.hardware')"
      :description="t('device.section.hardwareHelp')"
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('device.fields.vendor')">
          <template #default="{ id: fieldId }">
            <Input :id="fieldId" v-model="form.vendor" autocomplete="off" />
          </template>
        </FormField>
        <FormField :label="t('device.fields.model')">
          <template #default="{ id: fieldId }">
            <Input :id="fieldId" v-model="form.model" autocomplete="off" />
          </template>
        </FormField>

        <!-- Serial / asset tag are code-like values: mono face so a zero can
             never be read as an O. -->
        <FormField :label="t('device.fields.serial')">
          <template #default="{ id: fieldId }">
            <Input :id="fieldId" v-model="form.serial" class="font-mono" autocomplete="off" />
          </template>
        </FormField>
        <FormField :label="t('device.fields.assetTag')">
          <template #help>
            <HelpTooltip :text="t('device.help.assetTag')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input
              :id="fieldId"
              v-model="form.asset_tag"
              placeholder="NF-001234"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('device.section.lifecycle')"
      :description="t('device.section.lifecycleHelp')"
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('device.fields.warrantyExpiresAt')">
          <template #help>
            <HelpTooltip :text="t('device.help.warranty')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input
              :id="fieldId"
              v-model="form.warranty_expires_at"
              type="date"
              autocomplete="off"
            />
          </template>
        </FormField>
        <FormField :label="t('device.fields.eolDate')" :hint="t('device.eolHint')">
          <template #help>
            <HelpTooltip :text="t('device.help.eol')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input :id="fieldId" v-model="form.eol_date" type="date" autocomplete="off" />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('device.section.notes')"
      :description="t('device.section.notesHelp')"
      single
    >
      <Skeleton v-if="loading" width="100%" height="4rem" rounded="md" />
      <FormField v-else :label="t('device.fields.description')">
        <template #default="{ id: fieldId }">
          <Textarea :id="fieldId" v-model="form.description" :rows="3" />
        </template>
      </FormField>
    </FormSection>
  </FormPage>
</template>

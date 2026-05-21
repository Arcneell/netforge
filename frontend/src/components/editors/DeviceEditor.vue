<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import { devicesApi, roomsApi } from '@/api'
import type { Device, DeviceCreate, DeviceType, DeviceUpdate, Room } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const props = defineProps<{
  open: boolean
  device?: Device | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', device: Device): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

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
const rooms = ref<Room[]>([])

const isEdit = computed(() => !!props.device)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    const d = props.device
    form.name = d?.name ?? ''
    form.type = d?.type ?? 'server'
    form.vendor = d?.vendor ?? ''
    form.model = d?.model ?? ''
    form.serial = d?.serial ?? ''
    form.room_id = d?.room_id ?? null
    form.asset_tag = d?.asset_tag ?? ''
    form.warranty_expires_at = d?.warranty_expires_at ?? ''
    form.eol_date = d?.eol_date ?? ''
    form.description = d?.description ?? ''
    Object.keys(errors).forEach((k) => ((errors as Record<string, string | null>)[k] = null))
    submitError.value = null
    const r = await roomsApi.list({ page_size: 200 })
    rooms.value = r.items
  },
)

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

async function onSubmit(e: Event) {
  e.preventDefault()
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
    let saved: Device
    if (props.device) {
      const update: DeviceUpdate = payload
      saved = await devicesApi.update(props.device.id, update)
    } else {
      const create: DeviceCreate = payload
      saved = await devicesApi.create(create)
    }
    emit('saved', saved)
    emit('close')
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Modal
    :open="open"
    :title="isEdit ? t('device.edit') : t('device.new')"
    size="md"
    @close="emit('close')"
  >
    <form class="grid grid-cols-2 gap-4" @submit="onSubmit">
      <FormField class="col-span-2" :label="t('device.fields.name')" :error="errors.name" required>
        <template #default="{ id, invalid }">
          <Input :id="id" v-model="form.name" :invalid="invalid" autocomplete="off" />
        </template>
      </FormField>

      <FormField :label="t('device.fields.type')" required>
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.type"
            :options="typeOptions"
            @update:model-value="(v) => (form.type = v as DeviceType)"
          />
        </template>
      </FormField>
      <FormField :label="t('device.fields.room')">
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.room_id ?? 0"
            :options="roomOptions"
            @update:model-value="(v) => (form.room_id = v === 0 ? null : Number(v))"
          />
        </template>
      </FormField>

      <FormField :label="t('device.fields.vendor')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.vendor" autocomplete="off" />
        </template>
      </FormField>
      <FormField :label="t('device.fields.model')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.model" autocomplete="off" />
        </template>
      </FormField>

      <FormField :label="t('device.fields.serial')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.serial" autocomplete="off" />
        </template>
      </FormField>
      <FormField :label="t('device.fields.assetTag')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.asset_tag" placeholder="NF-001234" autocomplete="off" />
        </template>
      </FormField>

      <FormField :label="t('device.fields.warrantyExpiresAt')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.warranty_expires_at" type="date" autocomplete="off" />
        </template>
      </FormField>
      <FormField :label="t('device.fields.eolDate')" :hint="t('device.eolHint')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.eol_date" type="date" autocomplete="off" />
        </template>
      </FormField>

      <FormField class="col-span-2" :label="t('device.fields.description')">
        <template #default="{ id }">
          <Textarea :id="id" v-model="form.description" :rows="2" />
        </template>
      </FormField>

      <p v-if="submitError" class="col-span-2 text-sm text-danger" role="alert">
        {{ submitError }}
      </p>
    </form>

    <template #footer>
      <div class="flex justify-end gap-2">
        <Button variant="secondary" :disabled="saving" @click="emit('close')">
          {{ t('common.cancel') }}
        </Button>
        <Button variant="primary" :loading="saving" @click="onSubmit">
          {{ t('common.save') }}
        </Button>
      </div>
    </template>
  </Modal>
</template>

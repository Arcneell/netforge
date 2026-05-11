<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import { devicesApi, ipsApi } from '@/api'
import type { Device, Ip, IpCreate, IpStatus, IpUpdate, Subnet } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { isValidMac, normalizeMac } from '@/utils/mac'

const props = defineProps<{
  open: boolean
  subnet: Subnet
  /** When set, the IP is updated; otherwise created at `prefilledAddress`. */
  ip?: Ip | null
  /** Used to pre-fill the address field on create (e.g. clicked free cell). */
  prefilledAddress?: string | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', ip: Ip): void
  (e: 'deleted', id: number): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

interface Form {
  address: string
  hostname: string
  mac: string
  device_id: number | null
  status: IpStatus
  description: string
}

const form = reactive<Form>({
  address: '',
  hostname: '',
  mac: '',
  device_id: null,
  status: 'reserved',
  description: '',
})
const errors = reactive<Partial<Record<keyof Form, string | null>>>({})
const submitError = ref<string | null>(null)
const saving = ref(false)
const deleting = ref(false)
const devices = ref<Device[]>([])

const isEdit = computed(() => !!props.ip)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    form.address = props.ip?.address ?? props.prefilledAddress ?? ''
    form.hostname = props.ip?.hostname ?? ''
    form.mac = props.ip?.mac ?? ''
    form.device_id = props.ip?.device_id ?? null
    form.status = props.ip?.status ?? 'reserved'
    form.description = props.ip?.description ?? ''
    Object.keys(errors).forEach((k) => ((errors as Record<string, string | null>)[k] = null))
    submitError.value = null
    // Devices list keeps things tight; v1 doesn't need autocomplete on large fleets.
    const res = await devicesApi.list({ page_size: 200 })
    devices.value = res.items
  },
)

const statusOptions = computed(() => [
  { value: 'reserved', label: t('ip.status.reserved') },
  { value: 'assigned', label: t('ip.status.assigned') },
  { value: 'dhcp', label: t('ip.status.dhcp') },
])

const deviceOptions = computed(() => [
  { value: 0, label: t('common.none') },
  ...devices.value.map((d) => ({ value: d.id, label: d.name })),
])

function validate(): boolean {
  let ok = true
  errors.address = errors.mac = null
  if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(form.address.trim())) {
    errors.address = t('common.validation.invalidIp')
    ok = false
  }
  if (form.mac) {
    const m = normalizeMac(form.mac)
    if (!isValidMac(m)) {
      errors.mac = t('common.validation.invalidMac')
      ok = false
    } else {
      form.mac = m
    }
  }
  return ok
}

async function onSubmit(e: Event) {
  e.preventDefault()
  if (saving.value || !validate()) return
  saving.value = true
  submitError.value = null
  try {
    const base = {
      subnet_id: props.subnet.id,
      address: form.address.trim(),
      hostname: form.hostname.trim() || null,
      mac: form.mac.trim() || null,
      device_id: form.device_id && form.device_id !== 0 ? form.device_id : null,
      status: form.status,
      description: form.description.trim() || null,
    }
    let saved: Ip
    if (props.ip) {
      const update: IpUpdate = base
      saved = await ipsApi.update(props.ip.id, update)
    } else {
      const create: IpCreate = base
      saved = await ipsApi.create(create)
    }
    emit('saved', saved)
    emit('close')
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    saving.value = false
  }
}

async function onDelete() {
  if (!props.ip || deleting.value) return
  deleting.value = true
  try {
    await ipsApi.delete(props.ip.id)
    emit('deleted', props.ip.id)
    emit('close')
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <Modal :open="open" :title="isEdit ? t('ip.edit') : t('ip.new')" size="md" @close="emit('close')">
    <form class="grid grid-cols-2 gap-4" @submit="onSubmit">
      <FormField :label="t('ip.fields.address')" :error="errors.address" required>
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.address"
            :invalid="invalid"
            placeholder="10.0.30.42"
            class="font-mono"
            autocomplete="off"
            :readonly="isEdit"
          />
        </template>
      </FormField>

      <FormField :label="t('ip.fields.status')" required>
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.status"
            :options="statusOptions"
            @update:model-value="(v) => (form.status = v as IpStatus)"
          />
        </template>
      </FormField>

      <FormField :label="t('ip.fields.hostname')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.hostname" placeholder="srv-app-01" autocomplete="off" />
        </template>
      </FormField>

      <FormField :label="t('ip.fields.mac')" :error="errors.mac">
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.mac"
            :invalid="invalid"
            placeholder="aa:bb:cc:dd:ee:ff"
            class="font-mono"
            autocomplete="off"
          />
        </template>
      </FormField>

      <FormField class="col-span-2" :label="t('ip.fields.device')">
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.device_id ?? 0"
            :options="deviceOptions"
            @update:model-value="(v) => (form.device_id = v === 0 ? null : Number(v))"
          />
        </template>
      </FormField>

      <FormField class="col-span-2" :label="t('ip.fields.description')">
        <template #default="{ id }">
          <Textarea :id="id" v-model="form.description" :rows="2" />
        </template>
      </FormField>

      <p v-if="submitError" class="col-span-2 text-sm text-danger" role="alert">
        {{ submitError }}
      </p>
    </form>

    <template #footer>
      <div class="flex justify-between items-center gap-2 w-full">
        <Button
          v-if="isEdit"
          variant="danger"
          :loading="deleting"
          :disabled="saving"
          @click="onDelete"
        >
          {{ t('common.delete') }}
        </Button>
        <div class="flex justify-end gap-2 ml-auto">
          <Button variant="secondary" :disabled="saving || deleting" @click="emit('close')">
            {{ t('common.cancel') }}
          </Button>
          <Button variant="primary" :loading="saving" :disabled="deleting" @click="onSubmit">
            {{ t('common.save') }}
          </Button>
        </div>
      </div>
    </template>
  </Modal>
</template>

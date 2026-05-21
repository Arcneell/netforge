<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import { roomsApi, switchesApi } from '@/api'
import type { Room, Switch, SwitchCreate, SwitchUpdate } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const props = defineProps<{
  open: boolean
  switchItem?: Switch | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', sw: Switch): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

interface Form {
  name: string
  vendor: string
  model: string
  serial: string
  management_ip: string
  room_id: number | null
  rack_position: string
  port_count: number
  firmware_version: string
  snmp_community: string
  asset_tag: string
  // ISO date strings (YYYY-MM-DD) — `<input type="date">` exposes them that
  // way and the Pydantic `date` schema accepts the same format directly.
  warranty_expires_at: string
  eol_date: string
  description: string
}

const form = reactive<Form>({
  name: '',
  vendor: '',
  model: '',
  serial: '',
  management_ip: '',
  room_id: null,
  rack_position: '',
  port_count: 48,
  firmware_version: '',
  snmp_community: '',
  asset_tag: '',
  warranty_expires_at: '',
  eol_date: '',
  description: '',
})
const errors = reactive<Partial<Record<keyof Form, string | null>>>({})
const submitError = ref<string | null>(null)
const saving = ref(false)
const rooms = ref<Room[]>([])

const isEdit = computed(() => !!props.switchItem)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    const s = props.switchItem
    form.name = s?.name ?? ''
    form.vendor = s?.vendor ?? ''
    form.model = s?.model ?? ''
    form.serial = s?.serial ?? ''
    form.management_ip = s?.management_ip ?? ''
    form.room_id = s?.room_id ?? null
    form.rack_position = s?.rack_position ?? ''
    form.port_count = s?.port_count ?? 48
    form.firmware_version = s?.firmware_version ?? ''
    form.snmp_community = s?.snmp_community ?? ''
    form.asset_tag = s?.asset_tag ?? ''
    form.warranty_expires_at = s?.warranty_expires_at ?? ''
    form.eol_date = s?.eol_date ?? ''
    form.description = s?.description ?? ''
    Object.keys(errors).forEach((k) => ((errors as Record<string, string | null>)[k] = null))
    submitError.value = null
    const r = await roomsApi.list({ page_size: 200 })
    rooms.value = r.items
  },
)

const roomOptions = computed(() => [
  { value: 0, label: t('common.none') },
  ...rooms.value.map((r) => ({ value: r.id, label: r.code })),
])

function validate(): boolean {
  let ok = true
  errors.name = errors.port_count = errors.management_ip = null
  if (!form.name.trim()) {
    errors.name = t('common.validation.required')
    ok = false
  }
  if (
    !isEdit.value &&
    (!Number.isInteger(form.port_count) || form.port_count < 1 || form.port_count > 1024)
  ) {
    errors.port_count = t('common.validation.required')
    ok = false
  }
  if (form.management_ip && !/^\d{1,3}(\.\d{1,3}){3}$/.test(form.management_ip.trim())) {
    errors.management_ip = t('common.validation.invalidIp')
    ok = false
  }
  return ok
}

async function onSubmit(e: Event) {
  e.preventDefault()
  if (saving.value || !validate()) return
  saving.value = true
  submitError.value = null
  try {
    const common = {
      name: form.name.trim(),
      vendor: form.vendor.trim() || null,
      model: form.model.trim() || null,
      serial: form.serial.trim() || null,
      management_ip: form.management_ip.trim() || null,
      room_id: form.room_id && form.room_id !== 0 ? form.room_id : null,
      rack_position: form.rack_position.trim() || null,
      firmware_version: form.firmware_version.trim() || null,
      snmp_community: form.snmp_community.trim() || null,
      asset_tag: form.asset_tag.trim() || null,
      warranty_expires_at: form.warranty_expires_at || null,
      eol_date: form.eol_date || null,
      description: form.description.trim() || null,
    }
    let saved: Switch
    if (props.switchItem) {
      // port_count is intentionally not part of SwitchUpdate.
      const update: SwitchUpdate = common
      saved = await switchesApi.update(props.switchItem.id, update)
    } else {
      const create: SwitchCreate = { ...common, port_count: form.port_count }
      saved = await switchesApi.create(create)
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
    :title="isEdit ? t('switch.edit') : t('switch.new')"
    size="lg"
    @close="emit('close')"
  >
    <form class="grid grid-cols-2 gap-4" @submit="onSubmit">
      <FormField :label="t('switch.fields.name')" :error="errors.name" required>
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.name"
            :invalid="invalid"
            placeholder="sw-core-01"
            autocomplete="off"
          />
        </template>
      </FormField>

      <FormField :label="t('switch.fields.managementIp')" :error="errors.management_ip">
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.management_ip"
            :invalid="invalid"
            placeholder="10.0.0.10"
            class="font-mono"
            autocomplete="off"
          />
        </template>
      </FormField>

      <FormField :label="t('switch.fields.vendor')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.vendor" placeholder="Cisco" autocomplete="off" />
        </template>
      </FormField>
      <FormField :label="t('switch.fields.model')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.model" placeholder="C9300-48P" autocomplete="off" />
        </template>
      </FormField>

      <FormField :label="t('switch.fields.serial')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.serial" autocomplete="off" />
        </template>
      </FormField>
      <FormField :label="t('switch.fields.firmware')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.firmware_version" autocomplete="off" />
        </template>
      </FormField>

      <FormField :label="t('switch.fields.room')">
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.room_id ?? 0"
            :options="roomOptions"
            @update:model-value="(v) => (form.room_id = v === 0 ? null : Number(v))"
          />
        </template>
      </FormField>
      <FormField :label="t('switch.fields.rackPosition')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.rack_position" placeholder="U22" autocomplete="off" />
        </template>
      </FormField>

      <FormField
        :label="t('switch.fields.portCount')"
        :error="errors.port_count"
        :hint="isEdit ? t('switch.portCountImmutable') : undefined"
        required
      >
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model.number="form.port_count"
            type="number"
            min="1"
            max="1024"
            :invalid="invalid"
            :readonly="isEdit"
            autocomplete="off"
          />
        </template>
      </FormField>

      <FormField :label="t('switch.fields.snmpCommunity')" :hint="t('switch.snmpCommunityHint')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.snmp_community" type="password" autocomplete="off" />
        </template>
      </FormField>

      <FormField :label="t('switch.fields.assetTag')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.asset_tag" placeholder="NF-001234" autocomplete="off" />
        </template>
      </FormField>
      <FormField :label="t('switch.fields.warrantyExpiresAt')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.warranty_expires_at" type="date" autocomplete="off" />
        </template>
      </FormField>
      <FormField :label="t('switch.fields.eolDate')" :hint="t('switch.eolHint')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.eol_date" type="date" autocomplete="off" />
        </template>
      </FormField>

      <FormField class="col-span-2" :label="t('switch.fields.description')">
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

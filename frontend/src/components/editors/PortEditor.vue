<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import { devicesApi, portsApi, vlansApi } from '@/api'
import type { Device, Port, PortAdminStatus, PortMode, PortUpdate, Vlan } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const props = defineProps<{
  open: boolean
  port: Port | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', port: Port): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

interface Form {
  label: string
  mode: PortMode
  native_vlan_id: number | null
  admin_status: PortAdminStatus
  connected_device_id: number | null
  notes: string
}

const form = reactive<Form>({
  label: '',
  mode: 'access',
  native_vlan_id: null,
  admin_status: 'up',
  connected_device_id: null,
  notes: '',
})
const submitError = ref<string | null>(null)
const saving = ref(false)
const vlanLoading = ref(false)
const taggedVlanIds = ref<number[]>([])
const newTaggedVlan = ref<number | null>(null)

const vlans = ref<Vlan[]>([])
const vlansById = computed(() => new Map(vlans.value.map((v) => [v.id, v])))
const devices = ref<Device[]>([])

watch(
  () => props.open,
  async (open) => {
    if (!open || !props.port) return
    const p = props.port
    form.label = p.label ?? ''
    form.mode = p.mode
    form.native_vlan_id = p.native_vlan_id ?? null
    form.admin_status = p.admin_status
    form.connected_device_id = p.connected_device_id ?? null
    form.notes = p.notes ?? ''
    submitError.value = null
    // PortRead does not expose the tagged-VLAN list directly — backend exposes it
    // separately via the port-vlan join. For v1 we keep a local list that admins
    // mutate through dedicated add/remove endpoints; on open we reset to empty
    // because there's no batch read endpoint. (Phase 7 follow-up: add it server-side.)
    taggedVlanIds.value = []
    const [v, d] = await Promise.all([
      vlansApi.list({ page_size: 200 }),
      devicesApi.list({ page_size: 200 }),
    ])
    vlans.value = v.items
    devices.value = d.items
  },
)

const modeOptions = computed(() => [
  { value: 'access', label: t('port.modes.access') },
  { value: 'trunk', label: t('port.modes.trunk') },
  { value: 'hybrid', label: t('port.modes.hybrid') },
  { value: 'disabled', label: t('port.modes.disabled') },
])

const adminStatusOptions = computed(() => [
  { value: 'up', label: t('port.adminStatus.up') },
  { value: 'down', label: t('port.adminStatus.down') },
])

const vlanOptions = computed(() => [
  { value: 0, label: t('common.none') },
  ...vlans.value.map((v) => ({ value: v.id, label: `${v.vlan_id} — ${v.name}` })),
])

const taggedAddOptions = computed(() => [
  { value: 0, label: '—' },
  ...vlans.value
    .filter((v) => !taggedVlanIds.value.includes(v.id) && v.id !== form.native_vlan_id)
    .map((v) => ({ value: v.id, label: `${v.vlan_id} — ${v.name}` })),
])

async function onSubmit(e: Event) {
  e.preventDefault()
  if (!props.port || saving.value) return
  saving.value = true
  submitError.value = null
  try {
    const payload: PortUpdate = {
      label: form.label.trim() || null,
      mode: form.mode,
      native_vlan_id: form.native_vlan_id && form.native_vlan_id !== 0 ? form.native_vlan_id : null,
      admin_status: form.admin_status,
      connected_device_id:
        form.connected_device_id && form.connected_device_id !== 0
          ? form.connected_device_id
          : null,
      notes: form.notes.trim() || null,
    }
    const saved = await portsApi.update(props.port.id, payload)
    emit('saved', saved)
    emit('close')
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    saving.value = false
  }
}

async function addTagged() {
  if (!props.port || !newTaggedVlan.value || newTaggedVlan.value === 0) return
  vlanLoading.value = true
  try {
    await portsApi.addTaggedVlan(props.port.id, newTaggedVlan.value)
    taggedVlanIds.value = [...taggedVlanIds.value, newTaggedVlan.value]
    newTaggedVlan.value = null
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    vlanLoading.value = false
  }
}

async function removeTagged(vlanId: number) {
  if (!props.port) return
  vlanLoading.value = true
  try {
    await portsApi.removeTaggedVlan(props.port.id, vlanId)
    taggedVlanIds.value = taggedVlanIds.value.filter((id) => id !== vlanId)
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    vlanLoading.value = false
  }
}
</script>

<template>
  <Modal
    :open="open"
    :title="port ? `${t('port.edit')} #${port.number}` : t('port.edit')"
    size="lg"
    @close="emit('close')"
  >
    <form class="grid grid-cols-2 gap-4" @submit="onSubmit">
      <FormField :label="t('port.fields.label')">
        <template #default="{ id }">
          <Input :id="id" v-model="form.label" placeholder="uplink-core-01" autocomplete="off" />
        </template>
      </FormField>

      <FormField :label="t('port.fields.mode')">
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.mode"
            :options="modeOptions"
            @update:model-value="(v) => (form.mode = v as PortMode)"
          />
        </template>
      </FormField>

      <FormField :label="t('port.fields.nativeVlan')">
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.native_vlan_id ?? 0"
            :options="vlanOptions"
            @update:model-value="(v) => (form.native_vlan_id = v === 0 ? null : Number(v))"
          />
        </template>
      </FormField>

      <FormField :label="t('port.fields.adminStatus')">
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.admin_status"
            :options="adminStatusOptions"
            @update:model-value="(v) => (form.admin_status = v as PortAdminStatus)"
          />
        </template>
      </FormField>

      <FormField class="col-span-2" :label="t('port.fields.connectedDevice')">
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.connected_device_id ?? 0"
            :options="[
              { value: 0, label: t('common.none') },
              ...devices.map((d) => ({ value: d.id, label: d.name })),
            ]"
            @update:model-value="(v) => (form.connected_device_id = v === 0 ? null : Number(v))"
          />
        </template>
      </FormField>

      <FormField class="col-span-2" :label="t('port.fields.notes')">
        <template #default="{ id }">
          <Textarea :id="id" v-model="form.notes" :rows="2" />
        </template>
      </FormField>

      <!-- Tagged VLANs editor (separate from the main form save — uses dedicated endpoints) -->
      <div class="col-span-2 mt-2 border-t border-border pt-4">
        <p class="text-xs font-medium text-fg-muted uppercase tracking-wide mb-2">
          {{ t('port.fields.taggedVlans') }}
        </p>
        <div class="flex flex-wrap gap-2 mb-3 min-h-[1.5rem]">
          <span
            v-for="vlanId in taggedVlanIds"
            :key="vlanId"
            class="inline-flex items-center gap-1"
          >
            <VlanBadge v-if="vlansById.get(vlanId)" :vlan="vlansById.get(vlanId)!" />
            <button
              type="button"
              class="text-fg-muted hover:text-danger transition"
              :aria-label="t('common.remove')"
              :disabled="vlanLoading"
              @click="removeTagged(vlanId)"
            >
              <X class="w-3 h-3" aria-hidden="true" />
            </button>
          </span>
          <span v-if="taggedVlanIds.length === 0" class="text-xs text-fg-muted">
            {{ t('port.noTaggedVlans') }}
          </span>
        </div>
        <div class="flex items-end gap-2">
          <div class="flex-1">
            <Select
              :model-value="newTaggedVlan ?? 0"
              :options="taggedAddOptions"
              :aria-label="t('port.addTaggedVlan')"
              @update:model-value="(v) => (newTaggedVlan = v === 0 ? null : Number(v))"
            />
          </div>
          <Button
            variant="secondary"
            size="md"
            :disabled="!newTaggedVlan || vlanLoading"
            :loading="vlanLoading"
            @click="addTagged"
          >
            {{ t('common.add') }}
          </Button>
        </div>
      </div>

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

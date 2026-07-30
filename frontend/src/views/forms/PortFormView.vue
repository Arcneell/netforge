<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { X } from '@lucide/vue'
import FormPage from '@/components/FormPage.vue'
import FormSection from '@/components/FormSection.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import { devicesApi, fetchAllPages, portsApi, switchesApi, vlansApi } from '@/api'
import type { Device, Port, PortAdminStatus, PortMode, PortUpdate, Vlan } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { describe, notify } = useApiErrorMessage()
const { success } = useToast()

// A port always belongs to a switch: `/switches/:switchId/ports/:id/edit`.
// Ports are created with their switch, so this page is edit-only.
const id = computed(() => Number(route.params.id))
const switchId = computed(() => Number(route.params.switchId))

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
const port = ref<Port | null>(null)
const switchName = ref('')
const submitError = ref<string | null>(null)
const saving = ref(false)
const loading = ref(true)
const vlanLoading = ref(false)
const taggedVlanIds = ref<number[]>([])
const newTaggedVlan = ref<number | null>(null)

const vlans = ref<Vlan[]>([])
const vlansById = computed(() => new Map(vlans.value.map((v) => [v.id, v])))
const devices = ref<Device[]>([])

onMounted(async () => {
  loading.value = true
  try {
    const [p, v, d, tagged, sw] = await Promise.all([
      portsApi.get(id.value),
      fetchAllPages((p) => vlansApi.list(p)),
      fetchAllPages((p) => devicesApi.list(p)),
      portsApi.listTaggedVlans(id.value),
      switchesApi.get(switchId.value),
    ])
    port.value = p
    form.label = p.label ?? ''
    form.mode = p.mode
    form.native_vlan_id = p.native_vlan_id ?? null
    form.admin_status = p.admin_status
    form.connected_device_id = p.connected_device_id ?? null
    form.notes = p.notes ?? ''
    vlans.value = v
    devices.value = d
    taggedVlanIds.value = tagged.map((tv) => tv.id)
    switchName.value = sw.name
  } catch (err) {
    notify(err)
    router.replace({ name: 'switch-detail', params: { id: switchId.value } })
  } finally {
    loading.value = false
  }
})

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

function goBack() {
  router.push({ name: 'switch-detail', params: { id: switchId.value } })
}

async function onSubmit() {
  if (!port.value || saving.value) return
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
    await portsApi.update(port.value.id, payload)
    success(t('common.success'))
    goBack()
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    saving.value = false
  }
}

async function addTagged() {
  if (!port.value || !newTaggedVlan.value || newTaggedVlan.value === 0) return
  vlanLoading.value = true
  try {
    await portsApi.addTaggedVlan(port.value.id, newTaggedVlan.value)
    taggedVlanIds.value = [...taggedVlanIds.value, newTaggedVlan.value]
    newTaggedVlan.value = null
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    vlanLoading.value = false
  }
}

async function removeTagged(vlanId: number) {
  if (!port.value) return
  vlanLoading.value = true
  try {
    await portsApi.removeTaggedVlan(port.value.id, vlanId)
    taggedVlanIds.value = taggedVlanIds.value.filter((vid) => vid !== vlanId)
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    vlanLoading.value = false
  }
}

const title = computed(() =>
  port.value ? `${t('port.edit')} #${port.value.number}` : t('port.edit'),
)

const breadcrumb = computed(() => [
  { label: t('switch.labelPlural'), to: { name: 'switches' } },
  {
    label: switchName.value || t('switch.label'),
    to: { name: 'switch-detail', params: { id: switchId.value } },
  },
  { label: title.value },
])
</script>

<template>
  <FormPage
    :title="title"
    :subtitle="t('port.formSubtitle')"
    :breadcrumb="breadcrumb"
    :error="submitError"
    :saving="saving"
    @submit="onSubmit"
    @cancel="goBack"
  >
    <FormSection :title="t('port.section.config')" :description="t('port.section.configHelp')">
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('port.fields.label')">
          <template #help>
            <HelpTooltip :text="t('port.help.label')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input
              :id="fieldId"
              v-model="form.label"
              placeholder="uplink-core-01"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('port.fields.mode')">
          <template #help>
            <HelpTooltip :text="t('port.help.mode')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.mode"
              :options="modeOptions"
              @update:model-value="(v) => (form.mode = v as PortMode)"
            />
          </template>
        </FormField>

        <FormField :label="t('port.fields.nativeVlan')">
          <template #help>
            <HelpTooltip :text="t('port.help.nativeVlan')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.native_vlan_id ?? 0"
              :options="vlanOptions"
              @update:model-value="(v) => (form.native_vlan_id = v === 0 ? null : Number(v))"
            />
          </template>
        </FormField>

        <FormField :label="t('port.fields.adminStatus')">
          <template #help>
            <HelpTooltip :text="t('port.help.adminStatus')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.admin_status"
              :options="adminStatusOptions"
              @update:model-value="(v) => (form.admin_status = v as PortAdminStatus)"
            />
          </template>
        </FormField>
      </template>
    </FormSection>

    <!-- Tagged VLANs are saved through their own endpoints, not by the Save
         button below — each add/remove hits the server immediately. Their own
         panel makes that separation legible instead of hiding it inside the
         main form. -->
    <FormSection
      :title="t('port.fields.taggedVlans')"
      :description="t('port.section.taggedHelp')"
      single
    >
      <template #header-aside>
        <HelpTooltip :text="t('port.help.taggedVlans')" />
      </template>
      <Skeleton v-if="loading" width="100%" height="4rem" rounded="md" />
      <template v-else>
        <div class="flex flex-wrap items-center gap-1.5 min-h-[1.5rem]">
          <span
            v-for="vlanId in taggedVlanIds"
            :key="vlanId"
            class="inline-flex items-center gap-1 rounded-md border border-border bg-surface pl-1 pr-0.5 py-0.5"
          >
            <VlanBadge v-if="vlansById.get(vlanId)" :vlan="vlansById.get(vlanId)!" />
            <button
              type="button"
              class="inline-flex items-center justify-center w-5 h-5 rounded text-fg-subtle hover:text-danger hover:bg-danger/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-150 ease-soft"
              :aria-label="t('common.remove')"
              :disabled="vlanLoading"
              @click="removeTagged(vlanId)"
            >
              <X class="w-3 h-3" aria-hidden="true" />
            </button>
          </span>
          <span v-if="taggedVlanIds.length === 0" class="text-sm text-fg-subtle">
            {{ t('port.noTaggedVlans') }}
          </span>
        </div>
        <div class="flex items-center gap-2">
          <div class="flex-1 min-w-0">
            <Select
              :model-value="newTaggedVlan ?? 0"
              :options="taggedAddOptions"
              :aria-label="t('port.addTaggedVlan')"
              @update:model-value="(v) => (newTaggedVlan = v === 0 ? null : Number(v))"
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            size="md"
            :disabled="!newTaggedVlan || vlanLoading"
            :loading="vlanLoading"
            @click="addTagged"
          >
            {{ t('common.add') }}
          </Button>
        </div>
      </template>
    </FormSection>

    <FormSection
      :title="t('port.section.connection')"
      :description="t('port.section.connectionHelp')"
      single
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="4rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('port.fields.connectedDevice')">
          <template #help>
            <HelpTooltip :text="t('port.help.connectedDevice')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.connected_device_id ?? 0"
              :options="[
                { value: 0, label: t('common.none') },
                ...devices.map((d) => ({ value: d.id, label: d.name })),
              ]"
              @update:model-value="(v) => (form.connected_device_id = v === 0 ? null : Number(v))"
            />
          </template>
        </FormField>

        <FormField :label="t('port.fields.notes')">
          <template #default="{ id: fieldId }">
            <Textarea :id="fieldId" v-model="form.notes" :rows="3" />
          </template>
        </FormField>
      </template>
    </FormSection>
  </FormPage>
</template>

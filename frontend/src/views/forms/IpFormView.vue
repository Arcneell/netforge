<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import FormPage from '@/components/FormPage.vue'
import FormSection from '@/components/FormSection.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { devicesApi, fetchAllPages, ipsApi, subnetsApi } from '@/api'
import type { Device, Ip, IpCreate, IpStatus, IpUpdate, Subnet } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'
import { isValidMac, normalizeMac } from '@/utils/mac'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { describe, notify } = useApiErrorMessage()
const { success } = useToast()

// An IP always belongs to a subnet, so the two routes differ in what they
// carry: `/subnets/:subnetId/ips/new` names the parent up front, while
// `/ips/:id/edit` gets it from the loaded row. One component serves both so
// the two forms can never drift apart.
const ipId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => ipId.value !== null)
// Set on create by the route, on edit by the row we load.
const subnetId = ref<number | null>(route.params.subnetId ? Number(route.params.subnetId) : null)
// Clicking a free cell in the grid opens this form with the address already
// filled in; it travels as a query param rather than component state.
const prefilledAddress = computed(() =>
  typeof route.query.address === 'string' ? route.query.address : null,
)

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
const loading = ref(true)
const devices = ref<Device[]>([])
const subnet = ref<Subnet | null>(null)
const existing = ref<Ip | null>(null)

onMounted(async () => {
  loading.value = true
  try {
    if (isEdit.value) {
      const ip = await ipsApi.get(ipId.value!)
      existing.value = ip
      subnetId.value = ip.subnet_id
      form.address = ip.address
      form.hostname = ip.hostname ?? ''
      form.mac = ip.mac ?? ''
      form.device_id = ip.device_id ?? null
      form.status = ip.status
      form.description = ip.description ?? ''
    } else {
      form.address = prefilledAddress.value ?? ''
    }
    // The parent subnet is what the breadcrumb and the cancel target hang
    // off; without it there is nowhere sensible to send the user back to.
    subnet.value = await subnetsApi.get(subnetId.value!)
  } catch (err) {
    notify(err)
    router.replace({ name: 'subnets' })
    return
  } finally {
    loading.value = false
  }
  // Full device list — `fetchAllPages` walks past the server's 200-row page
  // cap so large fleets still populate the picker completely.
  devices.value = await fetchAllPages((p) => devicesApi.list(p))
})

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

function goBack() {
  if (subnetId.value != null) {
    router.push({ name: 'subnet-detail', params: { id: subnetId.value } })
  } else {
    router.push({ name: 'subnets' })
  }
}

async function onSubmit() {
  if (saving.value || !validate()) return
  saving.value = true
  submitError.value = null
  try {
    const base = {
      subnet_id: subnetId.value!,
      address: form.address.trim(),
      hostname: form.hostname.trim() || null,
      mac: form.mac.trim() || null,
      device_id: form.device_id && form.device_id !== 0 ? form.device_id : null,
      status: form.status,
      description: form.description.trim() || null,
    }
    if (existing.value) {
      const update: IpUpdate = base
      await ipsApi.update(existing.value.id, update)
    } else {
      const create: IpCreate = base
      await ipsApi.create(create)
    }
    success(t('common.success'))
    goBack()
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    saving.value = false
  }
}

async function onDelete() {
  if (!existing.value || deleting.value) return
  deleting.value = true
  try {
    await ipsApi.delete(existing.value.id)
    success(t('common.success'))
    goBack()
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    deleting.value = false
  }
}

const breadcrumb = computed(() => [
  { label: t('subnet.labelPlural'), to: { name: 'subnets' } },
  ...(subnet.value
    ? [
        {
          label: subnet.value.cidr,
          to: { name: 'subnet-detail', params: { id: subnet.value.id } },
        },
      ]
    : []),
  { label: isEdit.value ? t('ip.edit') : t('ip.new') },
])
</script>

<template>
  <FormPage
    :title="isEdit ? t('ip.edit') : t('ip.new')"
    :subtitle="t('ip.formSubtitle')"
    :breadcrumb="breadcrumb"
    :error="submitError"
    :saving="saving"
    @submit="onSubmit"
    @cancel="goBack"
  >
    <!-- The destructive action sits at the far edge of the action bar so it
         can't be hit by muscle memory reaching for Save. -->
    <template v-if="isEdit" #actions-start>
      <Button
        type="button"
        variant="danger"
        :loading="deleting"
        :disabled="saving"
        @click="onDelete"
      >
        {{ t('common.delete') }}
      </Button>
    </template>

    <FormSection :title="t('ip.section.identity')" :description="t('ip.section.identityHelp')">
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('ip.fields.address')" :error="errors.address" required>
          <template #help>
            <HelpTooltip :text="t('ip.help.address')" />
          </template>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
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
          <template #help>
            <HelpTooltip :text="t('ip.help.status')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.status"
              :options="statusOptions"
              @update:model-value="(v) => (form.status = v as IpStatus)"
            />
          </template>
        </FormField>

        <FormField class="sm:col-span-2 lg:col-span-3" :label="t('ip.fields.description')">
          <template #default="{ id: fieldId }">
            <Textarea :id="fieldId" v-model="form.description" :rows="2" />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('ip.section.attribution')"
      :description="t('ip.section.attributionHelp')"
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('ip.fields.hostname')">
          <template #help>
            <HelpTooltip :text="t('ip.help.hostname')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input
              :id="fieldId"
              v-model="form.hostname"
              placeholder="srv-app-01"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('ip.fields.mac')" :error="errors.mac">
          <template #help>
            <HelpTooltip :text="t('ip.help.mac')" />
          </template>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
              v-model="form.mac"
              :invalid="invalid"
              placeholder="aa:bb:cc:dd:ee:ff"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField class="sm:col-span-2 lg:col-span-3" :label="t('ip.fields.device')">
          <template #help>
            <HelpTooltip :text="t('ip.help.device')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.device_id ?? 0"
              :options="deviceOptions"
              @update:model-value="(v) => (form.device_id = v === 0 ? null : Number(v))"
            />
          </template>
        </FormField>
      </template>
    </FormSection>
  </FormPage>
</template>

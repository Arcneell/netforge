<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import { sitesApi, subnetsApi, vlansApi } from '@/api'
import type { Site, Subnet, SubnetCreate, SubnetUpdate, Vlan } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const props = defineProps<{
  open: boolean
  subnet?: Subnet | null
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', subnet: Subnet): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

interface Form {
  cidr: string
  gateway: string
  vlan_id: number | null
  site_id: number | null
  description: string
  dhcp_enabled: boolean
  dhcp_range_start: string
  dhcp_range_end: string
}

const form = reactive<Form>({
  cidr: '',
  gateway: '',
  vlan_id: null,
  site_id: null,
  description: '',
  dhcp_enabled: false,
  dhcp_range_start: '',
  dhcp_range_end: '',
})
const errors = reactive<Partial<Record<keyof Form, string | null>>>({})
const submitError = ref<string | null>(null)
const saving = ref(false)

const sites = ref<Site[]>([])
const vlans = ref<Vlan[]>([])
const loadingRefs = ref(false)

const isEdit = computed(() => !!props.subnet)

// Pre-load the dropdown sources on first open; sites + vlans are bounded and
// cheap to fetch wholesale (page_size=200 covers any realistic deployment).
async function loadDropdowns() {
  if (loadingRefs.value) return
  loadingRefs.value = true
  try {
    const [s, v] = await Promise.all([
      sitesApi.list({ page_size: 200 }),
      vlansApi.list({ page_size: 200 }),
    ])
    sites.value = s.items
    vlans.value = v.items
  } finally {
    loadingRefs.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    loadDropdowns()
    form.cidr = props.subnet?.cidr ?? ''
    form.gateway = props.subnet?.gateway ?? ''
    form.vlan_id = props.subnet?.vlan_id ?? null
    form.site_id = props.subnet?.site_id ?? null
    form.description = props.subnet?.description ?? ''
    form.dhcp_enabled = props.subnet?.dhcp_enabled ?? false
    form.dhcp_range_start = props.subnet?.dhcp_range_start ?? ''
    form.dhcp_range_end = props.subnet?.dhcp_range_end ?? ''
    Object.keys(errors).forEach((k) => ((errors as Record<string, string | null>)[k] = null))
    submitError.value = null
  },
)

const siteOptions = computed(() =>
  sites.value.map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` })),
)
const vlanOptions = computed(() => [
  { value: 0, label: t('common.none') },
  ...vlans.value.map((v) => ({ value: v.id, label: `${v.vlan_id} — ${v.name}` })),
])

function validate(): boolean {
  let ok = true
  errors.cidr = errors.site_id = errors.gateway = null
  if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(form.cidr.trim())) {
    errors.cidr = t('common.validation.invalidCidr')
    ok = false
  }
  if (form.gateway && !/^\d{1,3}(\.\d{1,3}){3}$/.test(form.gateway.trim())) {
    errors.gateway = t('common.validation.invalidIp')
    ok = false
  }
  if (!form.site_id) {
    errors.site_id = t('common.validation.required')
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
    const payload = {
      cidr: form.cidr.trim(),
      gateway: form.gateway.trim() || null,
      vlan_id: form.vlan_id && form.vlan_id !== 0 ? form.vlan_id : null,
      site_id: form.site_id!,
      description: form.description.trim() || null,
      dhcp_enabled: form.dhcp_enabled,
      dhcp_range_start: form.dhcp_range_start.trim() || null,
      dhcp_range_end: form.dhcp_range_end.trim() || null,
    }
    let saved: Subnet
    if (props.subnet) {
      const update: SubnetUpdate = payload
      saved = await subnetsApi.update(props.subnet.id, update)
    } else {
      const create: SubnetCreate = payload
      saved = await subnetsApi.create(create)
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
    :title="isEdit ? t('subnet.edit') : t('subnet.new')"
    size="lg"
    @close="emit('close')"
  >
    <form class="grid grid-cols-2 gap-4" @submit="onSubmit">
      <FormField :label="t('subnet.fields.cidr')" :error="errors.cidr" required>
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.cidr"
            :invalid="invalid"
            placeholder="10.0.30.0/24"
            class="font-mono"
            autocomplete="off"
            :readonly="isEdit"
          />
        </template>
      </FormField>

      <FormField :label="t('subnet.fields.gateway')" :error="errors.gateway">
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.gateway"
            :invalid="invalid"
            placeholder="10.0.30.1"
            class="font-mono"
            autocomplete="off"
          />
        </template>
      </FormField>

      <FormField :label="t('subnet.fields.site')" :error="errors.site_id" required>
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.site_id ?? 0"
            :options="[{ value: 0, label: '—' }, ...siteOptions]"
            @update:model-value="(v) => (form.site_id = v === 0 ? null : Number(v))"
          />
        </template>
      </FormField>

      <FormField :label="t('subnet.fields.vlan')">
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.vlan_id ?? 0"
            :options="vlanOptions"
            @update:model-value="(v) => (form.vlan_id = v === 0 ? null : Number(v))"
          />
        </template>
      </FormField>

      <FormField class="col-span-2" :label="t('subnet.fields.description')">
        <template #default="{ id }">
          <Textarea :id="id" v-model="form.description" :rows="2" />
        </template>
      </FormField>

      <label class="col-span-2 flex items-center gap-2 text-sm select-none cursor-pointer">
        <input
          v-model="form.dhcp_enabled"
          type="checkbox"
          class="rounded border-border text-primary-600 focus:ring-primary-500"
        />
        {{ t('subnet.fields.dhcpEnabled') }}
      </label>

      <FormField v-if="form.dhcp_enabled" :label="t('subnet.fields.dhcpRangeStart')">
        <template #default="{ id }">
          <Input
            :id="id"
            v-model="form.dhcp_range_start"
            placeholder="10.0.30.100"
            class="font-mono"
            autocomplete="off"
          />
        </template>
      </FormField>
      <FormField v-if="form.dhcp_enabled" :label="t('subnet.fields.dhcpRangeEnd')">
        <template #default="{ id }">
          <Input
            :id="id"
            v-model="form.dhcp_range_end"
            placeholder="10.0.30.200"
            class="font-mono"
            autocomplete="off"
          />
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

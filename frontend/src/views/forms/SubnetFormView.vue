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
import { fetchAllPages, sitesApi, subnetsApi, vlansApi } from '@/api'
import type { Site, Subnet, SubnetCreate, SubnetUpdate, Vlan } from '@/api'
import { vrfsApi } from '@/api/endpoints/vrfs'
import type { Vrf } from '@/api/endpoints/vrfs'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { describe, notify } = useApiErrorMessage()
const { success } = useToast()

// `/subnets/new` has no id param; `/subnets/:id/edit` does. One component
// serves both so the two forms can never drift apart.
const id = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => id.value !== null)

interface Form {
  cidr: string
  gateway: string
  vlan_id: number | null
  site_id: number | null
  vrf_id: number | null
  parent_subnet_id: number | null
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
  vrf_id: null,
  parent_subnet_id: null,
  description: '',
  dhcp_enabled: false,
  dhcp_range_start: '',
  dhcp_range_end: '',
})
const errors = reactive<Partial<Record<keyof Form, string | null>>>({})
const submitError = ref<string | null>(null)
const saving = ref(false)
const loading = ref(false)

const sites = ref<Site[]>([])
const vlans = ref<Vlan[]>([])
const vrfs = ref<Vrf[]>([])
// Parent picker — same VRF as the current form. Loaded lazily because most
// installs don't use hierarchical IPAM and the picker stays hidden anyway.
const candidateParents = ref<Subnet[]>([])
const loadingRefs = ref(false)

// Pre-load the dropdown sources; `fetchAllPages` walks the server's 200-row
// pages so even deployments past the cap fill the pickers completely.
async function loadDropdowns() {
  if (loadingRefs.value) return
  loadingRefs.value = true
  try {
    const [s, v, vr] = await Promise.all([
      fetchAllPages((p) => sitesApi.list(p)),
      fetchAllPages((p) => vlansApi.list(p)),
      vrfsApi.list().catch(() => [] as Vrf[]),
    ])
    sites.value = s
    vlans.value = v
    vrfs.value = vr
  } finally {
    loadingRefs.value = false
  }
}

// Reload the parent candidates whenever the chosen VRF changes, so the
// picker only ever offers subnets in the same routing scope (matches the
// server-side `_validate_parent` rule).
async function loadParentCandidates() {
  const scope = form.vrf_id ?? 0 // 0 = global
  try {
    const items = await fetchAllPages((p) => subnetsApi.list({ ...p, vrf_id: scope }))
    candidateParents.value = items.filter((s) => s.id !== id.value)
  } catch {
    candidateParents.value = []
  }
}

onMounted(async () => {
  loadDropdowns()
  if (isEdit.value) {
    loading.value = true
    try {
      const subnet = await subnetsApi.get(id.value!)
      form.cidr = subnet.cidr
      form.gateway = subnet.gateway ?? ''
      form.vlan_id = subnet.vlan_id ?? null
      form.site_id = subnet.site_id ?? null
      form.vrf_id = subnet.vrf_id ?? null
      form.parent_subnet_id = subnet.parent_subnet_id ?? null
      form.description = subnet.description ?? ''
      form.dhcp_enabled = subnet.dhcp_enabled ?? false
      form.dhcp_range_start = subnet.dhcp_range_start ?? ''
      form.dhcp_range_end = subnet.dhcp_range_end ?? ''
    } catch (err) {
      notify(err)
      router.replace({ name: 'subnets' })
      return
    } finally {
      loading.value = false
    }
  }
  // Only once the VRF is known — the candidate list is scoped to it.
  loadParentCandidates()
})

const siteOptions = computed(() =>
  sites.value.map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` })),
)
const vlanOptions = computed(() => [
  { value: 0, label: t('common.none') },
  ...vlans.value.map((v) => ({ value: v.id, label: `${v.vlan_id} — ${v.name}` })),
])
const vrfOptions = computed(() => [
  { value: 0, label: t('subnet.vrfFilterGlobal') },
  ...vrfs.value.map((v) => ({ value: v.id, label: v.name })),
])
const parentOptions = computed(() => [
  { value: 0, label: t('common.none') },
  ...candidateParents.value.map((s) => ({ value: s.id, label: s.cidr })),
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

// Editing can be started from the list or from the subnet's own detail page.
// `?from=` carries whichever it was so saving returns you where you were,
// instead of always dumping you back on the list.
function goBack() {
  const from = route.query.from
  if (typeof from === 'string' && from.startsWith('/')) {
    router.push(from)
    return
  }
  router.push({ name: 'subnets' })
}

async function onSubmit() {
  if (saving.value || !validate()) return
  saving.value = true
  submitError.value = null
  try {
    const payload = {
      cidr: form.cidr.trim(),
      gateway: form.gateway.trim() || null,
      vlan_id: form.vlan_id && form.vlan_id !== 0 ? form.vlan_id : null,
      site_id: form.site_id!,
      vrf_id: form.vrf_id && form.vrf_id !== 0 ? form.vrf_id : null,
      parent_subnet_id:
        form.parent_subnet_id && form.parent_subnet_id !== 0 ? form.parent_subnet_id : null,
      description: form.description.trim() || null,
      dhcp_enabled: form.dhcp_enabled,
      dhcp_range_start: form.dhcp_range_start.trim() || null,
      dhcp_range_end: form.dhcp_range_end.trim() || null,
    }
    if (isEdit.value) {
      const update: SubnetUpdate = payload
      await subnetsApi.update(id.value!, update)
    } else {
      const create: SubnetCreate = payload
      await subnetsApi.create(create)
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
  { label: t('subnet.labelPlural'), to: { name: 'subnets' } },
  { label: isEdit.value ? t('subnet.edit') : t('subnet.new') },
])
</script>

<template>
  <FormPage
    :title="isEdit ? t('subnet.edit') : t('subnet.new')"
    :subtitle="t('subnet.formSubtitle')"
    :breadcrumb="breadcrumb"
    :error="submitError"
    :saving="saving"
    @submit="onSubmit"
    @cancel="goBack"
  >
    <FormSection
      :title="t('subnet.section.addressing')"
      :description="t('subnet.section.addressingHelp')"
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('subnet.fields.cidr')" :error="errors.cidr" required>
          <template #help>
            <HelpTooltip :text="t('subnet.help.cidr')" />
          </template>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
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
          <template #help>
            <HelpTooltip :text="t('subnet.help.gateway')" />
          </template>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
              v-model="form.gateway"
              :invalid="invalid"
              placeholder="10.0.30.1"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('subnet.fields.site')" :error="errors.site_id" required>
          <template #help>
            <HelpTooltip :text="t('subnet.help.site')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.site_id ?? 0"
              :options="[{ value: 0, label: '—' }, ...siteOptions]"
              @update:model-value="(v) => (form.site_id = v === 0 ? null : Number(v))"
            />
          </template>
        </FormField>

        <FormField :label="t('subnet.fields.vlan')">
          <template #help>
            <HelpTooltip :text="t('subnet.help.vlan')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.vlan_id ?? 0"
              :options="vlanOptions"
              @update:model-value="(v) => (form.vlan_id = v === 0 ? null : Number(v))"
            />
          </template>
        </FormField>

        <FormField class="sm:col-span-2 lg:col-span-3" :label="t('subnet.fields.description')">
          <template #default="{ id: fieldId }">
            <Textarea :id="fieldId" v-model="form.description" :rows="3" />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection :title="t('subnet.section.scope')" :description="t('subnet.section.scopeHelp')">
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('vrf.label')">
          <template #help>
            <HelpTooltip :text="t('subnet.help.vrf')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.vrf_id ?? 0"
              :options="vrfOptions"
              @update:model-value="
                (v) => {
                  form.vrf_id = v === 0 ? null : Number(v)
                  // Changing VRF invalidates the current parent — clear + reload.
                  form.parent_subnet_id = null
                  loadParentCandidates()
                }
              "
            />
          </template>
        </FormField>

        <FormField :label="t('subnet.fields.parent')">
          <template #help>
            <HelpTooltip :text="t('subnet.help.parent')" />
          </template>
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.parent_subnet_id ?? 0"
              :options="parentOptions"
              @update:model-value="(v) => (form.parent_subnet_id = v === 0 ? null : Number(v))"
            />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection :title="t('subnet.section.dhcp')" :description="t('subnet.section.dhcpHelp')">
      <template v-if="loading">
        <Skeleton class="sm:col-span-2 lg:col-span-3" width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <div
          class="sm:col-span-2 lg:col-span-3 flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-base"
        >
          <label class="flex items-center gap-2 select-none cursor-pointer text-fg">
            <input
              v-model="form.dhcp_enabled"
              type="checkbox"
              class="h-4 w-4 rounded accent-primary-600 cursor-pointer"
            />
            {{ t('subnet.fields.dhcpEnabled') }}
          </label>
          <HelpTooltip :text="t('subnet.help.dhcp')" />
        </div>

        <FormField v-if="form.dhcp_enabled" :label="t('subnet.fields.dhcpRangeStart')">
          <template #help>
            <HelpTooltip :text="t('subnet.help.dhcpRange')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input
              :id="fieldId"
              v-model="form.dhcp_range_start"
              placeholder="10.0.30.100"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>
        <FormField v-if="form.dhcp_enabled" :label="t('subnet.fields.dhcpRangeEnd')">
          <template #default="{ id: fieldId }">
            <Input
              :id="fieldId"
              v-model="form.dhcp_range_end"
              placeholder="10.0.30.200"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>
      </template>
    </FormSection>
  </FormPage>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Eye, EyeOff } from 'lucide-vue-next'
import FormPage from '@/components/FormPage.vue'
import FormSection from '@/components/FormSection.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { fetchAllPages, roomsApi, switchesApi } from '@/api'
import type { Room, SwitchCreate, SwitchUpdate } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'
import { isValidIpv4 } from '@/utils/cidr'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { describe, notify } = useApiErrorMessage()
const { success } = useToast()

// `/switches/new` has no id param; `/switches/:id/edit` does. One component
// serves both so the two forms can never drift apart.
const id = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => id.value !== null)

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
const loading = ref(false)
const rooms = ref<Room[]>([])

// SNMP community is a shared secret in plain text on the wire (SNMPv1/v2c
// has no concept of hiding it), so masking it by default is mostly a "don't
// shoulder-surf it" courtesy — a toggle to reveal it is standard for that
// class of field (same idea as a password field with a show/hide eye).
const showSnmpCommunity = ref(false)

onMounted(async () => {
  // Rooms populate the placement select in both modes; they are not part of
  // the entity load, so a slow /rooms never blocks the create form.
  fetchAllPages((p) => roomsApi.list(p)).then((r) => (rooms.value = r))
  if (!isEdit.value) return
  loading.value = true
  try {
    const s = await switchesApi.get(id.value!)
    form.name = s.name
    form.vendor = s.vendor ?? ''
    form.model = s.model ?? ''
    form.serial = s.serial ?? ''
    form.management_ip = s.management_ip ?? ''
    form.room_id = s.room_id ?? null
    form.rack_position = s.rack_position ?? ''
    form.port_count = s.port_count
    form.firmware_version = s.firmware_version ?? ''
    form.snmp_community = s.snmp_community ?? ''
    form.asset_tag = s.asset_tag ?? ''
    form.warranty_expires_at = s.warranty_expires_at ?? ''
    form.eol_date = s.eol_date ?? ''
    form.description = s.description ?? ''
  } catch (err) {
    notify(err)
    router.replace({ name: 'switches' })
  } finally {
    loading.value = false
  }
})

const roomOptions = computed(() => [
  { value: 0, label: t('common.none') },
  ...rooms.value.map((r) => ({ value: r.id, label: r.code })),
])

// Real IPv4 parsing (utils/cidr.ts) instead of a hand-rolled regex — a regex
// like `\d{1,3}` only checks digit count, so it happily accepted an
// out-of-range octet.
function validateManagementIp(): boolean {
  if (form.management_ip && !isValidIpv4(form.management_ip.trim())) {
    errors.management_ip = t('common.validation.invalidIp')
    return false
  }
  errors.management_ip = null
  return true
}

function validate(): boolean {
  let ok = true
  errors.name = errors.port_count = null
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
  if (!validateManagementIp()) ok = false
  return ok
}

// Editing can be started from the list or from the switch's own detail page.
// `?from=` carries whichever it was so saving returns you where you were.
function goBack() {
  const from = route.query.from
  if (typeof from === 'string' && from.startsWith('/')) {
    router.push(from)
    return
  }
  router.push({ name: 'switches' })
}

async function onSubmit() {
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
    if (isEdit.value) {
      // port_count is intentionally not part of SwitchUpdate.
      const update: SwitchUpdate = common
      await switchesApi.update(id.value!, update)
    } else {
      const create: SwitchCreate = { ...common, port_count: form.port_count }
      await switchesApi.create(create)
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
  { label: t('switch.labelPlural'), to: { name: 'switches' } },
  { label: isEdit.value ? t('switch.edit') : t('switch.new') },
])
</script>

<template>
  <FormPage
    :title="isEdit ? t('switch.edit') : t('switch.new')"
    :subtitle="t('switch.formSubtitle')"
    :breadcrumb="breadcrumb"
    :error="submitError"
    :saving="saving"
    @submit="onSubmit"
    @cancel="goBack"
  >
    <FormSection
      :title="t('switch.section.identity')"
      :description="t('switch.section.identityHelp')"
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('switch.fields.name')" :error="errors.name" required>
          <template #help>
            <HelpTooltip :text="t('switch.help.name')" />
          </template>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
              v-model="form.name"
              :invalid="invalid"
              placeholder="sw-core-01"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('switch.fields.managementIp')" :error="errors.management_ip">
          <template #help>
            <HelpTooltip :text="t('switch.help.managementIp')" />
          </template>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
              v-model="form.management_ip"
              :invalid="invalid"
              placeholder="10.0.0.10"
              class="font-mono"
              autocomplete="off"
              @blur="validateManagementIp()"
            />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('switch.section.hardware')"
      :description="t('switch.section.hardwareHelp')"
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('switch.fields.vendor')">
          <template #default="{ id: fieldId }">
            <Input :id="fieldId" v-model="form.vendor" placeholder="Cisco" autocomplete="off" />
          </template>
        </FormField>
        <FormField :label="t('switch.fields.model')">
          <template #default="{ id: fieldId }">
            <Input :id="fieldId" v-model="form.model" placeholder="C9300-48P" autocomplete="off" />
          </template>
        </FormField>

        <!-- Serial / firmware are code-like values: mono face so a zero can
             never be read as an O. -->
        <FormField :label="t('switch.fields.serial')">
          <template #default="{ id: fieldId }">
            <Input :id="fieldId" v-model="form.serial" class="font-mono" autocomplete="off" />
          </template>
        </FormField>
        <FormField :label="t('switch.fields.firmware')">
          <template #help>
            <HelpTooltip :text="t('switch.help.firmware')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input
              :id="fieldId"
              v-model="form.firmware_version"
              placeholder="17.09.04a"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField
          :label="t('switch.fields.portCount')"
          :error="errors.port_count"
          :hint="isEdit ? t('switch.portCountImmutable') : undefined"
          required
        >
          <template #help>
            <HelpTooltip :text="t('switch.help.portCount')" />
          </template>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
              v-model.number="form.port_count"
              type="number"
              min="1"
              max="1024"
              :invalid="invalid"
              :readonly="isEdit"
              placeholder="48"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('switch.fields.snmpCommunity')" :hint="t('switch.snmpCommunityHint')">
          <template #help>
            <HelpTooltip :text="t('switch.help.snmpCommunity')" />
          </template>
          <template #default="{ id: fieldId }">
            <div class="relative">
              <Input
                :id="fieldId"
                v-model="form.snmp_community"
                :type="showSnmpCommunity ? 'text' : 'password'"
                autocomplete="off"
                class="pr-9"
              />
              <button
                type="button"
                class="absolute inset-y-0 right-0 flex items-center px-2.5 text-fg-muted hover:text-fg transition-colors duration-150 ease-soft"
                :aria-label="showSnmpCommunity ? t('common.hide') : t('common.reveal')"
                :title="showSnmpCommunity ? t('common.hide') : t('common.reveal')"
                @click="showSnmpCommunity = !showSnmpCommunity"
              >
                <EyeOff v-if="showSnmpCommunity" class="w-4 h-4" aria-hidden="true" />
                <Eye v-else class="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('switch.section.placement')"
      :description="t('switch.section.placementHelp')"
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('switch.fields.room')">
          <template #default="{ id: fieldId }">
            <Select
              :id="fieldId"
              :model-value="form.room_id ?? 0"
              :options="roomOptions"
              @update:model-value="(v) => (form.room_id = v === 0 ? null : Number(v))"
            />
          </template>
        </FormField>
        <FormField :label="t('switch.fields.rackPosition')">
          <template #help>
            <HelpTooltip :text="t('switch.help.rackPosition')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input
              :id="fieldId"
              v-model="form.rack_position"
              placeholder="U22"
              autocomplete="off"
            />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('switch.section.lifecycle')"
      :description="t('switch.section.lifecycleHelp')"
    >
      <template v-if="loading">
        <Skeleton width="100%" height="2.25rem" rounded="md" />
        <Skeleton width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField :label="t('switch.fields.assetTag')">
          <template #help>
            <HelpTooltip :text="t('switch.help.assetTag')" />
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
        <FormField :label="t('switch.fields.warrantyExpiresAt')">
          <template #help>
            <HelpTooltip :text="t('switch.help.warranty')" />
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
        <FormField :label="t('switch.fields.eolDate')" :hint="t('switch.eolHint')">
          <template #help>
            <HelpTooltip :text="t('switch.help.eol')" />
          </template>
          <template #default="{ id: fieldId }">
            <Input :id="fieldId" v-model="form.eol_date" type="date" autocomplete="off" />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('switch.section.notes')"
      :description="t('switch.section.notesHelp')"
      single
    >
      <Skeleton v-if="loading" width="100%" height="4rem" rounded="md" />
      <FormField v-else :label="t('switch.fields.description')">
        <template #default="{ id: fieldId }">
          <Textarea :id="fieldId" v-model="form.description" :rows="3" />
        </template>
      </FormField>
    </FormSection>
  </FormPage>
</template>

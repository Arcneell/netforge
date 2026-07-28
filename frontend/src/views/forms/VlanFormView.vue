<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import FormPage from '@/components/FormPage.vue'
import FormSection from '@/components/FormSection.vue'
import Input from '@/components/ui/Input.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { vlansApi } from '@/api'
import type { VlanCreate, VlanUpdate } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { describe, notify } = useApiErrorMessage()
const { success } = useToast()

// `/vlans/new` has no id param; `/vlans/:id/edit` does. One component serves
// both so the two forms can never drift apart.
const id = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => id.value !== null)

interface Form {
  vlan_id: number | null
  name: string
  description: string
  color: string
}

const form = reactive<Form>({ vlan_id: null, name: '', description: '', color: '' })
const errors = reactive<Record<keyof Form, string | null>>({
  vlan_id: null,
  name: null,
  description: null,
  color: null,
})
const submitError = ref<string | null>(null)
const saving = ref(false)
const loading = ref(false)

onMounted(async () => {
  if (!isEdit.value) return
  loading.value = true
  try {
    const vlan = await vlansApi.get(id.value!)
    form.vlan_id = vlan.vlan_id
    form.name = vlan.name
    form.description = vlan.description ?? ''
    form.color = vlan.color ?? ''
  } catch (err) {
    notify(err)
    router.replace({ name: 'vlans' })
  } finally {
    loading.value = false
  }
})

function validate(): boolean {
  let ok = true
  errors.vlan_id = errors.name = errors.color = null

  if (form.vlan_id === null || !Number.isInteger(form.vlan_id)) {
    errors.vlan_id = t('common.validation.required')
    ok = false
  } else if (form.vlan_id < 1 || form.vlan_id > 4094) {
    errors.vlan_id = t('common.validation.vlanIdRange')
    ok = false
  }

  if (!form.name.trim()) {
    errors.name = t('common.validation.required')
    ok = false
  } else if (form.name.length > 100) {
    errors.name = t('common.validation.maxLength', { max: 100 })
    ok = false
  }

  if (form.color && !/^#[0-9a-fA-F]{6}$/.test(form.color)) {
    errors.color = t('common.validation.invalidHexColor')
    ok = false
  }
  return ok
}

function goBack() {
  router.push({ name: 'vlans' })
}

async function onSubmit() {
  if (saving.value || !validate()) return
  saving.value = true
  submitError.value = null
  try {
    const payload = {
      vlan_id: form.vlan_id!,
      name: form.name.trim(),
      description: form.description.trim() || null,
      color: form.color || null,
    }
    if (isEdit.value) {
      await vlansApi.update(id.value!, payload as VlanUpdate)
    } else {
      await vlansApi.create(payload as VlanCreate)
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
  { label: t('vlan.labelPlural'), to: { name: 'vlans' } },
  { label: isEdit.value ? t('vlan.edit') : t('vlan.new') },
])
</script>

<template>
  <FormPage
    :title="isEdit ? t('vlan.edit') : t('vlan.new')"
    :subtitle="t('vlan.formSubtitle')"
    :breadcrumb="breadcrumb"
    :error="submitError"
    :saving="saving"
    @submit="onSubmit"
    @cancel="goBack"
  >
    <FormSection :title="t('vlan.section.identity')" :description="t('vlan.section.identityHelp')">
      <template v-if="loading">
        <Skeleton class="sm:col-span-2 lg:col-span-3" width="100%" height="2.25rem" rounded="md" />
        <Skeleton class="sm:col-span-2 lg:col-span-3" width="100%" height="2.25rem" rounded="md" />
      </template>
      <template v-else>
        <FormField
          :label="t('vlan.fields.vlanId')"
          :error="errors.vlan_id"
          :hint="t('common.validation.vlanIdRange')"
          required
        >
          <template #help>
            <HelpTooltip :text="t('vlan.help.vlanId')" />
          </template>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
              v-model.number="form.vlan_id"
              type="number"
              min="1"
              max="4094"
              :invalid="invalid"
              placeholder="100"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField :label="t('vlan.fields.name')" :error="errors.name" required>
          <template #default="{ id: fieldId, invalid }">
            <Input
              :id="fieldId"
              v-model="form.name"
              :invalid="invalid"
              placeholder="Office"
              maxlength="100"
              autocomplete="off"
            />
          </template>
        </FormField>

        <FormField class="sm:col-span-2 lg:col-span-3" :label="t('vlan.fields.description')">
          <template #default="{ id: fieldId }">
            <Textarea :id="fieldId" v-model="form.description" :rows="3" />
          </template>
        </FormField>
      </template>
    </FormSection>

    <FormSection
      :title="t('vlan.section.appearance')"
      :description="t('vlan.section.appearanceHelp')"
    >
      <FormField :label="t('vlan.fields.color')" :error="errors.color">
        <template #help>
          <HelpTooltip :text="t('vlan.help.color')" />
        </template>
        <template #default="{ id: fieldId, invalid }">
          <div class="flex items-center gap-2">
            <!-- The swatch is the one place a raw colour is legitimate: the
                 value is the record's own. -->
            <input
              type="color"
              :value="form.color || '#6366f1'"
              class="w-9 h-9 shrink-0 rounded-md border border-border-strong bg-surface cursor-pointer p-1 transition-colors duration-150 ease-soft hover:border-primary-500"
              :aria-label="t('vlan.fields.color')"
              @input="form.color = ($event.target as HTMLInputElement).value"
            />
            <Input
              :id="fieldId"
              v-model="form.color"
              :invalid="invalid"
              placeholder="#6366f1"
              class="flex-1 font-mono"
              autocomplete="off"
            />
          </div>
        </template>
      </FormField>
    </FormSection>
  </FormPage>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import { vlansApi } from '@/api'
import type { Vlan, VlanCreate, VlanUpdate } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

const props = defineProps<{
  open: boolean
  /** Pass the existing VLAN to edit; omit to create. */
  vlan?: Vlan | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', vlan: Vlan): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { success } = useToast()

interface Form {
  vlan_id: number | null
  name: string
  description: string
  color: string
}

const form = reactive<Form>({
  vlan_id: null,
  name: '',
  description: '',
  color: '',
})
const errors = reactive<Record<keyof Form, string | null>>({
  vlan_id: null,
  name: null,
  description: null,
  color: null,
})
const submitError = ref<string | null>(null)
const saving = ref(false)

const isEdit = computed(() => !!props.vlan)

// Reset the form every time the modal re-opens. Without this, a stale value
// from the previous edit would bleed into a fresh "Create".
watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.vlan_id = props.vlan?.vlan_id ?? null
    form.name = props.vlan?.name ?? ''
    form.description = props.vlan?.description ?? ''
    form.color = props.vlan?.color ?? ''
    errors.vlan_id = errors.name = errors.description = errors.color = null
    submitError.value = null
  },
)

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

async function onSubmit(e: Event) {
  e.preventDefault()
  if (saving.value || !validate()) return
  saving.value = true
  submitError.value = null
  try {
    let saved: Vlan
    const payload = {
      vlan_id: form.vlan_id!,
      name: form.name.trim(),
      description: form.description.trim() || null,
      color: form.color || null,
    }
    if (props.vlan) {
      const update: VlanUpdate = payload
      saved = await vlansApi.update(props.vlan.id, update)
    } else {
      const create: VlanCreate = payload
      saved = await vlansApi.create(create)
    }
    success(isEdit.value ? t('common.success') : t('common.success'))
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
    :title="isEdit ? t('vlan.edit') : t('vlan.new')"
    size="md"
    @close="emit('close')"
  >
    <form class="flex flex-col gap-4" @submit="onSubmit">
      <div class="grid grid-cols-2 gap-3">
        <FormField :label="t('vlan.fields.vlanId')" :error="errors.vlan_id" required>
          <template #default="{ id, invalid }">
            <Input
              :id="id"
              v-model.number="form.vlan_id"
              type="number"
              min="1"
              max="4094"
              :invalid="invalid"
              placeholder="100"
              autocomplete="off"
            />
          </template>
        </FormField>
        <FormField :label="t('vlan.fields.color')" :error="errors.color">
          <template #default="{ id, invalid }">
            <div class="flex items-center gap-2">
              <input
                type="color"
                :value="form.color || '#06b6d4'"
                class="w-9 h-9 rounded border border-border bg-surface cursor-pointer p-0.5"
                :aria-label="t('vlan.fields.color')"
                @input="form.color = ($event.target as HTMLInputElement).value"
              />
              <Input
                :id="id"
                v-model="form.color"
                :invalid="invalid"
                placeholder="#06b6d4"
                class="flex-1 font-mono"
                autocomplete="off"
              />
            </div>
          </template>
        </FormField>
      </div>

      <FormField :label="t('vlan.fields.name')" :error="errors.name" required>
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.name"
            :invalid="invalid"
            placeholder="Office"
            maxlength="100"
            autocomplete="off"
          />
        </template>
      </FormField>

      <FormField :label="t('vlan.fields.description')">
        <template #default="{ id }">
          <Textarea :id="id" v-model="form.description" :rows="3" placeholder="" />
        </template>
      </FormField>

      <p v-if="submitError" class="text-sm text-danger" role="alert">{{ submitError }}</p>
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

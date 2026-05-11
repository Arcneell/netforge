<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import { roomsApi, sitesApi } from '@/api'
import type { Room, RoomCreate, RoomUpdate, Site } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const props = defineProps<{
  open: boolean
  room?: Room | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', room: Room): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

const form = reactive({ site_id: null as number | null, code: '', description: '' })
const errors = reactive<Record<string, string | null>>({ site_id: null, code: null })
const submitError = ref<string | null>(null)
const saving = ref(false)
const sites = ref<Site[]>([])

const isEdit = computed(() => !!props.room)

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    form.site_id = props.room?.site_id ?? null
    form.code = props.room?.code ?? ''
    form.description = props.room?.description ?? ''
    errors.site_id = errors.code = null
    submitError.value = null
    const r = await sitesApi.list({ page_size: 200 })
    sites.value = r.items
  },
)

const siteOptions = computed(() => [
  { value: 0, label: '—' },
  ...sites.value.map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` })),
])

function validate(): boolean {
  let ok = true
  errors.site_id = errors.code = null
  if (!form.site_id) {
    errors.site_id = t('common.validation.required')
    ok = false
  }
  if (!form.code.trim()) {
    errors.code = t('common.validation.required')
    ok = false
  } else if (form.code.length > 50) {
    errors.code = t('common.validation.maxLength', { max: 50 })
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
      site_id: form.site_id!,
      code: form.code.trim(),
      description: form.description.trim() || null,
    }
    let saved: Room
    if (props.room) {
      const update: RoomUpdate = payload
      saved = await roomsApi.update(props.room.id, update)
    } else {
      const create: RoomCreate = payload
      saved = await roomsApi.create(create)
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
    :title="isEdit ? t('room.edit') : t('room.new')"
    size="md"
    @close="emit('close')"
  >
    <form class="grid grid-cols-2 gap-4" @submit="onSubmit">
      <FormField :label="t('room.fields.site')" :error="errors.site_id" required>
        <template #default="{ id }">
          <Select
            :id="id"
            :model-value="form.site_id ?? 0"
            :options="siteOptions"
            @update:model-value="(v) => (form.site_id = v === 0 ? null : Number(v))"
          />
        </template>
      </FormField>
      <FormField :label="t('room.fields.code')" :error="errors.code" required>
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.code"
            :invalid="invalid"
            placeholder="MDF-01"
            autocomplete="off"
          />
        </template>
      </FormField>
      <FormField class="col-span-2" :label="t('room.fields.description')">
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

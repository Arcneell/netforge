<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle } from '@lucide/vue'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import { sitesApi } from '@/api'
import type { Site, SiteCreate, SiteUpdate } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const props = defineProps<{
  open: boolean
  site?: Site | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', site: Site): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

const form = reactive({ code: '', name: '', address: '' })
const errors = reactive<Record<string, string | null>>({ code: null, name: null })
const submitError = ref<string | null>(null)
const saving = ref(false)

const isEdit = computed(() => !!props.site)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.code = props.site?.code ?? ''
    form.name = props.site?.name ?? ''
    form.address = props.site?.address ?? ''
    errors.code = errors.name = null
    submitError.value = null
  },
)

function validate(): boolean {
  let ok = true
  errors.code = errors.name = null
  if (!form.code.trim()) {
    errors.code = t('common.validation.required')
    ok = false
  } else if (!/^[A-Za-z0-9_-]+$/.test(form.code.trim())) {
    errors.code = t('common.validation.pattern')
    ok = false
  } else if (form.code.length > 20) {
    errors.code = t('common.validation.maxLength', { max: 20 })
    ok = false
  }
  if (!form.name.trim()) {
    errors.name = t('common.validation.required')
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
      code: form.code.trim(),
      name: form.name.trim(),
      address: form.address.trim() || null,
    }
    let saved: Site
    if (props.site) {
      const update: SiteUpdate = payload
      saved = await sitesApi.update(props.site.id, update)
    } else {
      const create: SiteCreate = payload
      saved = await sitesApi.create(create)
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
    :title="isEdit ? t('site.edit') : t('site.new')"
    size="md"
    @close="emit('close')"
  >
    <!-- One rhythm for every editor: single column on a phone, two from `sm`
         up, a uniform 1rem gutter, and full-width rows opting in with
         `sm:col-span-2`. -->
    <form class="grid grid-cols-1 sm:grid-cols-2 gap-4" @submit="onSubmit">
      <FormField :label="t('site.fields.code')" :error="errors.code" required>
        <template #help>
          <HelpTooltip :text="t('site.help.code')" />
        </template>
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.code"
            :invalid="invalid"
            maxlength="20"
            placeholder="PAR-DC1"
            class="font-mono"
            autocomplete="off"
          />
        </template>
      </FormField>
      <FormField :label="t('site.fields.name')" :error="errors.name" required>
        <template #default="{ id, invalid }">
          <Input
            :id="id"
            v-model="form.name"
            :invalid="invalid"
            maxlength="200"
            autocomplete="off"
          />
        </template>
      </FormField>
      <FormField class="sm:col-span-2" :label="t('site.fields.address')">
        <template #default="{ id }">
          <Textarea :id="id" v-model="form.address" :rows="2" />
        </template>
      </FormField>

      <!-- Form-level failure (the API said no). Field-level problems always
           render inside their own FormField, so this block is the single
           place a submit error can appear. -->
      <p
        v-if="submitError"
        class="sm:col-span-2 flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
        role="alert"
      >
        <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
        <span>{{ submitError }}</span>
      </p>
    </form>
    <template #footer>
      <div class="flex items-center justify-end gap-2">
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

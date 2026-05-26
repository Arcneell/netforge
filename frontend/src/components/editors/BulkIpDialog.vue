<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import { subnetsApi } from '@/api'
import type { Subnet } from '@/api'
import type {
  BulkIpAction,
  BulkIpResult,
  BulkIpStatus,
} from '@/api/endpoints/subnets'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const props = defineProps<{
  open: boolean
  subnet: Subnet
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'applied', summary: BulkIpResult): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

interface Form {
  action: BulkIpAction
  start: string
  end: string
  status: BulkIpStatus
  overwrite: boolean
  description: string
}

const form = reactive<Form>({
  action: 'reserve',
  start: '',
  end: '',
  status: 'reserved',
  overwrite: false,
  description: '',
})

const saving = ref(false)
const lastResult = ref<BulkIpResult | null>(null)

// The status picker uses the shared <Select> which takes a flat options
// array. Re-derive on each render so the labels track the active locale.
const statusOptions = computed<{ value: BulkIpStatus; label: string }[]>(() => [
  { value: 'reserved', label: t('ip.status.reserved') },
  { value: 'assigned', label: t('ip.status.assigned') },
  { value: 'dhcp', label: t('ip.status.dhcp') },
])

// Reset the form every time the dialog opens — leftover values from a
// previous reservation are confusing when picking a different range.
watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.action = 'reserve'
    form.start = ''
    form.end = ''
    form.status = 'reserved'
    form.overwrite = false
    form.description = ''
    lastResult.value = null
  },
)

// Light client-side sanity: dotted-quad shape. The backend re-parses
// with `ipaddress.IPv4Address` so any genuine malformed input still
// surfaces a 422 — this is just to disable the submit button on
// obviously incomplete state without hitting the API.
const isValidAddr = (v: string) => /^(\d{1,3}\.){3}\d{1,3}$/.test(v.trim())
const canSubmit = computed(
  () =>
    !saving.value &&
    isValidAddr(form.start) &&
    isValidAddr(form.end) &&
    (form.action === 'release' || !!form.status),
)

async function apply() {
  if (!canSubmit.value) return
  saving.value = true
  try {
    const summary = await subnetsApi.bulkIpRange(props.subnet.id, {
      action: form.action,
      start: form.start.trim(),
      end: form.end.trim(),
      status: form.action === 'reserve' ? form.status : undefined,
      overwrite: form.action === 'reserve' ? form.overwrite : undefined,
      description: form.description.trim() || undefined,
    })
    lastResult.value = summary
    emit('applied', summary)
  } catch (err) {
    void describe(err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Modal :open="open" :title="t('subnet.bulk.title')" size="md" @close="emit('close')">
    <div class="space-y-4">
      <p class="text-sm text-fg-muted">
        {{ t('subnet.bulk.help', { cidr: subnet.cidr }) }}
      </p>

      <!-- Action toggle: reserve / release. Reserve shows the status +
           overwrite + description fields; release hides them since they
           don't apply. -->
      <FormField :label="t('subnet.bulk.actionLabel')">
        <div class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface">
          <button
            type="button"
            :aria-pressed="form.action === 'reserve'"
            :class="[
              'px-3 h-8 rounded text-sm font-medium transition',
              form.action === 'reserve'
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
            ]"
            @click="form.action = 'reserve'"
          >
            {{ t('subnet.bulk.reserve') }}
          </button>
          <button
            type="button"
            :aria-pressed="form.action === 'release'"
            :class="[
              'px-3 h-8 rounded text-sm font-medium transition',
              form.action === 'release'
                ? 'bg-danger/15 text-danger'
                : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
            ]"
            @click="form.action = 'release'"
          >
            {{ t('subnet.bulk.release') }}
          </button>
        </div>
      </FormField>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <FormField :label="t('subnet.bulk.start')">
          <Input v-model="form.start" placeholder="10.0.0.10" />
        </FormField>
        <FormField :label="t('subnet.bulk.end')">
          <Input v-model="form.end" placeholder="10.0.0.20" />
        </FormField>
      </div>

      <template v-if="form.action === 'reserve'">
        <FormField :label="t('ip.fields.status')">
          <template #help>
            <HelpTooltip :text="t('subnet.bulk.statusHelp')" />
          </template>
          <Select v-model="form.status" :options="statusOptions" />
        </FormField>

        <FormField :label="t('ip.fields.description')">
          <Textarea
            v-model="form.description"
            :rows="2"
            :placeholder="t('subnet.bulk.descriptionPlaceholder')"
          />
        </FormField>

        <label class="flex items-start gap-2 text-sm">
          <input
            v-model="form.overwrite"
            type="checkbox"
            class="mt-0.5"
          />
          <span>
            <span class="font-medium">{{ t('subnet.bulk.overwrite') }}</span>
            <span class="block text-xs text-fg-muted">
              {{ t('subnet.bulk.overwriteHelp') }}
            </span>
          </span>
        </label>
      </template>

      <!-- Summary block — only appears after a successful round-trip.
           Encodes the four counters the backend returns so the operator
           knows exactly what happened without re-checking the grid. -->
      <div v-if="lastResult" class="nf-card p-3 text-sm bg-success/5 border-success/30">
        <p class="font-semibold text-fg mb-1">{{ t('subnet.bulk.resultTitle') }}</p>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <dt class="text-fg-muted">{{ t('subnet.bulk.requested') }}</dt>
          <dd class="font-mono tabular-nums text-right">{{ lastResult.requested }}</dd>
          <dt class="text-fg-muted">{{ t('subnet.bulk.created') }}</dt>
          <dd class="font-mono tabular-nums text-right text-success">{{ lastResult.created }}</dd>
          <dt class="text-fg-muted">{{ t('subnet.bulk.updated') }}</dt>
          <dd class="font-mono tabular-nums text-right">{{ lastResult.updated }}</dd>
          <dt class="text-fg-muted">{{ t('subnet.bulk.deleted') }}</dt>
          <dd class="font-mono tabular-nums text-right text-danger">{{ lastResult.deleted }}</dd>
          <dt class="text-fg-muted">{{ t('subnet.bulk.skipped') }}</dt>
          <dd class="font-mono tabular-nums text-right text-fg-muted">{{ lastResult.skipped }}</dd>
        </dl>
      </div>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <Button variant="secondary" :disabled="saving" @click="emit('close')">
          {{ t('common.close') }}
        </Button>
        <Button
          :variant="form.action === 'release' ? 'danger' : 'primary'"
          :loading="saving"
          :disabled="!canSubmit"
          @click="apply"
        >
          {{
            form.action === 'release' ? t('subnet.bulk.release') : t('subnet.bulk.applyReserve')
          }}
        </Button>
      </div>
    </template>
  </Modal>
</template>

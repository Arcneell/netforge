<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, CheckCircle2 } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import { subnetsApi } from '@/api'
import type { Subnet } from '@/api'
import type { BulkIpAction, BulkIpResult, BulkIpStatus } from '@/api/endpoints/subnets'
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
const submitError = ref<string | null>(null)

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
    submitError.value = null
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

// Field-level feedback for the two address inputs, shown through the same
// `FormField` slot as every other form in the app. Purely presentational:
// it stays quiet until the user has typed something, and `canSubmit` above
// remains the single gate on the request.
const startError = computed(() =>
  form.start.trim() && !isValidAddr(form.start) ? t('common.validation.invalidIp') : null,
)
const endError = computed(() =>
  form.end.trim() && !isValidAddr(form.end) ? t('common.validation.invalidIp') : null,
)

/** Dotted quad → 32-bit integer, or null when any octet is out of range. */
function addrToInt(value: string): number | null {
  const parts = value.trim().split('.')
  if (parts.length !== 4) return null
  let n = 0
  for (const part of parts) {
    const octet = Number(part)
    if (!/^\d{1,3}$/.test(part) || !Number.isInteger(octet) || octet < 0 || octet > 255) return null
    n = n * 256 + octet
  }
  return n
}

// How many addresses the call will touch. Mirrors the backend's own
// `int(end) - int(start) + 1` span, which is what it reports back as
// `requested`. Null whenever the range isn't expressible yet, which is
// what hides the scope panel.
const rangeSize = computed<number | null>(() => {
  const a = addrToInt(form.start)
  const b = addrToInt(form.end)
  if (a === null || b === null || b < a) return null
  return b - a + 1
})

const isRelease = computed(() => form.action === 'release')

const statusLabel = computed(
  () => statusOptions.value.find((o) => o.value === form.status)?.label ?? form.status,
)

// Counters, in the order the backend fills them, each with the tone that
// says what it means at a glance.
const resultRows = computed(() => {
  const r = lastResult.value
  if (!r) return []
  return [
    { key: 'requested', label: t('subnet.bulk.requested'), value: r.requested, tone: 'text-fg' },
    { key: 'created', label: t('subnet.bulk.created'), value: r.created, tone: 'text-success' },
    { key: 'updated', label: t('subnet.bulk.updated'), value: r.updated, tone: 'text-fg' },
    { key: 'deleted', label: t('subnet.bulk.deleted'), value: r.deleted, tone: 'text-danger' },
    { key: 'skipped', label: t('subnet.bulk.skipped'), value: r.skipped, tone: 'text-fg-muted' },
  ]
})

async function apply() {
  if (!canSubmit.value) return
  saving.value = true
  submitError.value = null
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
    submitError.value = describe(err)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Modal :open="open" :title="t('subnet.bulk.title')" size="md" @close="emit('close')">
    <!-- Same 1rem rhythm as the entity editors; this dialog is single-column
         apart from the address pair. -->
    <div class="flex flex-col gap-4">
      <p class="text-base text-fg-muted">
        {{ t('subnet.bulk.help', { cidr: subnet.cidr }) }}
      </p>

      <!-- Action toggle: reserve / release. Reserve shows the status +
           overwrite + description fields; release hides them since they
           don't apply. -->
      <FormField :label="t('subnet.bulk.actionLabel')">
        <div class="nf-segmented">
          <button
            type="button"
            :aria-pressed="!isRelease"
            :class="['nf-segmented-item', !isRelease ? 'nf-segmented-item-active' : '']"
            @click="form.action = 'reserve'"
          >
            {{ t('subnet.bulk.reserve') }}
          </button>
          <button
            type="button"
            :aria-pressed="isRelease"
            :class="['nf-segmented-item', isRelease ? 'nf-segmented-item-active text-danger' : '']"
            @click="form.action = 'release'"
          >
            {{ t('subnet.bulk.release') }}
          </button>
        </div>
      </FormField>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <FormField :label="t('subnet.bulk.start')" :error="startError">
          <template #default="{ id, invalid }">
            <Input
              :id="id"
              v-model="form.start"
              :invalid="invalid"
              placeholder="10.0.0.10"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>
        <FormField :label="t('subnet.bulk.end')" :error="endError">
          <template #default="{ id, invalid }">
            <Input
              :id="id"
              v-model="form.end"
              :invalid="invalid"
              placeholder="10.0.0.20"
              class="font-mono"
              autocomplete="off"
            />
          </template>
        </FormField>
      </div>

      <template v-if="!isRelease">
        <FormField :label="t('ip.fields.status')">
          <template #help>
            <HelpTooltip :text="t('subnet.bulk.statusHelp')" />
          </template>
          <template #default="{ id }">
            <Select :id="id" v-model="form.status" :options="statusOptions" />
          </template>
        </FormField>

        <FormField :label="t('ip.fields.description')">
          <template #default="{ id }">
            <Textarea
              :id="id"
              v-model="form.description"
              :rows="2"
              :placeholder="t('subnet.bulk.descriptionPlaceholder')"
            />
          </template>
        </FormField>

        <label
          class="flex items-start gap-2.5 rounded-md border border-border bg-muted/40 px-3 py-2 cursor-pointer transition-colors duration-150 ease-soft hover:bg-muted/70"
        >
          <input
            v-model="form.overwrite"
            type="checkbox"
            class="mt-0.5 h-4 w-4 shrink-0 rounded accent-primary-600 cursor-pointer"
          />
          <span class="min-w-0">
            <span class="block text-base font-medium text-fg">
              {{ t('subnet.bulk.overwrite') }}
            </span>
            <span class="block text-xs text-fg-muted">
              {{ t('subnet.bulk.overwriteHelp') }}
            </span>
          </span>
        </label>
      </template>

      <!-- Scope of the write, spelled out. This one click can create or
           delete hundreds of rows, so the exact range, its size and the
           target subnet are restated immediately above the confirm button
           rather than left implicit in the two inputs. -->
      <div
        v-if="rangeSize !== null"
        :class="[
          'flex items-start gap-2.5 rounded-md border px-3 py-2.5',
          isRelease
            ? 'border-danger/30 bg-danger/10'
            : 'border-primary-200 bg-primary-50 dark:border-primary-500/30 dark:bg-primary-500/10',
        ]"
      >
        <AlertTriangle
          :class="[
            'w-4 h-4 shrink-0 mt-0.5',
            isRelease ? 'text-danger' : 'text-primary-600 dark:text-primary-400',
          ]"
          aria-hidden="true"
        />
        <div class="min-w-0 space-y-1.5">
          <p class="text-base text-fg">
            <span class="font-medium">
              {{ isRelease ? t('subnet.bulk.release') : t('subnet.bulk.reserve') }}
            </span>
            <span class="mx-1.5 text-fg-subtle">·</span>
            <span class="font-mono">{{ form.start.trim() }} → {{ form.end.trim() }}</span>
          </p>
          <dl class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            <div class="flex items-baseline gap-1.5">
              <dt class="text-fg-muted">{{ t('subnet.bulk.requested') }}</dt>
              <dd class="font-mono tabular-nums font-medium text-fg">{{ rangeSize }}</dd>
            </div>
            <div class="flex items-baseline gap-1.5">
              <dt class="text-fg-muted">{{ t('subnet.fields.cidr') }}</dt>
              <dd class="font-mono text-fg">{{ subnet.cidr }}</dd>
            </div>
            <div v-if="!isRelease" class="flex items-baseline gap-1.5">
              <dt class="text-fg-muted">{{ t('ip.fields.status') }}</dt>
              <dd class="text-fg">{{ statusLabel }}</dd>
            </div>
            <div v-if="!isRelease && form.overwrite" class="flex items-baseline gap-1.5">
              <dt class="text-fg-muted">{{ t('subnet.bulk.overwrite') }}</dt>
              <dd class="text-fg">{{ t('common.yes') }}</dd>
            </div>
          </dl>
        </div>
      </div>

      <p
        v-if="submitError"
        class="flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
        role="alert"
      >
        <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
        <span>{{ submitError }}</span>
      </p>

      <!-- Summary block — only appears after a successful round-trip.
           Encodes the counters the backend returns so the operator knows
           exactly what happened without re-checking the grid. -->
      <div v-if="lastResult" class="nf-card p-3 border-success/30 bg-success/5">
        <p class="flex items-center gap-1.5 text-base font-medium text-fg mb-2">
          <CheckCircle2 class="w-4 h-4 text-success" aria-hidden="true" />
          {{ t('subnet.bulk.resultTitle') }}
        </p>
        <dl class="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <div
            v-for="row in resultRows"
            :key="row.key"
            class="rounded-md border border-border bg-surface px-2.5 py-1.5"
          >
            <dt class="nf-label">{{ row.label }}</dt>
            <dd :class="['font-mono tabular-nums text-md font-medium', row.tone]">
              {{ row.value }}
            </dd>
          </div>
        </dl>
      </div>
    </div>

    <template #footer>
      <div class="flex items-center justify-end gap-2">
        <Button variant="secondary" :disabled="saving" @click="emit('close')">
          {{ t('common.close') }}
        </Button>
        <Button
          :variant="isRelease ? 'danger' : 'primary'"
          :loading="saving"
          :disabled="!canSubmit"
          @click="apply"
        >
          {{ isRelease ? t('subnet.bulk.release') : t('subnet.bulk.applyReserve') }}
        </Button>
      </div>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Textarea from '@/components/ui/Textarea.vue'
import FormField from '@/components/ui/FormField.vue'
import { linksApi, portsApi, switchesApi } from '@/api'
import type { Link, LinkType, Port, Switch } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const props = defineProps<{
  open: boolean
  /** Pass an existing Link to edit; omit to create a new one. */
  link?: Link | null
  /** Pre-loaded switch list — TopologyView already fetched these, so we let
   * the parent share its cache instead of re-fetching on every open. */
  switches?: Switch[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', link: Link): void
}>()

const { t } = useI18n()
const { describe } = useApiErrorMessage()

const isEdit = computed(() => !!props.link)

interface Form {
  // Create-only fields — endpoints are immutable in edit mode.
  switch_a: string
  port_a: number | null
  switch_b: string
  port_b: number | null
  // Mutable metadata.
  link_type: LinkType
  speed_mbps: number | null
  description: string
}

const form = reactive<Form>({
  switch_a: '',
  port_a: null,
  switch_b: '',
  port_b: null,
  link_type: 'copper',
  speed_mbps: null,
  description: '',
})

const errors = reactive({
  switch_a: null as string | null,
  port_a: null as string | null,
  switch_b: null as string | null,
  port_b: null as string | null,
  speed_mbps: null as string | null,
})

const submitError = ref<string | null>(null)
const saving = ref(false)

// Local switch list when the parent didn't pre-load one. Lazy: we only fetch
// on first open since the editor isn't visible by default.
const localSwitches = ref<Switch[]>([])
const allSwitches = computed<Switch[]>(() =>
  props.switches && props.switches.length > 0 ? props.switches : localSwitches.value,
)

// Per-side port lists, keyed by which switch the user picked. Loading state
// is per-side so picking switch A doesn't grey out side B.
const portsA = ref<Port[]>([])
const portsB = ref<Port[]>([])
const loadingPortsA = ref(false)
const loadingPortsB = ref(false)

// Cached resolved endpoint labels for edit mode (port id → "switch:port#").
// The Link record only carries port_a_id / port_b_id, so we need a small
// roundtrip when the modal opens to display friendly identifiers.
const endpointALabel = ref<string>('')
const endpointBLabel = ref<string>('')

const linkTypeOptions = computed(() => [
  { value: 'copper', label: t('link.types.copper') },
  { value: 'fiber', label: t('link.types.fiber') },
  { value: 'dac', label: t('link.types.dac') },
  { value: 'virtual', label: t('link.types.virtual') },
])

const switchOptions = computed(() => [
  { value: '', label: t('common.choose') },
  ...allSwitches.value.map((s) => ({ value: s.name, label: s.name })),
])

function portOptions(ports: Port[]) {
  return [
    { value: 0, label: t('common.choose') },
    ...ports.map((p) => ({
      value: p.number,
      label: p.label ? `${p.number} — ${p.label}` : `${p.number}`,
    })),
  ]
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    // Reset state on every open so a closed-then-reopened modal never shows
    // stale ports / errors from a previous session.
    Object.assign(form, {
      switch_a: '',
      port_a: null,
      switch_b: '',
      port_b: null,
      link_type: (props.link?.link_type ?? 'copper') as LinkType,
      speed_mbps: props.link?.speed_mbps ?? null,
      description: props.link?.description ?? '',
    })
    errors.switch_a = errors.port_a = errors.switch_b = errors.port_b = errors.speed_mbps = null
    submitError.value = null
    portsA.value = []
    portsB.value = []
    endpointALabel.value = ''
    endpointBLabel.value = ''

    // Make sure we have a switch list — fall back to a local fetch only when
    // the parent didn't pass one in.
    if (!props.switches || props.switches.length === 0) {
      try {
        const res = await switchesApi.list({ page_size: 200 })
        localSwitches.value = res.items
      } catch {
        // Surfaced through the submit-time error anyway.
      }
    }

    if (props.link) {
      // Edit mode: resolve both endpoints once so the user sees "SW-A:24" not
      // "#42". The ports API returns the Port; we then look up its switch via
      // the cached map to render `<switch>:<number>`.
      await resolveEndpointLabels(props.link)
    }
  },
)

async function resolveEndpointLabels(link: Link) {
  try {
    const [pa, pb] = await Promise.all([portsApi.get(link.port_a_id), portsApi.get(link.port_b_id)])
    endpointALabel.value = formatEndpoint(pa)
    endpointBLabel.value = formatEndpoint(pb)
  } catch {
    endpointALabel.value = `#${link.port_a_id}`
    endpointBLabel.value = `#${link.port_b_id}`
  }
}

function formatEndpoint(port: Port): string {
  const sw = allSwitches.value.find((s) => s.id === port.switch_id)
  const swLabel = sw?.name ?? `switch #${port.switch_id}`
  return port.label ? `${swLabel} : ${port.number} (${port.label})` : `${swLabel} : ${port.number}`
}

async function loadPortsForSide(side: 'a' | 'b', switchName: string) {
  const target = side === 'a' ? portsA : portsB
  const loading = side === 'a' ? loadingPortsA : loadingPortsB
  target.value = []
  if (!switchName) return
  const sw = allSwitches.value.find((s) => s.name === switchName)
  if (!sw) return
  loading.value = true
  try {
    const res = await portsApi.listForSwitch(sw.id, { page_size: 200 })
    target.value = res.items
  } catch (err) {
    submitError.value = describe(err)
  } finally {
    loading.value = false
  }
}

watch(
  () => form.switch_a,
  (v) => {
    form.port_a = null
    void loadPortsForSide('a', v)
  },
)
watch(
  () => form.switch_b,
  (v) => {
    form.port_b = null
    void loadPortsForSide('b', v)
  },
)

function validate(): boolean {
  let ok = true
  errors.switch_a = errors.port_a = errors.switch_b = errors.port_b = errors.speed_mbps = null

  if (!isEdit.value) {
    if (!form.switch_a) {
      errors.switch_a = t('common.validation.required')
      ok = false
    }
    if (!form.port_a) {
      errors.port_a = t('common.validation.required')
      ok = false
    }
    if (!form.switch_b) {
      errors.switch_b = t('common.validation.required')
      ok = false
    }
    if (!form.port_b) {
      errors.port_b = t('common.validation.required')
      ok = false
    }
    if (
      form.switch_a &&
      form.switch_b &&
      form.port_a &&
      form.port_b &&
      form.switch_a === form.switch_b &&
      form.port_a === form.port_b
    ) {
      errors.port_b = t('link.errors.samePort')
      ok = false
    }
  }

  if (form.speed_mbps !== null && form.speed_mbps !== undefined && form.speed_mbps <= 0) {
    errors.speed_mbps = t('common.validation.positive')
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
    let saved: Link
    if (props.link) {
      saved = await linksApi.update(props.link.id, {
        link_type: form.link_type,
        speed_mbps: form.speed_mbps,
        description: form.description.trim() || null,
      })
    } else {
      saved = await linksApi.createByName({
        switch_a: form.switch_a,
        port_a: form.port_a!,
        switch_b: form.switch_b,
        port_b: form.port_b!,
        link_type: form.link_type,
        speed_mbps: form.speed_mbps,
        description: form.description.trim() || null,
      })
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
    :title="isEdit ? t('link.edit') : t('link.new')"
    size="lg"
    @close="emit('close')"
  >
    <form class="flex flex-col gap-4" @submit="onSubmit">
      <!-- Endpoints: editable on create, read-only on edit -->
      <template v-if="!isEdit">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <fieldset class="rounded-md border border-border p-3 space-y-3">
            <legend class="text-xs uppercase tracking-wide text-fg-muted px-1">
              {{ t('link.endpointA') }}
            </legend>
            <FormField :label="t('switch.label')" :error="errors.switch_a" required>
              <template #default="{ id, invalid }">
                <Select
                  :id="id"
                  :model-value="form.switch_a"
                  :options="switchOptions"
                  :aria-invalid="invalid"
                  @update:model-value="(v) => (form.switch_a = String(v))"
                />
              </template>
            </FormField>
            <FormField :label="t('port.label')" :error="errors.port_a" required>
              <template #default="{ id, invalid }">
                <Select
                  :id="id"
                  :model-value="form.port_a ?? 0"
                  :options="portOptions(portsA)"
                  :disabled="!form.switch_a || loadingPortsA"
                  :aria-invalid="invalid"
                  @update:model-value="(v) => (form.port_a = Number(v) || null)"
                />
              </template>
            </FormField>
          </fieldset>

          <fieldset class="rounded-md border border-border p-3 space-y-3">
            <legend class="text-xs uppercase tracking-wide text-fg-muted px-1">
              {{ t('link.endpointB') }}
            </legend>
            <FormField :label="t('switch.label')" :error="errors.switch_b" required>
              <template #default="{ id, invalid }">
                <Select
                  :id="id"
                  :model-value="form.switch_b"
                  :options="switchOptions"
                  :aria-invalid="invalid"
                  @update:model-value="(v) => (form.switch_b = String(v))"
                />
              </template>
            </FormField>
            <FormField :label="t('port.label')" :error="errors.port_b" required>
              <template #default="{ id, invalid }">
                <Select
                  :id="id"
                  :model-value="form.port_b ?? 0"
                  :options="portOptions(portsB)"
                  :disabled="!form.switch_b || loadingPortsB"
                  :aria-invalid="invalid"
                  @update:model-value="(v) => (form.port_b = Number(v) || null)"
                />
              </template>
            </FormField>
          </fieldset>
        </div>
      </template>

      <template v-else>
        <!-- Edit mode: endpoints are immutable -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          <div class="rounded-md border border-border p-3 bg-muted/40">
            <p class="text-xs uppercase tracking-wide text-fg-muted">
              {{ t('link.endpointA') }}
            </p>
            <p class="font-mono text-fg mt-1">{{ endpointALabel || '—' }}</p>
          </div>
          <div class="rounded-md border border-border p-3 bg-muted/40">
            <p class="text-xs uppercase tracking-wide text-fg-muted">
              {{ t('link.endpointB') }}
            </p>
            <p class="font-mono text-fg mt-1">{{ endpointBLabel || '—' }}</p>
          </div>
        </div>
        <p class="text-xs text-fg-muted -mt-2">{{ t('link.endpointsImmutableHint') }}</p>
      </template>

      <!-- Shared metadata -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <FormField :label="t('link.fields.type')" required>
          <template #default="{ id }">
            <Select
              :id="id"
              :model-value="form.link_type"
              :options="linkTypeOptions"
              @update:model-value="(v) => (form.link_type = v as LinkType)"
            />
          </template>
        </FormField>
        <FormField :label="t('link.fields.speed')" :error="errors.speed_mbps">
          <template #default="{ id, invalid }">
            <Input
              :id="id"
              v-model.number="form.speed_mbps"
              type="number"
              min="1"
              :invalid="invalid"
              placeholder="1000"
              autocomplete="off"
            />
          </template>
        </FormField>
      </div>

      <FormField :label="t('link.fields.description')">
        <template #default="{ id }">
          <Textarea :id="id" v-model="form.description" :rows="2" placeholder="" />
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

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Pencil } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Spinner from '@/components/ui/Spinner.vue'
import SwitchRackView from '@/components/SwitchRackView.vue'
import PortTable from '@/components/PortTable.vue'
import SwitchEditor from '@/components/editors/SwitchEditor.vue'
import PortEditor from '@/components/editors/PortEditor.vue'
import { portsApi, switchesApi, vlansApi } from '@/api'
import type { Port, Switch, Vlan } from '@/api'
import { useAuth } from '@/composables/useAuth'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { isAdmin } = useAuth()
const { describe } = useApiErrorMessage()

const sw = ref<Switch | null>(null)
const ports = ref<Port[]>([])
const vlansById = ref<Map<number, Vlan>>(new Map())
const loading = ref(true)
const editingSwitch = ref(false)
const editingPort = ref<Port | null>(null)
const tab = ref<'rack' | 'table'>('rack')

const id = computed(() => Number(route.params.id))

async function loadAll() {
  loading.value = true
  try {
    const [s, p, v] = await Promise.all([
      switchesApi.get(id.value),
      // page_size=200 fits any single-chassis switch; v1 doesn't model stacked
      // > 200-port frames. Phase 7+ can paginate the table view if needed.
      portsApi.listForSwitch(id.value, { page_size: 200 }),
      vlansApi.list({ page_size: 200 }),
    ])
    sw.value = s
    ports.value = p.items
    vlansById.value = new Map(v.items.map((vl) => [vl.id, vl]))
  } catch (err) {
    void describe(err)
    router.replace('/switches')
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
watch(id, loadAll)

const portStats = computed(() => {
  const used = ports.value.filter(
    (p) =>
      p.admin_status === 'up' &&
      p.mode !== 'disabled' &&
      (p.connected_device_id || p.connected_ip_id),
  ).length
  return { used, total: ports.value.length }
})

function onPortSelect(p: Port) {
  if (!isAdmin.value) return
  editingPort.value = p
}
function onPortSaved(p: Port) {
  const i = ports.value.findIndex((x) => x.id === p.id)
  if (i !== -1) ports.value[i] = p
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <button
      type="button"
      class="inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg mb-4 transition"
      @click="router.push('/switches')"
    >
      <ArrowLeft class="w-4 h-4" aria-hidden="true" />
      {{ t('switch.labelPlural') }}
    </button>

    <div v-if="loading && !sw" class="flex items-center justify-center py-12">
      <Spinner :label="t('common.loading')" />
    </div>

    <template v-else-if="sw">
      <PageHeader :title="sw.name" :subtitle="sw.description ?? undefined">
        <template #actions>
          <Button v-if="isAdmin" variant="primary" @click="editingSwitch = true">
            <Pencil class="w-4 h-4" aria-hidden="true" />
            {{ t('common.edit') }}
          </Button>
        </template>
      </PageHeader>

      <section class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div class="nf-card p-4">
          <p class="text-[10px] uppercase tracking-wide text-fg-muted">
            {{ t('switch.fields.managementIp') }}
          </p>
          <p class="mt-1 font-mono text-sm">{{ sw.management_ip || '—' }}</p>
        </div>
        <div class="nf-card p-4">
          <p class="text-[10px] uppercase tracking-wide text-fg-muted">
            {{ t('switch.fields.vendor') }} / {{ t('switch.fields.model') }}
          </p>
          <p class="mt-1 text-sm">
            {{ sw.vendor || '—' }}
            <span v-if="sw.model">· {{ sw.model }}</span>
          </p>
        </div>
        <div class="nf-card p-4">
          <p class="text-[10px] uppercase tracking-wide text-fg-muted">
            {{ t('switch.fields.firmware') }}
          </p>
          <p class="mt-1 text-sm">{{ sw.firmware_version || '—' }}</p>
        </div>
        <div class="nf-card p-4">
          <p class="text-[10px] uppercase tracking-wide text-fg-muted">
            {{ t('switch.ports') }}
          </p>
          <p class="mt-1 text-sm">
            {{ t('switch.portStats', { used: portStats.used, total: portStats.total }) }}
          </p>
        </div>
      </section>

      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold">{{ t('switch.ports') }}</h2>
        <div
          class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface"
          role="group"
        >
          <button
            type="button"
            :aria-pressed="tab === 'rack'"
            :class="[
              'flex items-center gap-1.5 px-2 h-7 rounded text-xs font-medium transition',
              tab === 'rack'
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-100/30 dark:text-primary-50'
                : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
            ]"
            @click="tab = 'rack'"
          >
            {{ t('switch.rackView') }}
          </button>
          <button
            type="button"
            :aria-pressed="tab === 'table'"
            :class="[
              'flex items-center gap-1.5 px-2 h-7 rounded text-xs font-medium transition',
              tab === 'table'
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-100/30 dark:text-primary-50'
                : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
            ]"
            @click="tab = 'table'"
          >
            {{ t('subnet.viewTable') }}
          </button>
        </div>
      </div>

      <SwitchRackView
        v-if="tab === 'rack'"
        :ports="ports"
        :vlans="vlansById"
        @select="onPortSelect"
      />
      <PortTable
        v-else
        :ports="ports"
        :vlans="vlansById"
        :loading="loading"
        @select="onPortSelect"
      />

      <SwitchEditor
        :open="editingSwitch"
        :switch-item="sw"
        @close="editingSwitch = false"
        @saved="loadAll"
      />
      <PortEditor
        :open="!!editingPort"
        :port="editingPort"
        @close="editingPort = null"
        @saved="onPortSaved"
      />
    </template>
  </div>
</template>

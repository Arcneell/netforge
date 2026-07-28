<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Pencil, Server, Table as TableIcon } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Breadcrumb from '@/components/Breadcrumb.vue'
import Button from '@/components/ui/Button.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import Segmented, { type SegmentedOption } from '@/components/ui/Segmented.vue'
import SubnetFillBar from '@/components/SubnetFillBar.vue'
import SwitchRackView from '@/components/SwitchRackView.vue'
import PortTable from '@/components/PortTable.vue'
import { fetchAllPages, portsApi, switchesApi, vlansApi } from '@/api'
import type { Port, Switch, Vlan } from '@/api'
import { useAuth } from '@/composables/useAuth'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useStoredRef } from '@/composables/useStoredRef'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { isAdmin } = useAuth()
const { notify } = useApiErrorMessage()

const sw = ref<Switch | null>(null)
const ports = ref<Port[]>([])
const vlansById = ref<Map<number, Vlan>>(new Map())
const loading = ref(true)
// Persist tab choice so flipping between switches keeps the view the user
// was on. Stored once per app — admins typically pick rack OR table as
// their preferred lens and stay there.
const tab = useStoredRef<'rack' | 'table'>('netforge.switch.tab', 'rack')

const id = computed(() => Number(route.params.id))

// Sequence guard — `watch(id, loadAll)` re-fires on every adjacent
// /switches/:id navigation. Without the token, a slow first response
// can land after the fresh one and overwrite the visible data with the
// previous switch's payload. Mirrors SubnetDetailView.
let detailLoadSeq = 0

async function loadAll() {
  const seq = ++detailLoadSeq
  loading.value = true
  try {
    const [s, p, v] = await Promise.all([
      switchesApi.get(id.value),
      // `fetchAllPages` walks past the server's 200-row page cap, so even a
      // stacked > 200-port frame or a large VLAN plan loads completely.
      fetchAllPages((params) => portsApi.listForSwitch(id.value, params)),
      fetchAllPages((params) => vlansApi.list(params)),
    ])
    if (seq !== detailLoadSeq) return
    sw.value = s
    ports.value = p
    vlansById.value = new Map(v.map((vl) => [vl.id, vl]))
  } catch (err) {
    if (seq !== detailLoadSeq) return
    notify(err)
    router.replace('/switches')
  } finally {
    if (seq === detailLoadSeq) loading.value = false
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

// Rack / table switch — the shared segmented control, same as the subnet page.
const tabOptions = computed<SegmentedOption<'rack' | 'table'>[]>(() => [
  { value: 'rack', label: t('switch.rackView'), icon: Server },
  { value: 'table', label: t('subnet.viewTable'), icon: TableIcon },
])

// Editing a port is a full page of its own, nested under this switch. Coming
// back re-mounts this view, so `loadAll()` refreshes the row — no in-place
// patch needed any more.
function onPortSelect(p: Port) {
  if (!isAdmin.value) return
  router.push({ name: 'port-edit', params: { switchId: id.value, id: p.id } })
}

function onEditSwitch() {
  // `from` sends the user back here after saving rather than to the list.
  router.push({ name: 'switch-edit', params: { id: id.value }, query: { from: route.fullPath } })
}
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <div v-if="loading && !sw" aria-busy="true">
      <div class="mb-3">
        <Skeleton width="14rem" height="0.75rem" />
      </div>
      <div class="mb-8">
        <Skeleton width="18rem" height="1.75rem" rounded="md" />
        <div class="mt-2">
          <Skeleton width="24rem" height="0.875rem" />
        </div>
      </div>
      <!-- Mirrors the identity block below: one card, four hairline-separated cells. -->
      <section class="nf-card overflow-hidden mb-6">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-border">
          <div v-for="i in 4" :key="`sk-meta-${i}`" class="bg-surface px-5 py-4">
            <Skeleton width="5rem" height="0.625rem" />
            <div class="mt-2.5">
              <Skeleton width="80%" height="0.875rem" />
            </div>
          </div>
        </div>
      </section>
      <div class="nf-card p-6">
        <Skeleton width="100%" height="14rem" rounded="md" />
      </div>
    </div>

    <template v-else-if="sw">
      <Breadcrumb
        :items="[{ label: t('switch.labelPlural'), to: { name: 'switches' } }, { label: sw.name }]"
      />
      <PageHeader :title="sw.name" :subtitle="sw.description ?? undefined">
        <template #actions>
          <Button v-if="isAdmin" variant="primary" @click="onEditSwitch">
            <Pencil class="w-4 h-4" aria-hidden="true" />
            {{ t('common.edit') }}
          </Button>
        </template>
      </PageHeader>

      <!-- Identity. One card, hairline-separated cells: the page opens with
           what this switch *is* rather than four disconnected boxes. The
           `gap-px` over a `bg-border` container draws the dividers, so they
           land correctly at every breakpoint without per-cell border rules. -->
      <section class="nf-card overflow-hidden mb-8">
        <dl class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-border">
          <div class="bg-surface px-5 py-4 min-w-0">
            <dt class="nf-label">{{ t('switch.fields.managementIp') }}</dt>
            <dd class="mt-2 font-mono text-base text-fg truncate">
              {{ sw.management_ip || '—' }}
            </dd>
          </div>
          <div class="bg-surface px-5 py-4 min-w-0">
            <dt class="nf-label">
              {{ t('switch.fields.vendor') }} / {{ t('switch.fields.model') }}
            </dt>
            <dd class="mt-2 text-base text-fg truncate">
              <template v-if="sw.vendor || sw.model">
                {{ sw.vendor || '—' }}
                <span v-if="sw.model" class="text-fg-muted">· {{ sw.model }}</span>
              </template>
              <span v-else class="text-fg-subtle">—</span>
            </dd>
          </div>
          <div class="bg-surface px-5 py-4 min-w-0">
            <dt class="nf-label">{{ t('switch.fields.firmware') }}</dt>
            <dd class="mt-2 text-base text-fg truncate">
              <span v-if="sw.firmware_version" class="font-mono">{{ sw.firmware_version }}</span>
              <span v-else class="text-fg-subtle">—</span>
            </dd>
          </div>
          <div class="bg-surface px-5 py-4 min-w-0">
            <dt class="nf-label">{{ t('switch.ports') }}</dt>
            <!-- Same fill bar the subnets use — a capacity ratio reads the
                 same way whether it counts addresses or ports. -->
            <dd class="mt-2">
              <SubnetFillBar
                :used="portStats.used"
                :usable="portStats.total"
                variant="block"
                :title="t('switch.portStats', { used: portStats.used, total: portStats.total })"
              />
            </dd>
          </div>
        </dl>
      </section>

      <!-- Ports. Heading on the left, controls on the right — same shape as
           the list pages and the subnet detail page. -->
      <section>
        <div class="nf-toolbar justify-between">
          <div class="flex items-baseline gap-2 min-w-0">
            <h2 class="nf-section-title">{{ t('switch.ports') }}</h2>
            <span class="text-sm text-fg-subtle tabular-nums">{{ portStats.total }}</span>
          </div>
          <Segmented v-model="tab" :options="tabOptions" :aria-label="t('switch.ports')" />
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
      </section>
    </template>
  </div>
</template>

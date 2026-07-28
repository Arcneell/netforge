<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2 } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { vlansApi } from '@/api'
import type { Vlan } from '@/api'
import { useApi } from '@/composables/useApi'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const router = useRouter()
const { t } = useI18n()
const { isAdmin } = useAuth()
const { success } = useToast()
const { notify } = useApiErrorMessage()
// Reserved for future filter-aware fetches; useApi keeps toast wiring centralised.
useApi()

const items = ref<Vlan[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

const deleteTarget = ref<Vlan | null>(null)
const deleting = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await vlansApi.list({ page: page.value, page_size: pageSize })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

onMounted(load)

// Create and edit are their own pages now; the list only navigates.
function onNew() {
  router.push({ name: 'vlan-new' })
}

function onEdit(vlan: Vlan) {
  router.push({ name: 'vlan-edit', params: { id: vlan.id } })
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await vlansApi.delete(deleteTarget.value.id)
    success(t('common.success'))
    deleteTarget.value = null
    load()
  } catch (err) {
    // The axios interceptor only calls back on network failures, 401 and 403,
    // so a 409 here would otherwise reach the user as nothing at all.
    notify(err)
  } finally {
    deleting.value = false
  }
}

// Wrap in computed so column labels follow the i18n locale.
const columns = computed<DataTableColumn[]>(() => [
  { key: 'vlan_id', label: t('vlan.fields.vlanId'), cellClass: 'w-32 font-mono' },
  { key: 'name', label: t('vlan.fields.name') },
  { key: 'description', label: t('vlan.fields.description'), hideOnSm: true },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
])
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('vlan.labelPlural')" :subtitle="t('vlan.subtitle')">
      <template #help>
        <HelpTooltip :text="t('vlan.help.vlanId')" placement="bottom" />
      </template>
      <template #actions>
        <Button v-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('vlan.new') }}
        </Button>
      </template>
    </PageHeader>

    <!-- Same toolbar slot as the other list pages. `/vlans` has no
         server-side search or filter params yet, so the bar carries only
         the honest result count — client-side filtering of a single
         paginated page would lie about what's actually there. -->
    <div class="nf-toolbar">
      <span class="ml-auto text-sm text-fg-muted tabular-nums whitespace-nowrap" aria-live="polite">
        {{ t('common.resultCount', total) }}
      </span>
    </div>

    <DataTable
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="t('common.empty.title')"
      :empty-description="t('vlan.empty')"
    >
      <template v-if="isAdmin" #empty-action>
        <Button variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('vlan.new') }}
        </Button>
      </template>
      <template #cell-vlan_id="{ row }">
        <VlanBadge :vlan="row" compact />
      </template>
      <template #cell-name="{ row }">
        <span class="font-medium text-fg">{{ row.name }}</span>
      </template>
      <template #cell-description="{ row }">
        <span class="text-fg-muted">{{ row.description || '—' }}</span>
      </template>
      <template #cell-actions="{ row }">
        <div class="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('common.edit')"
            :disabled="!isAdmin"
            @click.stop="onEdit(row)"
          >
            <Pencil class="w-4 h-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('common.delete')"
            :disabled="!isAdmin"
            @click.stop="deleteTarget = row"
          >
            <Trash2 class="w-4 h-4 text-danger" aria-hidden="true" />
          </Button>
        </div>
      </template>
      <template #footer>
        <Pagination
          v-if="total > pageSize"
          :page="page"
          :page-size="pageSize"
          :total="total"
          @update:page="
            (p) => {
              page = p
              load()
            }
          "
        />
      </template>
    </DataTable>

    <ConfirmDialog
      :open="!!deleteTarget"
      :title="t('common.confirmDelete.title', { label: deleteTarget?.name ?? '' })"
      :message="t('common.confirmDelete.message')"
      variant="danger"
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Badge from '@/components/ui/Badge.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import type { Port, Vlan } from '@/api'

const props = defineProps<{
  ports: Port[]
  vlans: Map<number, Vlan>
  loading?: boolean
}>()

defineEmits<{ (e: 'select', port: Port): void }>()

const { t } = useI18n()

const columns = computed<DataTableColumn[]>(() => [
  { key: 'number', label: t('port.fields.number'), cellClass: 'w-12 font-mono' },
  { key: 'label', label: t('port.fields.label') },
  { key: 'mode', label: t('port.fields.mode'), cellClass: 'w-24' },
  { key: 'native_vlan_id', label: t('port.fields.nativeVlan'), cellClass: 'w-40' },
  { key: 'admin_status', label: t('port.fields.adminStatus'), cellClass: 'w-24' },
  { key: 'notes', label: t('port.fields.notes'), hideOnSm: true },
])

const modeBadge: Record<string, 'primary' | 'neutral' | 'warning' | 'muted'> = {
  access: 'neutral',
  trunk: 'primary',
  hybrid: 'warning',
  disabled: 'muted',
}
</script>

<template>
  <DataTable
    :columns="columns"
    :rows="ports"
    :loading="loading"
    :empty-title="t('port.labelPlural')"
    clickable
    @row-click="(p) => $emit('select', p)"
  >
    <template #cell-label="{ row }">
      <span class="text-fg-muted">{{ row.label || '—' }}</span>
    </template>
    <template #cell-mode="{ row }">
      <Badge :tone="modeBadge[row.mode] ?? 'neutral'">
        {{ t(`port.modes.${row.mode}`) }}
      </Badge>
    </template>
    <template #cell-native_vlan_id="{ row }">
      <VlanBadge
        v-if="row.native_vlan_id && props.vlans.get(row.native_vlan_id)"
        :vlan="props.vlans.get(row.native_vlan_id)!"
      />
      <span v-else class="text-fg-muted">—</span>
    </template>
    <template #cell-admin_status="{ row }">
      <Badge :tone="row.admin_status === 'up' ? 'success' : 'muted'">
        {{ t(`port.adminStatus.${row.admin_status}`) }}
      </Badge>
    </template>
    <template #cell-notes="{ row }">
      <span class="text-fg-muted truncate">{{ row.notes || '—' }}</span>
    </template>
  </DataTable>
</template>

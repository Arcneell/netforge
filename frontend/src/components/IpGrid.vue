<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SubnetIpEntry } from '@/api'

const props = defineProps<{
  ips: SubnetIpEntry[]
}>()

defineEmits<{ (e: 'select', entry: SubnetIpEntry): void }>()

const { t } = useI18n()

type StatusKey = 'assigned' | 'reserved' | 'dhcp' | 'free'

const statusClass: Record<StatusKey, string> = {
  assigned: 'bg-primary-500 hover:bg-primary-600 text-white border-primary-600',
  reserved: 'bg-warning/90 hover:bg-warning text-white border-warning',
  dhcp: 'bg-success/80 hover:bg-success text-white border-success',
  free: 'bg-surface hover:bg-surface-hover text-fg-muted border-border',
}

const statusLabel = computed<Record<StatusKey, string>>(() => ({
  assigned: t('ip.status.assigned'),
  reserved: t('ip.status.reserved'),
  dhcp: t('ip.status.dhcp'),
  free: t('ip.status.free'),
}))

function keyFor(status: string): StatusKey {
  return (status in statusClass ? status : 'free') as StatusKey
}

// Backend already returns a stable order, but we don't trust it — paginate-style
// rendering relies on the array index matching the offset in the block.
const sorted = computed(() => props.ips)
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3 mb-3 text-xs text-fg-muted">
      <span
        v-for="status in ['assigned', 'reserved', 'dhcp', 'free'] as const"
        :key="status"
        class="flex items-center gap-1.5"
      >
        <span
          :class="['inline-block w-3 h-3 rounded-sm', statusClass[status]]"
          aria-hidden="true"
        />
        {{ statusLabel[status] }}
      </span>
    </div>
    <div
      class="grid gap-1"
      style="grid-template-columns: repeat(auto-fill, minmax(2.25rem, 1fr))"
      role="grid"
      :aria-label="t('subnet.viewGrid')"
    >
      <button
        v-for="entry in sorted"
        :key="entry.address"
        type="button"
        :class="[
          'group relative h-9 text-[10px] font-mono rounded border transition flex items-center justify-center px-1 truncate',
          statusClass[keyFor(entry.status)],
        ]"
        :title="`${entry.address} · ${statusLabel[keyFor(entry.status)]}${entry.hostname ? ' · ' + entry.hostname : ''}`"
        :aria-label="`${entry.address} ${entry.status}`"
        @click="$emit('select', entry)"
      >
        <!-- Show last octet for compactness; full address surfaces in the tooltip. -->
        <span>{{ entry.address.split('.').pop() }}</span>
      </button>
    </div>
  </div>
</template>

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

// Cell classes (used on the clickable IP buttons in the grid). They share
// the `bg-*` token with the legend so the swatch under each label matches
// what an IP of that status looks like on the grid.
const statusClass: Record<StatusKey, string> = {
  assigned: 'bg-primary-500 hover:bg-primary-600 text-white border-primary-600',
  reserved: 'bg-warning/90 hover:bg-warning text-white border-warning',
  dhcp: 'bg-success/80 hover:bg-success text-white border-success',
  // Free cells: muted fill on a slightly darker border so the empty
  // addresses stay distinguishable from the white card background in
  // light mode and from the elevated surface in dark mode.
  free: 'bg-muted/60 hover:bg-surface-hover text-fg-muted border-border',
}

// Legend swatches — same fill as the cell, plus an explicit 1-px border so
// every chip stays visible against `bg-surface` (the card it sits on). The
// cells themselves already get `border` via the button class, but the
// legend swatch is a plain `<span>` and would otherwise be borderless.
const legendSwatchClass: Record<StatusKey, string> = {
  assigned: 'bg-primary-500 border border-primary-600',
  reserved: 'bg-warning border border-warning',
  dhcp: 'bg-success border border-success',
  free: 'bg-muted/60 border border-border',
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
    <div class="flex flex-wrap items-center gap-4 mb-3 text-xs text-fg-muted">
      <span
        v-for="status in ['assigned', 'reserved', 'dhcp', 'free'] as const"
        :key="status"
        class="inline-flex items-center gap-1.5"
      >
        <span
          :class="['inline-block w-3.5 h-3.5 rounded-sm flex-shrink-0', legendSwatchClass[status]]"
          aria-hidden="true"
        />
        <span>{{ statusLabel[status] }}</span>
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

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Port, Vlan } from '@/api'

const props = defineProps<{
  ports: Port[]
  vlans: Map<number, Vlan>
}>()

defineEmits<{ (e: 'select', port: Port): void }>()

const { t } = useI18n()

// Stable order by port number. Backend should already be ordered but we don't
// depend on it — RackView's whole point is a visual map keyed off the index.
const ordered = computed(() => [...props.ports].sort((a, b) => a.number - b.number))

function colorFor(port: Port): string | null {
  if (port.admin_status === 'down' || port.mode === 'disabled') return null
  if (!port.native_vlan_id) return null
  return props.vlans.get(port.native_vlan_id)?.color ?? null
}

function statusClass(port: Port): string {
  if (port.admin_status === 'down') return 'bg-muted text-fg-muted border-border'
  if (port.mode === 'disabled') return 'bg-muted text-fg-muted border-border'
  if (port.connected_device_id || port.connected_ip_id)
    return 'bg-primary-500 text-white border-primary-600'
  return 'bg-surface text-fg border-border hover:bg-surface-hover'
}
</script>

<template>
  <div>
    <div
      class="grid gap-1 p-3 bg-bg/60 rounded-md border border-border"
      style="grid-template-columns: repeat(auto-fill, minmax(2.5rem, 1fr))"
      role="grid"
      :aria-label="t('switch.rackView')"
    >
      <button
        v-for="port in ordered"
        :key="port.id"
        type="button"
        :class="[
          'h-10 rounded border text-xs font-mono flex flex-col items-center justify-center transition relative',
          statusClass(port),
        ]"
        :style="
          colorFor(port)
            ? {
                borderColor: colorFor(port) as string,
                boxShadow: `inset 0 -3px 0 ${colorFor(port)}`,
              }
            : undefined
        "
        :title="`#${port.number}${port.label ? ' · ' + port.label : ''}`"
        :aria-label="`${t('port.label')} ${port.number}`"
        @click="$emit('select', port)"
      >
        <span class="font-semibold">{{ port.number }}</span>
      </button>
    </div>
  </div>
</template>

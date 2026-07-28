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

type PortState = 'connected' | 'free' | 'disabled'

function stateOf(port: Port): PortState {
  if (port.admin_status === 'down' || port.mode === 'disabled') return 'disabled'
  if (port.connected_device_id || port.connected_ip_id) return 'connected'
  return 'free'
}

function colorFor(port: Port): string | null {
  if (stateOf(port) === 'disabled') return null
  if (!port.native_vlan_id) return null
  return props.vlans.get(port.native_vlan_id)?.color ?? null
}

// Three states, told by fill weight: solid means something is plugged in,
// outlined means the port is up and free, flat grey means it's switched off.
const stateClass: Record<PortState, string> = {
  connected: 'bg-primary-600 text-white border-transparent hover:bg-primary-500',
  free: 'bg-surface text-fg-muted border-border-strong hover:bg-surface-hover hover:text-fg',
  disabled: 'bg-muted text-fg-subtle border-transparent cursor-default',
}

// Legend swatches mirror the cell treatment so the key reads as a sample of
// the rack rather than a second colour scheme.
const legendSwatchClass: Record<PortState, string> = {
  connected: 'bg-primary-600 border-transparent',
  free: 'bg-surface border-border-strong',
  disabled: 'bg-muted border-transparent',
}

// Existing vocabulary only: "Connected device" / "Up" / "Disabled". The state
// is repeated in every cell's title and aria-label so the rack never depends
// on colour alone.
const stateLabel = computed<Record<PortState, string>>(() => ({
  connected: t('port.fields.connectedDevice'),
  free: t('port.adminStatus.up'),
  disabled: t('port.modes.disabled'),
}))

const stateCounts = computed<Record<PortState, number>>(() => {
  const out: Record<PortState, number> = { connected: 0, free: 0, disabled: 0 }
  for (const port of props.ports) out[stateOf(port)] += 1
  return out
})

const STATES = ['connected', 'free', 'disabled'] as const

function titleFor(port: Port): string {
  const parts = [`#${port.number}`, stateLabel.value[stateOf(port)]]
  if (port.label) parts.splice(1, 0, port.label)
  const vlan = port.native_vlan_id ? props.vlans.get(port.native_vlan_id) : null
  if (vlan) parts.push(`${t('port.fields.nativeVlan')} ${vlan.vlan_id}`)
  return parts.join(' · ')
}
</script>

<template>
  <div class="nf-card p-4 sm:p-5">
    <div class="flex flex-wrap items-center gap-x-5 gap-y-2 pb-3 mb-4 border-b border-border">
      <span v-for="state in STATES" :key="state" class="inline-flex items-center gap-2">
        <span
          :class="['inline-block w-3 h-3 rounded border flex-shrink-0', legendSwatchClass[state]]"
          aria-hidden="true"
        />
        <span class="nf-label">{{ stateLabel[state] }}</span>
        <span class="text-xs text-fg-subtle tabular-nums">{{ stateCounts[state] }}</span>
      </span>
    </div>

    <div
      class="grid gap-1.5"
      style="grid-template-columns: repeat(auto-fill, minmax(2.5rem, 1fr))"
      role="grid"
      :aria-label="t('switch.rackView')"
    >
      <button
        v-for="port in ordered"
        :key="port.id"
        type="button"
        :class="[
          'h-10 rounded-md border flex flex-col items-center justify-center',
          'font-mono text-xs tabular-nums font-semibold',
          'transition-colors duration-150 ease-soft',
          stateClass[stateOf(port)],
        ]"
        :style="colorFor(port) ? { boxShadow: `inset 0 -3px 0 ${colorFor(port)}` } : undefined"
        :title="titleFor(port)"
        :aria-label="`${t('port.label')} ${port.number} · ${stateLabel[stateOf(port)]}`"
        @click="$emit('select', port)"
      >
        {{ port.number }}
      </button>
    </div>
  </div>
</template>

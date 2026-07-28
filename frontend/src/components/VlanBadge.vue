<script setup lang="ts">
import Badge from '@/components/ui/Badge.vue'
import type { Vlan } from '@/api'

/**
 * A VLAN rendered as a pill. Deliberately a thin wrapper over `Badge` — all
 * the geometry, tone and colour handling lives there, including the inline
 * per-VLAN colour, which is the one place a value from the database is
 * allowed to drive the palette.
 */
const props = defineProps<{
  vlan: Pick<Vlan, 'vlan_id' | 'name' | 'color'>
  /** Drop the textual name and only show the VLAN number, for tight cells. */
  compact?: boolean
}>()
</script>

<template>
  <Badge
    :color="props.vlan.color ?? null"
    monospace
    :title="`${props.vlan.vlan_id} — ${props.vlan.name}`"
  >
    <span class="tabular-nums">{{ props.vlan.vlan_id }}</span>
    <template v-if="!compact">
      <span class="opacity-50" aria-hidden="true">·</span>
      <span class="font-sans font-medium truncate max-w-[10rem]">{{ props.vlan.name }}</span>
    </template>
  </Badge>
</template>

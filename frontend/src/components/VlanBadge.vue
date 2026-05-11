<script setup lang="ts">
import Badge from '@/components/ui/Badge.vue'
import type { Vlan } from '@/api'

const props = defineProps<{
  vlan: Pick<Vlan, 'vlan_id' | 'name' | 'color'>
  /** Drop the textual name and only show the VLAN number, for tight cells. */
  compact?: boolean
}>()
</script>

<template>
  <Badge :color="props.vlan.color ?? null" monospace>
    <span>{{ props.vlan.vlan_id }}</span>
    <span v-if="!compact" class="opacity-80">·</span>
    <span v-if="!compact" class="font-sans font-medium truncate max-w-[10rem]">
      {{ props.vlan.name }}
    </span>
  </Badge>
</template>

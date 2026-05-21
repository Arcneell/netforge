<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, ChevronRight, Network } from 'lucide-vue-next'
import VlanBadge from '@/components/VlanBadge.vue'
import type { SubnetTreeNode } from '@/api/endpoints/subnets'
import type { Vlan } from '@/api'

/**
 * One row in the subnet hierarchy tree. Recursive: each node renders
 * itself + its children indented one level deeper. The parent passes the
 * shared `collapsed` Set so toggle state survives across re-renders, and
 * a `vlansById` map so we can render the VLAN badge without an extra
 * fetch per row.
 *
 * Visual treatment: every depth level reserves a 1.25-rem column with a
 * dashed vertical guide line so the hierarchy reads as a tree at a
 * glance — without that the indentation alone looks like an indented
 * list. The right-hand side shows VLAN, gateway and a compact fill-rate
 * bar so the tree carries the same useful signal as the flat list view.
 */
const props = defineProps<{
  node: SubnetTreeNode
  collapsed: Set<number>
  depth: number
  vlansById: Map<number, Vlan>
}>()

const emit = defineEmits<{
  (e: 'toggle', id: number): void
  (e: 'open', id: number): void
}>()

const hasChildren = computed(() => props.node.children.length > 0)
const isCollapsed = computed(() => props.collapsed.has(props.node.id))

const vlan = computed<Vlan | null>(() =>
  props.node.vlan_id ? (props.vlansById.get(props.node.vlan_id) ?? null) : null,
)

const fillRatio = computed(() => {
  if (!props.node.usable) return 0
  return Math.min(1, props.node.used / props.node.usable)
})

const fillPercent = computed(() => Math.round(fillRatio.value * 100))

const fillBarClass = computed(() => {
  // Match the colour ramp used in the dashboard: green under 50, amber
  // 50–80, red beyond. Mirrors how operators tend to triage subnet capacity.
  if (fillRatio.value >= 0.8) return 'bg-danger'
  if (fillRatio.value >= 0.5) return 'bg-warning'
  return 'bg-success'
})
</script>

<template>
  <li>
    <div
      class="group flex items-stretch hover:bg-surface-hover cursor-pointer transition-colors"
      @click="emit('open', node.id)"
    >
      <!-- Tree guide lines — one slim column per depth level. The dashed
           left border draws a vertical "stem" that visually ties siblings
           together; siblings at the same depth share the same column. -->
      <span
        v-for="i in depth"
        :key="i"
        class="w-5 border-l border-dashed border-border/70 flex-shrink-0"
        aria-hidden="true"
      />

      <div class="flex-1 flex items-center gap-2 px-2 py-2 min-w-0">
        <button
          v-if="hasChildren"
          type="button"
          class="w-5 h-5 flex items-center justify-center rounded hover:bg-surface text-fg-muted flex-shrink-0"
          :aria-label="isCollapsed ? 'Expand' : 'Collapse'"
          :aria-expanded="!isCollapsed"
          @click.stop="emit('toggle', node.id)"
        >
          <ChevronRight v-if="isCollapsed" class="w-3.5 h-3.5" />
          <ChevronDown v-else class="w-3.5 h-3.5" />
        </button>
        <span
          v-else
          class="w-5 h-5 inline-flex items-center justify-center text-fg-muted flex-shrink-0"
        >
          <Network class="w-3 h-3" aria-hidden="true" />
        </span>

        <span class="font-mono text-sm font-medium truncate">{{ node.cidr }}</span>

        <VlanBadge v-if="vlan" :vlan="vlan" class="flex-shrink-0" />

        <span v-if="node.gateway" class="text-xs text-fg-muted font-mono hidden md:inline">
          → {{ node.gateway }}
        </span>

        <span v-if="node.description" class="text-xs text-fg-muted truncate hidden lg:inline">
          — {{ node.description }}
        </span>

        <!-- Right-aligned meta: fill rate + children count -->
        <span class="ml-auto flex items-center gap-3 flex-shrink-0">
          <span
            v-if="node.usable > 0"
            class="hidden sm:inline-flex items-center gap-1.5 text-[11px] text-fg-muted tabular-nums"
            :title="`${node.used} / ${node.usable}`"
          >
            <span class="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
              <span
                :class="['block h-full transition-all', fillBarClass]"
                :style="{ width: `${fillRatio * 100}%` }"
              />
            </span>
            <span class="w-9 text-right">{{ fillPercent }}%</span>
          </span>
          <span
            v-if="hasChildren"
            class="text-[11px] text-fg-muted tabular-nums px-1.5 rounded bg-muted"
            :title="`${node.children.length} child subnet(s)`"
          >
            {{ node.children.length }}
          </span>
        </span>
      </div>
    </div>
    <ul v-if="hasChildren && !isCollapsed">
      <SubnetTreeRow
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :collapsed="collapsed"
        :depth="depth + 1"
        :vlans-by-id="vlansById"
        @toggle="(id) => emit('toggle', id)"
        @open="(id) => emit('open', id)"
      />
    </ul>
  </li>
</template>

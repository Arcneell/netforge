<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, ChevronRight, Network } from 'lucide-vue-next'
import type { SubnetTreeNode } from '@/api/endpoints/subnets'

/**
 * One row in the subnet hierarchy tree. Recursive: each node renders
 * itself + its children indented one level deeper. The parent passes the
 * shared `collapsed` Set so toggle state survives across re-renders.
 */
const props = defineProps<{
  node: SubnetTreeNode
  collapsed: Set<number>
  depth: number
}>()

const emit = defineEmits<{
  (e: 'toggle', id: number): void
  (e: 'open', id: number): void
}>()

const hasChildren = computed(() => props.node.children.length > 0)
const isCollapsed = computed(() => props.collapsed.has(props.node.id))

// 16px per depth level — keeps deep trees readable without runaway indent.
const indent = computed(() => `${props.depth * 16}px`)
</script>

<template>
  <li>
    <div
      class="flex items-center gap-2 px-3 py-2 hover:bg-surface-hover cursor-pointer"
      :style="{ paddingLeft: `calc(0.75rem + ${indent})` }"
      @click="emit('open', node.id)"
    >
      <button
        v-if="hasChildren"
        type="button"
        class="w-5 h-5 flex items-center justify-center rounded hover:bg-surface text-fg-muted"
        :aria-label="isCollapsed ? 'Expand' : 'Collapse'"
        @click.stop="emit('toggle', node.id)"
      >
        <ChevronRight v-if="isCollapsed" class="w-3.5 h-3.5" />
        <ChevronDown v-else class="w-3.5 h-3.5" />
      </button>
      <span v-else class="w-5 h-5 inline-flex items-center justify-center text-fg-muted">
        <Network class="w-3 h-3" aria-hidden="true" />
      </span>
      <span class="font-mono text-sm font-medium">{{ node.cidr }}</span>
      <span v-if="node.description" class="text-xs text-fg-muted truncate">
        — {{ node.description }}
      </span>
      <span v-if="hasChildren" class="ml-auto text-[11px] text-fg-muted tabular-nums">
        {{ node.children.length }}
      </span>
    </div>
    <ul v-if="hasChildren && !isCollapsed" class="divide-y divide-border/30">
      <SubnetTreeRow
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :collapsed="collapsed"
        :depth="depth + 1"
        @toggle="(id) => emit('toggle', id)"
        @open="(id) => emit('open', id)"
      />
    </ul>
  </li>
</template>

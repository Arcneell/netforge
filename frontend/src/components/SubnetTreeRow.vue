<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, ChevronRight, Network } from 'lucide-vue-next'
import VlanBadge from '@/components/VlanBadge.vue'
import SubnetFillBar from '@/components/SubnetFillBar.vue'
import type { SubnetTreeNode } from '@/api/endpoints/subnets'
import type { Vlan } from '@/api'

/**
 * One row in the subnet hierarchy tree, drawn with explorer-style
 * connectors: vertical guide lines through ancestors that still have
 * descendants below, plus an elbow (`└─` or `├─` look) leading to this
 * row's content.
 *
 * Three positional props drive the connectors:
 *   - `depth`: 0 at the root, +1 per nested level.
 *   - `isLast`: whether this node is the last child of its parent —
 *     controls whether the elbow's vertical stem continues past the row.
 *   - `ancestorOpen`: a boolean per ancestor level, `true` when that
 *     ancestor still has more children below this row. Those columns
 *     get a vertical line; closed ancestors get blank space.
 *
 * The recursive `<SubnetTreeRow>` builds the child's `ancestorOpen` by
 * appending `!isLast` from the current node — so the lines only continue
 * through ancestors that haven't reached their last sibling yet.
 */
const props = withDefaults(
  defineProps<{
    node: SubnetTreeNode
    collapsed: Set<number>
    depth: number
    isLast?: boolean
    ancestorOpen?: boolean[]
    vlansById: Map<number, Vlan>
  }>(),
  { isLast: true, ancestorOpen: () => [] },
)

const emit = defineEmits<{
  (e: 'toggle', id: number): void
  (e: 'open', id: number): void
}>()

const hasChildren = computed(() => props.node.children.length > 0)
const isCollapsed = computed(() => props.collapsed.has(props.node.id))

const vlan = computed<Vlan | null>(() =>
  props.node.vlan_id ? (props.vlansById.get(props.node.vlan_id) ?? null) : null,
)

// One indent column = 1.5 rem. Keep the value in sync with the
// `paddingLeft` style and the absolute-positioned guide lines below.
const INDENT_REM = 1.5

const childAncestorOpen = computed(() => [...props.ancestorOpen, !props.isLast])
</script>

<template>
  <li>
    <div
      class="relative group flex items-center min-h-[2.25rem] hover:bg-surface-hover cursor-pointer transition-colors"
      :style="{ paddingLeft: `${depth * INDENT_REM + 0.75}rem` }"
      @click="emit('open', node.id)"
    >
      <!-- Vertical guide lines for ancestor columns that still have more
           siblings below this row. Centered horizontally in each indent
           column at `(i + 0.5) * INDENT_REM`. -->
      <template v-for="(open, i) in ancestorOpen" :key="`anc-${i}`">
        <span
          v-if="open"
          class="absolute top-0 bottom-0 w-px bg-border"
          :style="{ left: `${(i + 0.5) * INDENT_REM}rem` }"
          aria-hidden="true"
        />
      </template>

      <!-- Elbow connector at this row's own depth.
           - Vertical stem: top → middle (always), middle → bottom (only
             when this is NOT the last sibling, so the line stays
             continuous between siblings).
           - Horizontal arm: middle row, from stem to the start of the
             content area. -->
      <template v-if="depth > 0">
        <span
          class="absolute top-0 w-px bg-border"
          :style="{
            left: `${(depth - 0.5) * INDENT_REM}rem`,
            height: isLast ? '50%' : '100%',
          }"
          aria-hidden="true"
        />
        <span
          class="absolute top-1/2 h-px bg-border"
          :style="{
            left: `${(depth - 0.5) * INDENT_REM}rem`,
            width: `${INDENT_REM * 0.55}rem`,
          }"
          aria-hidden="true"
        />
      </template>

      <button
        v-if="hasChildren"
        type="button"
        class="relative z-10 w-5 h-5 flex items-center justify-center rounded bg-surface border border-border text-fg-muted hover:bg-surface-hover flex-shrink-0"
        :aria-label="isCollapsed ? 'Expand' : 'Collapse'"
        :aria-expanded="!isCollapsed"
        @click.stop="emit('toggle', node.id)"
      >
        <ChevronRight v-if="isCollapsed" class="w-3.5 h-3.5" />
        <ChevronDown v-else class="w-3.5 h-3.5" />
      </button>
      <span
        v-else
        class="relative z-10 w-5 h-5 inline-flex items-center justify-center text-fg-muted flex-shrink-0 bg-surface rounded"
      >
        <Network class="w-3 h-3" aria-hidden="true" />
      </span>

      <div class="flex items-center gap-2 px-2 py-1.5 min-w-0 flex-1">
        <span class="font-mono text-sm font-medium truncate">{{ node.cidr }}</span>

        <VlanBadge v-if="vlan" :vlan="vlan" class="flex-shrink-0" />

        <span v-if="node.gateway" class="text-xs text-fg-muted font-mono hidden md:inline">
          → {{ node.gateway }}
        </span>

        <span v-if="node.description" class="text-xs text-fg-muted truncate hidden lg:inline">
          — {{ node.description }}
        </span>

        <span class="ml-auto flex items-center gap-3 flex-shrink-0">
          <SubnetFillBar
            v-if="node.usable > 0"
            :used="node.used"
            :usable="node.usable"
            class="hidden sm:inline-flex"
          />
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
        v-for="(child, idx) in node.children"
        :key="child.id"
        :node="child"
        :collapsed="collapsed"
        :depth="depth + 1"
        :is-last="idx === node.children.length - 1"
        :ancestor-open="childAncestorOpen"
        :vlans-by-id="vlansById"
        @toggle="(id) => emit('toggle', id)"
        @open="(id) => emit('open', id)"
      />
    </ul>
  </li>
</template>

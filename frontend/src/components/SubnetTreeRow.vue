<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, ChevronRight, FolderTree, Network } from 'lucide-vue-next'
import VlanBadge from '@/components/VlanBadge.vue'
import Badge from '@/components/ui/Badge.vue'
import SubnetFillBar from '@/components/SubnetFillBar.vue'
import type { SubnetTreeNode } from '@/api/endpoints/subnets'
import type { Vlan } from '@/api'

const { t } = useI18n()

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
const isSynthetic = computed(() => props.node.synthetic === true)

const vlan = computed<Vlan | null>(() =>
  props.node.vlan_id ? (props.vlansById.get(props.node.vlan_id) ?? null) : null,
)

// One indent column = 1.5 rem. Keep the value in sync with the
// `paddingLeft` style and the absolute-positioned guide lines below.
const INDENT_REM = 1.5

// Children inherit our ancestor trail PLUS our own column — but only when
// we ourselves have an elbow column to extend (i.e. depth >= 1). For
// depth-0 roots, appending would put a guide line right on top of the
// depth-1 child's elbow stem (same x-position), which makes a last-child
// `└` look like a continuing `├`. Codex P2 on #74.
const childAncestorOpen = computed<boolean[]>(() =>
  props.depth === 0 ? props.ancestorOpen : [...props.ancestorOpen, !props.isLast],
)
</script>

<template>
  <li>
    <div
      :class="[
        'relative group flex items-center min-h-[2.25rem] rounded-md',
        'transition-colors duration-150 ease-soft',
        isSynthetic
          ? 'cursor-default bg-muted/30 hover:bg-muted/50'
          : 'cursor-pointer hover:bg-surface-hover',
      ]"
      :style="{ paddingLeft: `${depth * INDENT_REM + 0.75}rem` }"
      @click="isSynthetic ? null : emit('open', node.id)"
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
        class="relative z-10 w-5 h-5 flex items-center justify-center rounded bg-surface border border-border text-fg-muted hover:text-fg hover:border-border-strong hover:bg-surface-hover transition-colors duration-150 ease-soft flex-shrink-0"
        :aria-label="isCollapsed ? 'Expand' : 'Collapse'"
        :aria-expanded="!isCollapsed"
        @click.stop="emit('toggle', node.id)"
      >
        <ChevronRight v-if="isCollapsed" class="w-3.5 h-3.5" />
        <ChevronDown v-else class="w-3.5 h-3.5" />
      </button>
      <span
        v-else
        class="relative z-10 w-5 h-5 inline-flex items-center justify-center text-fg-subtle flex-shrink-0 bg-surface rounded"
      >
        <FolderTree v-if="isSynthetic" class="w-3 h-3" aria-hidden="true" />
        <Network v-else class="w-3 h-3" aria-hidden="true" />
      </span>

      <div class="flex items-center gap-2 px-2 py-1.5 min-w-0 flex-1">
        <span
          :class="[
            'font-mono text-base truncate',
            isSynthetic ? 'italic text-fg-muted' : 'font-medium text-fg',
          ]"
        >
          {{ node.cidr }}
        </span>

        <Badge v-if="isSynthetic" tone="neutral" class="flex-shrink-0">
          {{ t('subnet.tree.autoGroup') }}
        </Badge>

        <VlanBadge v-if="vlan && !isSynthetic" :vlan="vlan" class="flex-shrink-0" />

        <span
          v-if="node.gateway && !isSynthetic"
          class="text-xs text-fg-muted font-mono hidden md:inline"
        >
          → {{ node.gateway }}
        </span>

        <span
          v-if="node.description && !isSynthetic"
          class="text-xs text-fg-subtle truncate hidden lg:inline"
        >
          — {{ node.description }}
        </span>

        <span class="ml-auto flex items-center gap-3 flex-shrink-0">
          <SubnetFillBar
            v-if="node.usable > 0 && !isSynthetic"
            :used="node.used"
            :usable="node.usable"
            class="hidden sm:inline-flex"
          />
          <Badge
            v-if="hasChildren"
            tone="neutral"
            monospace
            :title="
              isSynthetic
                ? t('subnet.tree.containedCount', { n: node.children.length })
                : `${node.children.length} child subnet(s)`
            "
          >
            {{ node.children.length }}
          </Badge>
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

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import cytoscape, {
  type Core,
  type ElementDefinition,
  type EventObject,
  type LayoutOptions,
  type StylesheetJson,
} from 'cytoscape'
import dagre from 'cytoscape-dagre'
import { useUiStore } from '@/stores/ui'
import type { TopologyEdge, TopologyNode } from '@/api'

// Layout extensions are global on the cytoscape factory. Registering twice is a
// no-op so this is safe in dev with HMR.
cytoscape.use(dagre)

export type LayoutName = 'dagre' | 'cose' | 'breadthfirst' | 'circle' | 'grid'

const props = withDefaults(
  defineProps<{
    nodes: TopologyNode[]
    edges: TopologyEdge[]
    layout?: LayoutName
    selectedId?: string | null
  }>(),
  { layout: 'dagre', selectedId: null },
)

const emit = defineEmits<{
  (e: 'select-node', id: string): void
  (e: 'select-edge', id: string): void
  (e: 'select-clear'): void
}>()

const container = ref<HTMLDivElement | null>(null)
const cy = shallowRef<Core | null>(null)
const resizeObserver = ref<ResizeObserver | null>(null)
const ui = useUiStore()

// Compute layout options on demand — dagre layout config differs from cose/etc.
function layoutOpts(name: LayoutName): LayoutOptions {
  const base = { fit: true, padding: 40, animate: true, animationDuration: 250 } as const
  switch (name) {
    case 'dagre':
      return {
        ...base,
        name: 'dagre',
        // dagre-specific options live at the top level of the layout opts.
        // The cast keeps TS happy without pulling in cytoscape-dagre types.
        ...({ rankDir: 'TB', nodeSep: 60, rankSep: 90 } as Record<string, unknown>),
      } as unknown as LayoutOptions
    case 'cose':
      return { ...base, name: 'cose', idealEdgeLength: () => 120 } as LayoutOptions
    case 'breadthfirst':
      return { ...base, name: 'breadthfirst', spacingFactor: 1.2 } as LayoutOptions
    case 'circle':
      return { ...base, name: 'circle' }
    case 'grid':
      return { ...base, name: 'grid' }
  }
}

function buildStyles(isDark: boolean) {
  const node = isDark
    ? { bg: '#11151e', border: '#3a4252', text: '#e2e8f0', subText: '#94a3b8' }
    : { bg: '#ffffff', border: '#cbd5e1', text: '#0f172a', subText: '#64748b' }
  const accent = '#06b6d4'
  return [
    {
      selector: 'node',
      style: {
        'background-color': node.bg,
        'border-color': node.border,
        'border-width': 1,
        label: 'data(label)',
        color: node.text,
        'font-size': 12,
        'font-family': 'Inter, system-ui, sans-serif',
        'font-weight': 600,
        'text-valign': 'bottom',
        'text-margin-y': 6,
        'text-wrap': 'ellipsis',
        'text-max-width': '140px',
        shape: 'round-rectangle',
        width: 80,
        height: 36,
        padding: 8,
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-color': accent,
        'border-width': 2.5,
        color: accent,
      },
    },
    {
      selector: 'edge',
      style: {
        width: (ele: cytoscape.EdgeSingular) => {
          const speed = (ele.data('speed_mbps') as number | null | undefined) ?? 0
          if (speed >= 10_000) return 4
          if (speed >= 1_000) return 2.5
          return 1.5
        },
        'line-color': node.subText,
        'line-style': (ele: cytoscape.EdgeSingular) => {
          const t = (ele.data('link_type') as string | undefined) ?? 'copper'
          return t === 'fiber'
            ? 'solid'
            : t === 'dac'
              ? 'dashed'
              : t === 'virtual'
                ? 'dotted'
                : 'solid'
        },
        'curve-style': 'bezier',
        'target-arrow-shape': 'none',
        opacity: 0.7,
      },
    },
    {
      selector: 'edge:selected',
      style: { 'line-color': accent, opacity: 1 },
    },
  ] as unknown as StylesheetJson
}

function applyDataset() {
  if (!cy.value) return
  const elements: ElementDefinition[] = [
    ...props.nodes.map((n) => ({ group: 'nodes' as const, data: n.data })),
    ...props.edges.map((e) => ({ group: 'edges' as const, data: e.data })),
  ]
  cy.value.batch(() => {
    cy.value!.elements().remove()
    cy.value!.add(elements)
  })
  cy.value.layout(layoutOpts(props.layout)).run()
}

function selectId(id: string | null) {
  if (!cy.value) return
  cy.value.elements(':selected').unselect()
  if (id) {
    const el = cy.value.getElementById(id)
    if (el && !el.empty()) el.select()
  }
}

onMounted(() => {
  if (!container.value) return
  cy.value = cytoscape({
    container: container.value,
    style: buildStyles(ui.isDark),
    wheelSensitivity: 0.25,
    minZoom: 0.2,
    maxZoom: 3,
    boxSelectionEnabled: false,
    autounselectify: false,
  })
  cy.value.on('tap', 'node', (ev: EventObject) => emit('select-node', ev.target.id()))
  cy.value.on('tap', 'edge', (ev: EventObject) => emit('select-edge', ev.target.id()))
  cy.value.on('tap', (ev: EventObject) => {
    if (ev.target === cy.value) emit('select-clear')
  })

  // Cytoscape needs a sized container to lay out — but on first mount the
  // flex cascade above us may still be settling, so the container is 0×0
  // and the graph renders into the void. ResizeObserver fires once the
  // container gets its real dimensions; we resize + relayout + fit then.
  resizeObserver.value = new ResizeObserver(() => {
    if (!cy.value || !container.value) return
    const { clientWidth, clientHeight } = container.value
    if (clientWidth === 0 || clientHeight === 0) return
    cy.value.resize()
    cy.value.fit(undefined, 40)
  })
  resizeObserver.value.observe(container.value)

  applyDataset()
})

onBeforeUnmount(() => {
  resizeObserver.value?.disconnect()
  resizeObserver.value = null
  cy.value?.destroy()
  cy.value = null
})

watch(
  () => [props.nodes, props.edges],
  () => applyDataset(),
  { deep: false },
)
watch(
  () => props.layout,
  (next) => cy.value?.layout(layoutOpts(next)).run(),
)
watch(
  () => props.selectedId,
  (id) => selectId(id ?? null),
)
watch(
  () => ui.isDark,
  (isDark) => {
    if (!cy.value) return
    cy.value.style(buildStyles(isDark))
  },
)

// Expose imperative controls to the parent — fit + PNG export are user-facing,
// not state we'd want to round-trip through props.
function fit() {
  cy.value?.fit(undefined, 40)
}
function exportPng(): string | null {
  if (!cy.value) return null
  return cy.value.png({ full: true, bg: ui.isDark ? '#090b11' : '#ffffff', scale: 2 })
}
function relayout() {
  cy.value?.layout(layoutOpts(props.layout)).run()
}

defineExpose({ fit, exportPng, relayout })
</script>

<template>
  <div
    ref="container"
    class="w-full h-full bg-bg/40 rounded-md border border-border"
    role="img"
    aria-label="Network topology graph"
  />
</template>

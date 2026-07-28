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

// Node rendering — a device plate with an accent tab on its left edge, the
// same geometry the app uses for a mounted module. Drawing a literal
// rack-mount switch at 150 px wide reads as clutter; the plate keeps the
// hostname the hero and lets the graph stay legible at any zoom.
//
// The plate is built from two rects in an inline SVG so cytoscape can paint
// it via `background-image`. The hostname is rendered by cytoscape's own
// canvas labeller (centered inside the node) — that way Archivo actually
// applies and text stays crisp at every zoom level.
function buildCardSvg(
  width: number,
  height: number,
  theme: { card: string; accent: string },
): string {
  // Two stacked rects: full-size card body, then a 4-px-wide left
  // stripe in the accent colour. The cytoscape round-rectangle clip
  // takes care of rounding the corners — including the stripe's top-
  // -left / bottom-left, which gives it that "card edge tab" feel.
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><rect width="${width}" height="${height}" fill="${theme.card}"/><rect width="4" height="${height}" fill="${theme.accent}"/></svg>`
}

function svgDataUri(svg: string): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

// Two card widths: access switches feel compact, distribution-grade
// (≥48 ports) gets visual heft so density still reads at a glance.
const CARD_SMALL = { w: 156, h: 48 }
const CARD_LARGE = { w: 196, h: 48 }

function buildStyles(isDark: boolean) {
  // Faceplate palette, mirroring the CSS tokens in assets/tailwind.css. Kept
  // as literals because cytoscape paints to canvas and can't read CSS vars.
  const accent = isDark ? '#2BA79E' : '#0E8C84' // primary-400 / primary-500
  const cardBg = isDark ? '#101A19' : '#FBFCFC' // surface
  const cardBorder = isDark ? '#243835' : '#CBD6D3' // border
  const text = isDark ? '#E7EFED' : '#0C1A18' // fg
  const subText = isDark ? '#8CA3A0' : '#566A67' // fg-muted

  const cardSmall = svgDataUri(buildCardSvg(CARD_SMALL.w, CARD_SMALL.h, { card: cardBg, accent }))
  const cardLarge = svgDataUri(buildCardSvg(CARD_LARGE.w, CARD_LARGE.h, { card: cardBg, accent }))

  return [
    {
      selector: 'node',
      style: {
        // background-color is the safety net behind the SVG and also
        // what cytoscape uses to compose anti-aliased rounded corners
        // — same hue as the card body so any sub-pixel gap blends.
        'background-color': cardBg,
        'background-image': cardSmall,
        'background-fit': 'cover',
        'background-image-opacity': 1,
        'background-clip': 'node',
        'border-color': cardBorder,
        'border-width': 1,
        // Hostname rendered inside the card, past the left stripe.
        label: 'data(label)',
        color: text,
        'font-size': 12,
        'font-family': 'Archivo Variable, Archivo, system-ui, sans-serif',
        'font-weight': 600,
        'text-valign': 'center',
        'text-halign': 'center',
        // Nudge the label slightly right so it visually centers in the
        // card's content area (past the 4-px accent stripe) rather than
        // in the geometric center.
        'text-margin-x': 3,
        'text-wrap': 'ellipsis',
        'text-max-width': '136px',
        shape: 'round-rectangle',
        width: CARD_SMALL.w,
        height: CARD_SMALL.h,
      },
    },
    {
      selector: 'node[ports_total >= 48]',
      style: {
        'background-image': cardLarge,
        width: CARD_LARGE.w,
        height: CARD_LARGE.h,
        'text-max-width': '172px',
      },
    },
    {
      selector: 'node:selected',
      style: {
        'border-color': accent,
        'border-width': 2,
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
        'line-color': subText,
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
  return cy.value.png({ full: true, bg: ui.isDark ? '#080F0F' : '#FBFCFC', scale: 2 })
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

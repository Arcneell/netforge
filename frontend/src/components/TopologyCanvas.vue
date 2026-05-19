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

// Each node renders a 1U rack-mount switch chassis. The SVG is generated
// inline and fed to cytoscape via `background-image` as a URL-encoded data
// URI — no extra deps, theme-aware, regenerated when dark mode flips.
//
// Two density tiers: a denser chassis for distribution-grade switches
// (≥48 physical ports). The 16-port row reads as "this thing's bigger"
// even when the graph is dezoomed, which the previous plain-rectangle
// nodes couldn't do.
//
// Choices made to survive low-zoom rasterisation (the layouts that fit-
// to-screen with many switches end up rendering each node at maybe
// 40 px wide):
// - Solid chassis colour, not a gradient — gradients in SVG-as-image
//   often fall apart at small sizes / on some renderers.
// - A bright accent stripe along the top edge so the node still "reads"
//   as a card even at thumbnail size.
// - Larger ports (8×16 vs the old 6×12) with high contrast against the
//   chassis: the port row is what makes the icon recognisable as a
//   switch, so giving it pixel weight is non-negotiable.
type SwitchTheme = {
  chassis: string
  stripe: string
  port: string
  led: string
  ledDim: string
  vent: string
}

function buildSwitchSvg(width: number, height: number, ports: number, theme: SwitchTheme): string {
  const portWidth = 8
  const portGap = 2
  const portRowWidth = ports * portWidth + (ports - 1) * portGap
  const leftPad = 22
  const rightPad = 26
  const usable = width - leftPad - rightPad
  const portStart = leftPad + Math.max(0, (usable - portRowWidth) / 2)
  const portY = Math.round((height - 16) / 2 + 1)

  let portsSvg = ''
  for (let i = 0; i < ports; i++) {
    const x = portStart + i * (portWidth + portGap)
    portsSvg += `<rect x="${x.toFixed(1)}" y="${portY}" width="${portWidth}" height="16" rx="1.5" fill="${theme.port}"/>`
  }

  const ledX = width - 14
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
<rect width="${width}" height="${height}" fill="${theme.chassis}"/>
<rect width="${width}" height="3" fill="${theme.stripe}"/>
<g fill="${theme.vent}" opacity="0.55"><circle cx="7" cy="12" r="1.3"/><circle cx="7" cy="${height - 12}" r="1.3"/><circle cx="${width - 7}" cy="12" r="1.3"/><circle cx="${width - 7}" cy="${height - 12}" r="1.3"/></g>
<g stroke="${theme.vent}" stroke-width="1" opacity="0.45"><line x1="13" y1="11" x2="13" y2="${height - 8}"/><line x1="16" y1="11" x2="16" y2="${height - 8}"/><line x1="19" y1="11" x2="19" y2="${height - 8}"/></g>
${portsSvg}
<circle cx="${ledX}" cy="${portY + 2}" r="2" fill="${theme.led}"/>
<circle cx="${ledX}" cy="${portY + 9}" r="2" fill="${theme.ledDim}"/>
<circle cx="${ledX}" cy="${portY + 16}" r="2" fill="${theme.ledDim}"/>
</svg>`
}

function svgDataUri(svg: string): string {
  // URL-encoded data URIs render more reliably than base64 across
  // browsers when the SVG is loaded as a background image — we keep
  // the markup ASCII (hex colours, no entity refs) so the only chars
  // that actually need escaping are `#`, `"` and `<`/`>`.
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

// Node sizes match SVG viewBoxes exactly so `background-fit: cover` is a
// 1:1 paint, no scaling artefacts.
const NODE_SMALL = { w: 140, h: 48, ports: 8 }
const NODE_LARGE = { w: 188, h: 48, ports: 16 }

function buildStyles(isDark: boolean) {
  const accent = isDark ? '#818cf8' : '#6366f1' // indigo-400 / indigo-500
  const text = isDark ? '#e4e4e7' : '#111111'
  const subText = isDark ? '#a1a1aa' : '#71717a'

  const theme: SwitchTheme = isDark
    ? {
        chassis: '#1f1f23', // a hair lighter than zinc-900 page bg so the chassis pops
        stripe: '#818cf8', // indigo-400 — brand colour accent stripe
        port: '#a5b4fc', // indigo-300 — bright against the dark chassis
        led: '#22c55e', // green-500 — "active" LED
        ledDim: '#3f3f46', // zinc-700 — unlit LED
        vent: '#0a0a0c', // near-black for grille / mount holes
      }
    : {
        chassis: '#f4f4f5', // zinc-100 — gentle lift off the page bg
        stripe: '#6366f1', // indigo-500
        port: '#312e81', // indigo-950 — dark ink so ports stay legible on a light chassis even at thumbnail size
        led: '#15803d', // green-700 — darker LED for light-mode contrast
        ledDim: '#d4d4d8', // zinc-300
        vent: '#52525b', // zinc-600
      }

  const iconSmall = svgDataUri(buildSwitchSvg(NODE_SMALL.w, NODE_SMALL.h, NODE_SMALL.ports, theme))
  const iconLarge = svgDataUri(buildSwitchSvg(NODE_LARGE.w, NODE_LARGE.h, NODE_LARGE.ports, theme))

  return [
    {
      selector: 'node',
      style: {
        // background-color is the fallback that shows if the SVG ever
        // fails to load — same hue as the chassis so the node still
        // reads as "card-shaped" not "missing image".
        'background-color': theme.chassis,
        'background-image': iconSmall,
        'background-fit': 'cover',
        'background-image-opacity': 1,
        'background-clip': 'node',
        'border-color': isDark ? '#3f3f46' : '#d4d4d8',
        'border-width': 1,
        label: 'data(label)',
        color: text,
        'font-size': 11,
        'font-family': 'Geist Sans, Inter, system-ui, sans-serif',
        'font-weight': 600,
        'text-valign': 'bottom',
        'text-margin-y': 8,
        'text-wrap': 'ellipsis',
        'text-max-width': '180px',
        shape: 'round-rectangle',
        width: NODE_SMALL.w,
        height: NODE_SMALL.h,
      },
    },
    {
      selector: 'node[ports_total >= 48]',
      style: {
        'background-image': iconLarge,
        width: NODE_LARGE.w,
        height: NODE_LARGE.h,
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

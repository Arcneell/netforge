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

// Layout extensions are global on the cytoscape factory. Registering twice is
// a no-op, so this is safe in dev with HMR.
cytoscape.use(dagre)

export type LayoutName = 'dagre' | 'cose' | 'breadthfirst' | 'circle' | 'grid'

const props = withDefaults(
  defineProps<{
    nodes: TopologyNode[]
    edges: TopologyEdge[]
    layout?: LayoutName
    selectedId?: string | null
    /**
     * When a node is selected, dim everything outside its immediate
     * neighbourhood. This is what turns a mesh into a readable answer to
     * "what is this switch attached to" — the whole reason the graph exists.
     */
    focusNeighbourhood?: boolean
  }>(),
  { layout: 'dagre', selectedId: null, focusNeighbourhood: true },
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

function layoutOpts(name: LayoutName): LayoutOptions {
  const base = { fit: true, padding: 48, animate: true, animationDuration: 240 } as const
  switch (name) {
    case 'dagre':
      return {
        ...base,
        name: 'dagre',
        // dagre-specific options live at the top level of the layout opts.
        // The cast keeps TS happy without pulling in cytoscape-dagre types.
        ...({ rankDir: 'TB', nodeSep: 64, rankSep: 96 } as Record<string, unknown>),
      } as unknown as LayoutOptions
    case 'cose':
      return { ...base, name: 'cose', idealEdgeLength: () => 140 } as LayoutOptions
    case 'breadthfirst':
      return { ...base, name: 'breadthfirst', spacingFactor: 1.25 } as LayoutOptions
    case 'circle':
      return { ...base, name: 'circle' }
    case 'grid':
      return { ...base, name: 'grid' }
  }
}

/**
 * Leaf nodes are drawn as a plate with an accent tab on the left edge — the
 * same geometry the app uses for a mounted module. Drawing a literal
 * rack-mount switch at 150 px wide reads as clutter; the plate keeps the
 * hostname the hero and stays legible at any zoom.
 *
 * The plate is two rects in an inline SVG so cytoscape can paint it via
 * `background-image`. The label is rendered by cytoscape's own canvas
 * labeller so the display face actually applies and text stays crisp.
 */
function buildPlateSvg(
  width: number,
  height: number,
  theme: { plate: string; accent: string },
): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><rect width="${width}" height="${height}" fill="${theme.plate}"/><rect width="4" height="${height}" fill="${theme.accent}"/></svg>`
}

function svgDataUri(svg: string): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

// Three plate sizes. Access switches feel compact, distribution-grade
// (>= 48 ports) gets visual heft so density reads at a glance, and devices
// are deliberately smaller than any switch — the hierarchy should be obvious
// before you read a single label.
const PLATE_SWITCH = { w: 156, h: 48 }
const PLATE_SWITCH_LARGE = { w: 196, h: 48 }
const PLATE_DEVICE = { w: 128, h: 38 }

function buildStyles(isDark: boolean) {
  // Faceplate palette, mirroring the CSS tokens in assets/tailwind.css. Kept
  // as literals because cytoscape paints to canvas and can't read CSS vars.
  const accent = isDark ? '#2BA79E' : '#0E8C84' // primary-400 / primary-500
  const surface = isDark ? '#101A19' : '#FBFCFC'
  const border = isDark ? '#243835' : '#CBD6D3'
  const text = isDark ? '#E7EFED' : '#0C1A18'
  const muted = isDark ? '#8CA3A0' : '#566A67'
  // Devices are secondary citizens in this graph: a warmer, quieter accent
  // separates "thing plugged in" from "thing doing the switching".
  const deviceAccent = isDark ? '#7C8FA8' : '#5B7192'
  // Group boxes read as the enclosure the plates are mounted in — a wash of
  // the plate colour, not another card.
  const groupFill = isDark ? '#0B1413' : '#F1F4F3'
  const groupBorder = isDark ? '#1E2E2C' : '#DBE3E1'

  const plateSwitch = svgDataUri(
    buildPlateSvg(PLATE_SWITCH.w, PLATE_SWITCH.h, { plate: surface, accent }),
  )
  const plateSwitchLarge = svgDataUri(
    buildPlateSvg(PLATE_SWITCH_LARGE.w, PLATE_SWITCH_LARGE.h, { plate: surface, accent }),
  )
  const plateDevice = svgDataUri(
    buildPlateSvg(PLATE_DEVICE.w, PLATE_DEVICE.h, { plate: surface, accent: deviceAccent }),
  )

  return [
    // --- leaf nodes: shared plate ---------------------------------------
    {
      selector: 'node',
      style: {
        // background-color is the safety net behind the SVG and also what
        // cytoscape uses to compose anti-aliased rounded corners — same hue
        // as the plate so any sub-pixel gap blends.
        'background-color': surface,
        'background-image': plateSwitch,
        'background-fit': 'cover',
        'background-image-opacity': 1,
        'background-clip': 'node',
        'border-color': border,
        'border-width': 1,
        label: 'data(label)',
        color: text,
        'font-size': 12,
        'font-family': 'Archivo Variable, Archivo, system-ui, sans-serif',
        'font-weight': 600,
        'text-valign': 'center',
        'text-halign': 'center',
        // Nudge right so the label centres in the plate's content area,
        // past the 4-px accent tab, rather than geometrically.
        'text-margin-x': 3,
        'text-wrap': 'ellipsis',
        'text-max-width': '136px',
        shape: 'round-rectangle',
        width: PLATE_SWITCH.w,
        height: PLATE_SWITCH.h,
      },
    },
    {
      selector: 'node[kind = "switch"][ports_total >= 48]',
      style: {
        'background-image': plateSwitchLarge,
        width: PLATE_SWITCH_LARGE.w,
        height: PLATE_SWITCH_LARGE.h,
        'text-max-width': '172px',
      },
    },
    {
      selector: 'node[kind = "device"]',
      style: {
        'background-image': plateDevice,
        width: PLATE_DEVICE.w,
        height: PLATE_DEVICE.h,
        'font-size': 11,
        'font-weight': 500,
        'text-max-width': '110px',
      },
    },
    // A switch with no cable and nothing plugged in is the single most
    // actionable thing on screen — give it a dashed outline so it stands out
    // without needing a legend lookup.
    {
      selector: 'node[kind = "switch"][?isolated]',
      style: { 'border-style': 'dashed', 'border-color': muted, 'border-width': 1.5 },
    },
    // --- group nodes: site / room ---------------------------------------
    {
      selector: 'node[kind = "site"], node[kind = "room"]',
      style: {
        'background-image': 'none',
        'background-color': groupFill,
        'background-opacity': 1,
        'border-color': groupBorder,
        'border-width': 1,
        shape: 'round-rectangle',
        // Group labels sit on the top edge, set in the mono legend style the
        // rest of the app uses for structural labels.
        'text-valign': 'top',
        'text-halign': 'center',
        'text-margin-y': -6,
        'font-family': 'IBM Plex Mono, ui-monospace, monospace',
        'font-size': 10,
        'font-weight': 600,
        'text-transform': 'uppercase',
        color: muted,
        padding: '24px',
        width: 'label',
        height: 'label',
      },
    },
    {
      selector: 'node[kind = "site"]',
      style: { 'border-width': 1.5, 'font-size': 11, padding: '32px' },
    },
    // --- selection + focus ----------------------------------------------
    {
      selector: 'node:selected',
      style: { 'border-color': accent, 'border-width': 2, 'border-style': 'solid' },
    },
    {
      // Applied by `applyFocus`. Cytoscape has no built-in "dim the rest",
      // so the class is added to everything outside the neighbourhood.
      selector: '.nf-dimmed',
      style: { opacity: 0.18, 'text-opacity': 0.18 },
    },
    {
      selector: 'node.nf-neighbour',
      style: { 'border-color': accent, 'border-width': 1.5 },
    },
    // --- edges ------------------------------------------------------------
    {
      selector: 'edge',
      style: {
        width: (ele: cytoscape.EdgeSingular) => {
          const speed = (ele.data('speed_mbps') as number | null | undefined) ?? 0
          if (speed >= 10_000) return 4
          if (speed >= 1_000) return 2.5
          return 1.5
        },
        'line-color': muted,
        'line-style': (ele: cytoscape.EdgeSingular) => {
          const t = (ele.data('link_type') as string | undefined) ?? 'copper'
          if (t === 'dac') return 'dashed'
          if (t === 'virtual') return 'dotted'
          return 'solid'
        },
        'curve-style': 'bezier',
        'target-arrow-shape': 'none',
        opacity: 0.72,
      },
    },
    {
      // Device attachments are drops off a switch, not backbone cable —
      // thinner and quieter so the backbone stays readable through them.
      selector: 'edge[kind = "attachment"]',
      style: {
        width: 1,
        'line-color': deviceAccent,
        'line-style': 'solid',
        opacity: 0.5,
        'curve-style': 'straight',
      },
    },
    {
      selector: 'edge:selected',
      style: { 'line-color': accent, opacity: 1 },
    },
    {
      selector: 'edge.nf-neighbour',
      style: { 'line-color': accent, opacity: 1 },
    },
  ] as unknown as StylesheetJson
}

function applyDataset() {
  if (!cy.value) return
  // `isolated` is a render-only flag: a switch with no incident edge. It's
  // derived here rather than sent by the API because "isolated" only means
  // anything relative to the edges actually in this payload (a VLAN filter
  // can legitimately hide the cable that connects it).
  const incident = new Set<string>()
  for (const e of props.edges) {
    incident.add(e.data.source)
    incident.add(e.data.target)
  }
  const elements: ElementDefinition[] = [
    ...props.nodes.map((n) => ({
      group: 'nodes' as const,
      data: {
        ...n.data,
        // Cytoscape reads `parent` off data to build compound nodes.
        parent: n.data.parent ?? undefined,
        isolated: n.data.kind === 'switch' && !incident.has(n.data.id) ? true : undefined,
      },
    })),
    ...props.edges.map((e) => ({ group: 'edges' as const, data: e.data })),
  ]
  cy.value.batch(() => {
    cy.value!.elements().remove()
    cy.value!.add(elements)
  })
  cy.value.layout(layoutOpts(props.layout)).run()
  applyFocus(props.selectedId ?? null)
}

/** Dim everything outside the selected node's immediate neighbourhood. */
function applyFocus(id: string | null) {
  const graph = cy.value
  if (!graph) return
  graph.elements().removeClass('nf-dimmed nf-neighbour')
  if (!id || !props.focusNeighbourhood) return
  const el = graph.getElementById(id)
  if (!el || el.empty() || !el.isNode()) return
  // Ancestors stay lit so the selected plate keeps its site/room context;
  // without them the node floats in an unlabelled void.
  const keep = el.closedNeighborhood().union(el.ancestors())
  graph.elements().difference(keep).addClass('nf-dimmed')
  keep.difference(el).addClass('nf-neighbour')
}

function selectId(id: string | null) {
  if (!cy.value) return
  cy.value.elements(':selected').unselect()
  if (id) {
    const el = cy.value.getElementById(id)
    if (el && !el.empty()) el.select()
  }
  applyFocus(id)
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
  // flex cascade above us may still be settling, so the container is 0x0 and
  // the graph renders into the void. ResizeObserver fires once the container
  // gets its real dimensions; resize + fit then.
  resizeObserver.value = new ResizeObserver(() => {
    if (!cy.value || !container.value) return
    const { clientWidth, clientHeight } = container.value
    if (clientWidth === 0 || clientHeight === 0) return
    cy.value.resize()
    cy.value.fit(undefined, 48)
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
  () => props.focusNeighbourhood,
  () => applyFocus(props.selectedId ?? null),
)
watch(
  () => ui.isDark,
  (isDark) => {
    if (!cy.value) return
    cy.value.style(buildStyles(isDark))
  },
)

// Imperative controls the parent drives from the toolbar — user-facing
// actions, not state worth round-tripping through props.
function fit() {
  cy.value?.fit(undefined, 48)
}
function exportPng(): string | null {
  if (!cy.value) return null
  return cy.value.png({ full: true, bg: ui.isDark ? '#080F0F' : '#FBFCFC', scale: 2 })
}
function relayout() {
  cy.value?.layout(layoutOpts(props.layout)).run()
}
function centerOn(id: string) {
  const el = cy.value?.getElementById(id)
  if (el && !el.empty()) cy.value?.animate({ center: { eles: el }, duration: 220 })
}

defineExpose({ fit, exportPng, relayout, centerOn })
</script>

<template>
  <!--
    `aria-hidden` is deliberate. This canvas is pointer-driven with no
    keyboard affordance of its own, and the previous `role="img"` actively
    lied about that: it advertised a static image while handling taps. The
    accessible path is the List view in TopologyView, which renders the same
    nodes and edges as real focusable rows. Hiding the decorative duplicate
    beats shipping a control screen readers can reach but not operate.
  -->
  <div
    ref="container"
    class="w-full h-full bg-bg/40 rounded-lg border border-border"
    aria-hidden="true"
  />
</template>

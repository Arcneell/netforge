# 09 — Graph topology

## Goal

Let you **see** the network at a glance: switches, links, paths, sites. A visual diagnostic tool (where does traffic go, which switches are cascaded, which link is saturated) and a presentation tool (diagram for an audit, a mentor, a contractor).

## Engine: Cytoscape.js

Choice justified in [02-architecture.md](02-architecture.md).

Additional libraries:
- `cytoscape-dagre`: hierarchical layout (ideal for core → distribution → access).
- `cytoscape-fcose`: clean force-directed layout for dense graphs.
- `cytoscape-popper` + `tippy.js`: rich tooltips on hover.

## Graph structure

### Nodes (switches)

```json
{
  "data": {
    "id": "sw-3",
    "label": "SW-SRV-01",
    "type": "switch",
    "vendor": "Aruba",
    "model": "2930F-48G",
    "site_code": "PAR",
    "room_code": "SALLE-SRV-01",
    "ports_total": 48,
    "ports_used": 42,
    "management_ip": "10.0.10.251"
  },
  "classes": "switch vendor-aruba"
}
```

CSS classes used for styling: background color per vendor, central icon, thicker border if the switch is "core".

### Edges (links)

```json
{
  "data": {
    "id": "link-12",
    "source": "sw-3",
    "target": "sw-7",
    "port_a": 48,
    "port_b": 24,
    "speed_mbps": 10000,
    "link_type": "fiber"
  },
  "classes": "link fiber speed-10g"
}
```

Edge style:
- Thickness proportional to `speed_mbps` (log scale).
- Color by `link_type` (fiber in blue, copper in orange, DAC in purple, virtual dashed).
- Label in the middle: `48 ↔ 24` (the two port numbers).

## Graph construction — backend

Endpoint `GET /api/topology?site_id={optional}`:

```python
@router.get("/topology")
async def get_topology(site_id: int | None = None, db: AsyncSession = Depends(get_db)):
    q = select(Switch)
    if site_id:
        q = q.join(Room).where(Room.site_id == site_id)
    switches = (await db.execute(q)).scalars().all()
    switch_ids = {s.id for s in switches}

    links_q = select(Link).join(Port, Link.port_a_id == Port.id).where(Port.switch_id.in_(switch_ids))
    links = (await db.execute(links_q)).scalars().all()

    nodes = [
        {"data": {"id": f"sw-{s.id}", "label": s.name, "type": "switch", ...}}
        for s in switches
    ]
    edges = [
        {"data": {"id": f"link-{l.id}", "source": f"sw-{l.port_a.switch_id}",
                  "target": f"sw-{l.port_b.switch_id}", ...}}
        for l in links
    ]
    return {"nodes": nodes, "edges": edges}
```

Complexity: O(switches + links). For a typical network (< 50 switches), the computation is trivial (< 50 ms).

## Frontend — component

`components/TopologyCanvas.vue`:

```vue
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import cytoscape from 'cytoscape'
import dagre from 'cytoscape-dagre'
import fcose from 'cytoscape-fcose'
import { api } from '@/api/client'

cytoscape.use(dagre)
cytoscape.use(fcose)

const props = defineProps<{ siteId?: number }>()
const container = ref<HTMLDivElement>()
const cy = ref<cytoscape.Core>()
const layout = ref<'dagre' | 'fcose'>('dagre')

async function load() {
  const { data } = await api.get('/topology', { params: { site_id: props.siteId } })
  cy.value = cytoscape({
    container: container.value,
    elements: [...data.nodes, ...data.edges],
    style: [/* ... */],
    layout: { name: layout.value, rankDir: 'TB' }
  })
  cy.value.on('tap', 'node', (e) => emit('select-switch', e.target.data('id')))
  cy.value.on('tap', 'edge', (e) => emit('select-link', e.target.data('id')))
}

onMounted(load)
watch(() => props.siteId, load)
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="toolbar flex gap-2 p-2 border-b">
      <button @click="layout = 'dagre'; load()">Hierarchical</button>
      <button @click="layout = 'fcose'; load()">Force</button>
      <button @click="cy?.fit()">Fit</button>
      <button @click="exportPng">Export PNG</button>
    </div>
    <div ref="container" class="flex-1"></div>
  </div>
</template>
```

## `TopologyView.vue` view

Split layout:
- Left 75%: `TopologyCanvas`.
- Right 25%: side panel. Shows details of the selected switch or link. Clickable links to `/switches/:id` or `/links/:id` for editing.
- Top bar: site selector, "show only connected switches" toggle, `{switches} switches · {links} links` counter.

## Special cases

### Orphan switch
A switch with no links shows up as an isolated node. Visually: slightly grayed color with a ⚠ icon to encourage documenting uplinks.

### Dangling links
If a link in Netforge points to a port whose switch no longer exists (cascade FK should prevent this, but just in case), we display the orphan "Unknown" node in red.

### LAG / LACP bundles
v1: a LAG = N separate links between the same two switches (Cytoscape renders them in parallel). No specific visual grouping. v2 possibly: group LAG links graphically.

## PNG / SVG export

`cy.png({ full: true, bg: 'white', scale: 2 })` → base64 → blob → download. Useful for attaching to a ticket or a report.

For SVG, we use `cytoscape-svg` (community plugin) — to be evaluated, otherwise PNG is enough for v1.

## Performance

- 20 switches, ~50 links: instant.
- 100 switches, ~500 links: Cytoscape handles it easily (< 200 ms layout).
- Beyond that, consider clustering (group by site) or lazy rendering.

## v2 evolutions

- Link colors based on saturation (requires SNMP polling).
- Path highlighting: click 2 switches, the path is highlighted.
- VLAN overlay: check a VLAN → display only the links carrying it.
- Traffic animation (real-time or simulated).

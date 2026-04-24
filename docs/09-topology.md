# 09 — Topologie graphique

## Objectif

Permettre de **voir** le parc en un coup d'œil : switches, liens, chemins, sites. Outil de diagnostic visuel (où passe le trafic, quels switches sont en cascade, quel lien sature) et de présentation (schéma pour audit, tuteur, prestataire).

## Moteur : Cytoscape.js

Choix justifié dans [02-architecture.md](02-architecture.md).

Lib additionnelle :
- `cytoscape-dagre` : layout hiérarchique (idéal pour core → distribution → access).
- `cytoscape-fcose` : layout force-directed propre pour graphes denses.
- `cytoscape-popper` + `tippy.js` : tooltips riches au hover.

## Structure du graphe

### Nœuds (switches)

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

Classes CSS utilisées pour le style : couleur de fond selon vendor, icône centrale, bord plus épais si switch "core".

### Edges (liens)

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

Style edge :
- Épaisseur proportionnelle à `speed_mbps` (log scale).
- Couleur selon `link_type` (fibre en bleu, cuivre en orange, DAC en violet, virtuel en pointillé).
- Label au milieu : `48 ↔ 24` (les deux numéros de port).

## Construction du graphe — backend

Endpoint `GET /api/topology?site_id={optional}` :

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

Complexité : O(switches + links). Pour un parc typique (< 50 switches), calcul trivial (< 50 ms).

## Frontend — composant

`components/TopologyCanvas.vue` :

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
      <button @click="layout = 'dagre'; load()">Hiérarchique</button>
      <button @click="layout = 'fcose'; load()">Force</button>
      <button @click="cy?.fit()">Recadrer</button>
      <button @click="exportPng">Exporter PNG</button>
    </div>
    <div ref="container" class="flex-1"></div>
  </div>
</template>
```

## Vue `TopologyView.vue`

Layout split :
- Gauche 75% : `TopologyCanvas`.
- Droite 25% : panel latéral. Montre les détails du switch ou du lien sélectionné. Liens cliquables vers `/switches/:id` ou `/links/:id` pour éditer.
- Top bar : sélecteur de site, toggle "afficher seulement les switches connectés", compteur `{switches} switches · {links} liens`.

## Cas spéciaux

### Switch orphelin
Un switch sans aucun lien apparaît comme nœud isolé. Visuellement : couleur légèrement grisée avec icône ⚠ pour inciter à documenter les uplinks.

### Liens en attente
Si un lien dans Netforge pointe sur un port dont le switch n'existe plus (FK cascade devrait empêcher ça, mais par sécurité), on affiche le nœud orphelin "Unknown" en rouge.

### Agrégats LAG / LACP
v1 : un LAG = N liens séparés entre les mêmes deux switches (Cytoscape les affiche en parallèle). Pas de regroupement visuel particulier. v2 éventuellement : grouper graphiquement les liens LAG.

## Export PNG / SVG

`cy.png({ full: true, bg: 'white', scale: 2 })` → base64 → blob → download. Utile pour joindre à un ticket ou un rapport.

Pour SVG, on utilise `cytoscape-svg` (plugin communautaire) — à évaluer, sinon PNG suffit pour v1.

## Performance

- 20 switches, ~50 liens : instantané.
- 100 switches, ~500 liens : Cytoscape tient sans souci (< 200 ms de layout).
- Au-delà, envisager du clustering (grouper par site) ou du lazy rendering.

## Évolutions v2

- Couleur des liens selon saturation (nécessite SNMP polling).
- Path highlighting : on clique 2 switches, le chemin est surligné.
- Overlay VLAN : cocher un VLAN → afficher uniquement les liens qui le portent.
- Animation du trafic (en temps réel ou simulation).

# 05 — Frontend

## Stack

- **Vue 3** (Composition API, `<script setup>`)
- **TypeScript** strict
- **Vite** pour le dev server et le build
- **Vue Router 4** pour le routing
- **Pinia** pour le state
- **Tailwind CSS** pour le style (pas de lib de composants lourde — tout custom simple)
- **Axios** pour le HTTP
- **Cytoscape.js** pour la topologie
- **Openapi-typescript** pour générer les types TS à partir du schéma OpenAPI de FastAPI

## Arborescence `frontend/src/`

```
src/
├── main.ts
├── App.vue
├── router/
│   └── index.ts
├── stores/
│   ├── auth.ts
│   ├── subnets.ts
│   ├── vlans.ts
│   ├── switches.ts
│   └── topology.ts
├── api/
│   ├── client.ts              # axios instance + interceptors
│   ├── types.ts               # généré via openapi-typescript
│   └── endpoints/             # wrappers typés par ressource
├── views/
│   ├── DashboardView.vue
│   ├── SubnetsListView.vue
│   ├── SubnetDetailView.vue
│   ├── VlansListView.vue
│   ├── SwitchesListView.vue
│   ├── SwitchDetailView.vue
│   ├── DevicesListView.vue
│   ├── DeviceDetailView.vue
│   ├── TopologyView.vue
│   ├── ImportView.vue
│   ├── AuditView.vue
│   ├── SettingsView.vue
│   └── LoginView.vue
├── components/
│   ├── AppShell.vue           # layout avec sidebar + topbar
│   ├── GlobalSearch.vue       # barre de recherche top-bar (cmd+k)
│   ├── IpGrid.vue             # grille visuelle des IPs d'un subnet
│   ├── IpEditor.vue           # modale CRUD IP
│   ├── PortTable.vue          # tableau des ports d'un switch
│   ├── PortEditor.vue         # modale CRUD port
│   ├── VlanBadge.vue          # pastille colorée VLAN
│   ├── SwitchCard.vue         # carte récap switch
│   ├── TopologyCanvas.vue     # wrapper Cytoscape
│   ├── AuditDiff.vue          # affichage JSON diff before/after
│   ├── CsvDropzone.vue        # upload drag&drop
│   ├── ConfirmDialog.vue      # modale confirmation générique
│   └── ui/                    # primitives (Button, Input, Modal, Toast...)
├── composables/
│   ├── useApi.ts              # wrapper axios + toast erreurs
│   ├── useAuth.ts             # accès user courant + role
│   ├── useKeyboardShortcuts.ts
│   └── useDebounce.ts
├── utils/
│   ├── cidr.ts                # helpers calcul IPs d'un CIDR
│   ├── mac.ts                 # format/validation MAC
│   └── formatters.ts          # dates, bytes, etc.
└── assets/
    └── tailwind.css
```

## Routing

| Route | View | Auth | Rôle min |
|-------|------|------|----------|
| `/login` | `LoginView` | publique | - |
| `/` | `DashboardView` | auth | viewer |
| `/subnets` | `SubnetsListView` | auth | viewer |
| `/subnets/:id` | `SubnetDetailView` | auth | viewer |
| `/vlans` | `VlansListView` | auth | viewer |
| `/switches` | `SwitchesListView` | auth | viewer |
| `/switches/:id` | `SwitchDetailView` | auth | viewer |
| `/devices` | `DevicesListView` | auth | viewer |
| `/devices/:id` | `DeviceDetailView` | auth | viewer |
| `/topology` | `TopologyView` | auth | viewer |
| `/import` | `ImportView` | auth | admin |
| `/audit` | `AuditView` | auth | admin |
| `/settings` | `SettingsView` | auth | admin |

Guard global dans `router/index.ts` : si pas authentifié → redirect `/login?next=<url>`. Si rôle insuffisant → page 403.

## Pages clés — maquette textuelle

### Dashboard
Grid 4 cartes :
- Nombre de subnets, IPs utilisées/totales
- Nombre de switches, ports occupés/totaux
- Top 5 subnets proches de saturation
- 10 dernières modifications (audit log condensé)

### SubnetsListView
Tableau trié avec :
- CIDR, VLAN (badge), Site, Utilisation (barre de progression), Actions.
- Filtres : site, VLAN, état (saturé / OK / vide).
- Bouton "Nouveau subnet" (admin).

### SubnetDetailView
- Header : CIDR, gateway, VLAN, description, stats.
- Grille visuelle des IPs (`IpGrid.vue`) : chaque IP est une case colorée selon son statut. Clic → `IpEditor`.
- Vue alternative "tableau" avec recherche et tri.
- Bouton "Exporter CSV".

### SwitchDetailView
- Header : nom, modèle, IP mgmt, room, stats (X/Y ports utilisés).
- Vue rack-like (représentation visuelle des ports 1..N en ligne, couleur selon VLAN ou état).
- Tableau détaillé : n°, label, mode, VLAN natif, VLANs tagués, device, IP, état.
- Clic sur port → `PortEditor` (modale).
- Onglet "Liens" : liste des uplinks/downlinks de ce switch.

### TopologyView
Pleine page, `TopologyCanvas.vue` Cytoscape :
- Nœuds switches (icônes selon vendor).
- Edges : liens avec épaisseur proportionnelle à la vitesse.
- Panneau latéral droit : détails du nœud/edge sélectionné.
- Contrôles : layout (dagre / cose / breadthfirst), filtre par site, zoom/fit, export PNG.

### ImportView
- Sélecteur de type d'entité (subnets / vlans / ips / switches / ports / devices / links).
- Dropzone CSV.
- Aperçu des 10 premières lignes parsées.
- Résumé avant import : "12 nouveaux, 3 existants mis à jour, 1 erreur ligne 7".
- Bouton "Valider l'import".

## State management (Pinia)

Chaque store expose :
- `state` : cache des entités par id (`Map<number, Entity>`).
- `getters` : listes filtrées, stats dérivées.
- `actions` : `fetchAll`, `fetchById`, `create`, `update`, `delete` qui appellent `api/*` et mutent le state.

Pas de cache agressif type TanStack Query pour v1 — du Pinia simple avec invalidation manuelle après mutation. Si le besoin devient évident, on basculera sur `@tanstack/vue-query`.

## Style

- Palette Tailwind par défaut + 2 couleurs custom : `primary` (bleu Mooland si charte, sinon slate), `accent`.
- Dark mode natif Tailwind (`class="dark"` sur `<html>`), toggle dans la top bar.
- Typographie : Inter (Google Fonts ou self-hosté) + monospace pour IPs/MACs.
- Responsive : desktop-first (outil admin), mobile basique pour consulter mais pas éditer.

## Accessibilité

- Labels ARIA sur toutes les actions.
- Focus visible.
- Keyboard nav complète (Tab, Enter, Esc pour les modales).
- Raccourcis : `cmd/ctrl+k` ouvre la recherche globale, `g s` → subnets, `g t` → topologie, etc.

## Build

`vite build` produit `dist/` servi par Nginx. Le `nginx.conf` fait le fallback SPA (`try_files $uri $uri/ /index.html`) et proxifie `/api/` vers le container backend.

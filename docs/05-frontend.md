# 05 — Frontend

## Stack

- **Vue 3** (Composition API, `<script setup>`)
- **TypeScript** strict
- **Vite** for the dev server and the build
- **Vue Router 4** for routing
- **Pinia** for state
- **Tailwind CSS** for styling (no heavyweight component library — everything is simple and custom)
- **Axios** for HTTP
- **Cytoscape.js** for topology
- **openapi-typescript** to generate TS types from the FastAPI OpenAPI schema

## `frontend/src/` layout

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
│   ├── types.ts               # generated via openapi-typescript
│   └── endpoints/             # typed wrappers per resource
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
│   ├── AppShell.vue           # layout with sidebar + topbar
│   ├── GlobalSearch.vue       # top-bar search (cmd+k)
│   ├── IpGrid.vue             # visual grid of a subnet's IPs
│   ├── IpEditor.vue           # IP CRUD modal
│   ├── PortTable.vue          # table of a switch's ports
│   ├── PortEditor.vue         # port CRUD modal
│   ├── VlanBadge.vue          # colored VLAN pill
│   ├── SwitchCard.vue         # switch summary card
│   ├── TopologyCanvas.vue     # Cytoscape wrapper
│   ├── AuditDiff.vue          # before/after JSON diff display
│   ├── CsvDropzone.vue        # drag & drop upload
│   ├── ConfirmDialog.vue      # generic confirmation modal
│   └── ui/                    # primitives (Button, Input, Modal, Toast...)
├── composables/
│   ├── useApi.ts              # axios wrapper + error toasts
│   ├── useAuth.ts             # current user + role accessor
│   ├── useKeyboardShortcuts.ts
│   └── useDebounce.ts
├── utils/
│   ├── cidr.ts                # helpers to compute IPs in a CIDR
│   ├── mac.ts                 # MAC formatting/validation
│   └── formatters.ts          # dates, bytes, etc.
└── assets/
    └── tailwind.css
```

## Routing

| Route | View | Auth | Min role |
|-------|------|------|----------|
| `/login` | `LoginView` | public | - |
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

Global guard in `router/index.ts`: if not authenticated → redirect to `/login?next=<url>`. If the role is insufficient → 403 page.

## Key pages — textual mockup

### Dashboard
Grid of 4 cards:
- Number of subnets, used/total IPs
- Number of switches, used/total ports
- Top 5 subnets nearing saturation
- 10 most recent changes (condensed audit log)

### SubnetsListView
Sortable table with:
- CIDR, VLAN (badge), Site, Usage (progress bar), Actions.
- Filters: site, VLAN, status (saturated / OK / empty).
- "New subnet" button (admin).

### SubnetDetailView
- Header: CIDR, gateway, VLAN, description, stats.
- Visual IP grid (`IpGrid.vue`): each IP is a cell colored by its status. Click → `IpEditor`.
- Alternative "table" view with search and sort.
- "Export CSV" button.

### SwitchDetailView
- Header: name, model, management IP, room, stats (X/Y used ports).
- Rack-like view (visual representation of ports 1..N in a row, color based on VLAN or state).
- Detailed table: #, label, mode, native VLAN, tagged VLANs, device, IP, state.
- Click on a port → `PortEditor` (modal).
- "Links" tab: list of this switch's uplinks/downlinks.

### TopologyView
Full page, `TopologyCanvas.vue` Cytoscape:
- Switch nodes (icons per vendor).
- Edges: links with thickness proportional to speed.
- Right-hand side panel: details of the selected node/edge.
- Controls: layout (dagre / cose / breadthfirst), filter by site, zoom/fit, PNG export.

### ImportView
- Entity type selector (subnets / vlans / ips / switches / ports / devices / links).
- CSV dropzone.
- Preview of the first 10 parsed rows.
- Pre-import summary: "12 new, 3 existing updated, 1 error on line 7".
- "Apply import" button.

## State management (Pinia)

Each store exposes:
- `state`: cache of entities by id (`Map<number, Entity>`).
- `getters`: filtered lists, derived stats.
- `actions`: `fetchAll`, `fetchById`, `create`, `update`, `delete` that call `api/*` and mutate the state.

No aggressive cache like TanStack Query for v1 — just plain Pinia with manual invalidation after mutations. If the need becomes clear, we'll switch to `@tanstack/vue-query`.

## Style

- Default Tailwind palette + 2 custom colors: `primary` (cyan/teal by default, overridable via `tailwind.config.js`) and `accent`.
- Native Tailwind dark mode (`class="dark"` on `<html>`), toggle in the top bar.
- Typography: Inter (Google Fonts or self-hosted) + monospace for IPs/MACs.
- Responsive: desktop-first (admin tool), basic mobile for read but not for editing.

## Accessibility

- ARIA labels on every action.
- Visible focus.
- Full keyboard navigation (Tab, Enter, Esc for modals).
- Shortcuts: `cmd/ctrl+k` opens the global search, `g s` → subnets, `g t` → topology, etc.

## Build

`vite build` produces `dist/` served by Nginx. The `nginx.conf` handles the SPA fallback (`try_files $uri $uri/ /index.html`) and proxies `/api/` to the backend container.

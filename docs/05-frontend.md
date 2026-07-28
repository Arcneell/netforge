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

## Design system

The interface aims to disappear. White space and type size carry the hierarchy,
borders are hairlines, and colour is spent on one accent (indigo) plus the three
status signals. Nothing is decorative.

Tokens live in `assets/tailwind.css` as CSS custom properties and are surfaced to
Tailwind as semantic names in `tailwind.config.js` — write `bg-surface`, never
`bg-white dark:bg-zinc-900`. The same class then works in both themes.

**Type.** Inter (variable) for the interface, IBM Plex Mono for values that are
genuinely code-like — CIDRs, MACs, firmware strings — with slashed zero and
tabular figures so `10.0.0.0/8` is never ambiguous. The scale is redefined in
`tailwind.config.js`: `text-base` is 14 px and is the body size; `text-sm` (13 px)
and `text-xs` (12 px) are metadata; `text-2xl` (24 px) is a page title.

**Component classes.** Prefer these over re-deriving the look inline:

| Class                                                                | Use                                                            |
| -------------------------------------------------------------------- | -------------------------------------------------------------- |
| `.nf-card`                                                           | The default container — hairline border, barely-there lift     |
| `.nf-interactive`                                                    | Add to a card that is itself a link or button                  |
| `.nf-section-title`                                                  | Heading above a group of content                               |
| `.nf-label`                                                          | Small caption naming a value: table headers, definition labels |
| `.nf-input` / `.nf-input-control`                                    | Text inputs                                                    |
| `.nf-segmented` / `.nf-segmented-item` / `.nf-segmented-item-active` | Segmented control (prefer the `ui/Segmented.vue` component)    |
| `.nf-toolbar`                                                        | Filter/action bar above a table or list                        |
| `.nf-link`                                                           | Inline link                                                    |
| `.nf-tab` / `.nf-tab-active`                                         | Horizontal tab, used by `WorkspaceTabs`                        |
| `.nf-list-row`                                                       | A row in a list that navigates somewhere                       |
| `.nf-enter` / `.nf-stagger`                                          | Entrance animation — see Motion                                |

**Selects.** Always `ui/Select.vue`. Never a native `<select>`.

Its popup is a listbox we render and teleport ourselves, which is not a
stylistic preference: a native option popup is painted by the OS, and Chromium
on Windows keeps the light palette for it regardless of `color-scheme: dark`.
Setting `background-color` on `<option>` does not take, while the author
`color` does — so a dark theme produced light text on a light popup, unreadable.
There is no CSS fix; owning the popup is the only reliable one. The component
handles keyboard navigation (arrows, Home/End, Enter, Escape, type-ahead),
`role="combobox"`/`listbox` semantics, and flipping above the trigger when
there is no room below.

**Opacity modifiers run in steps of 5.** `bg-primary-500/15` is generated;
`bg-primary-500/12` is not — Tailwind emits nothing at all for it, so the
utility silently vanishes and whatever it was meant to override wins. That is
how the active sidebar item ended up light-on-light in dark mode: its
`dark:bg-primary-500/12` never existed, leaving the light-theme `bg-primary-50`
in place. Use a multiple of 5, or bracket the value (`/[0.12]`).

**Geometry.** Radii are 6 px for controls, 10 px for cards, 12 px for modals.
Elevation only where something genuinely floats — `shadow-xs` on cards,
`shadow-lg` on menus, `shadow-xl` on modals.

**Motion.** Deliberately small: transitions run 150 ms on `ease-soft`, and
everything animated is `opacity` or `transform` so it stays on the compositor.
Put `.nf-stagger` on a page's outermost wrapper and its DIRECT children fade up
in sequence — that is the page entrance, and nothing should add a second one.
`.nf-enter` is the single-element version. Never put `.nf-stagger` on a list
whose rows re-render on refetch; the animation would replay on every poll. The
keyframes use `animation-fill-mode: backwards` on purpose: with `both`, the
final `transform: none` stays latched and silently defeats every hover
transform underneath. `prefers-reduced-motion` disables all of it globally.

**Page shell.** Every view opens with
`<div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">` and a
`<PageHeader>`.

## Creating and editing

Create and edit are **full pages, never modals**. Each entity has
`/<entity>/new` and `/<entity>/:id/edit`, served by one component under
`views/forms/` so the two forms cannot drift apart. Lists and detail pages
navigate; they no longer own an editor instance.

| Entity | Routes                                                      |
| ------ | ----------------------------------------------------------- |
| Subnet | `subnet-new`, `subnet-edit`                                 |
| IP     | `ip-new` (`subnets/:subnetId/ips/new?address=…`), `ip-edit` |
| VLAN   | `vlan-new`, `vlan-edit`                                     |
| Switch | `switch-new`, `switch-edit`                                 |
| Device | `device-new`, `device-edit`                                 |
| Port   | `port-edit` (`switches/:switchId/ports/:id/edit`)           |

A literal segment must be declared **before** its `:id` sibling — otherwise
`/subnets/new` matches the detail route and tries to load a subnet with the id
`"new"`.

Compose a form out of `components/FormPage.vue` (breadcrumb, title, error
slot, sticky action bar, optional `#aside` column) and
`components/FormSection.vue` (a titled panel; fields flow into up to three
columns, and a field takes the whole row with
`class="sm:col-span-2 lg:col-span-3"`).

Modals are still right for things that are not entity forms: confirmations
(`ConfirmDialog`), the bulk IP range action (`BulkIpDialog`), and the one-shot
secret reveals in settings.

## Navigation

The sidebar is one flat list of nine entries. The six network objects are what
people reach for all day and each stays one click away. Everything
administrative collapses into two workspaces, each a parent route rendering
`WorkspaceTabs` above its children:

| Workspace    | Tabs                                                         |
| ------------ | ------------------------------------------------------------ |
| `/assistant` | `/assistant/insights`, `/assistant/ask`, `/assistant/drafts` |
| `/data`      | `/data/import`, `/data/audit`, `/data/snapshots`             |

The pre-grouping paths (`/insights`, `/ask`, `/drafts`, `/import`, `/audit`,
`/snapshots/compare`) redirect to their new homes, and every route keeps its
original name — `router.push({ name: 'audit' })` still resolves.

## Routing

| Route           | View               | Auth   | Min role |
| --------------- | ------------------ | ------ | -------- |
| `/login`        | `LoginView`        | public | -        |
| `/`             | `DashboardView`    | auth   | viewer   |
| `/subnets`      | `SubnetsListView`  | auth   | viewer   |
| `/subnets/:id`  | `SubnetDetailView` | auth   | viewer   |
| `/vlans`        | `VlansListView`    | auth   | viewer   |
| `/switches`     | `SwitchesListView` | auth   | viewer   |
| `/switches/:id` | `SwitchDetailView` | auth   | viewer   |
| `/devices`      | `DevicesListView`  | auth   | viewer   |
| `/devices/:id`  | `DeviceDetailView` | auth   | viewer   |
| `/topology`     | `TopologyView`     | auth   | viewer   |
| `/import`       | `ImportView`       | auth   | admin    |
| `/audit`        | `AuditView`        | auth   | admin    |
| `/settings`     | `SettingsView`     | auth   | admin    |

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

# 12 — User guide

NetForge is your team's single source of truth for **IP addresses, VLANs,
subnets, switches and the cables between them**. The first half of this page
is the quick-start — enough to be productive on day one. The
[Feature reference](#feature-reference) below goes deeper for operators who
want the full picture.

> Looking for the API reference? See [04-api.md](04-api.md). Looking for
> deployment instructions? See [07-deployment.md](07-deployment.md).

## First login

Open `https://netforge.example.local` (your IT team will give you the actual
URL). Click **Sign in** — you're sent to your company's identity provider
(Microsoft / Google / GitHub), then back to NetForge.

Two roles exist:

- **Viewer** — can read everything (inventory, audit log, exports). Can't
  change a single field.
- **Admin** — can create, edit, delete, and run CSV imports.

If you need to write but the buttons are greyed out, ask an existing admin
to promote you (Settings → Users).

## The map of the app

| Where | What it shows | Who needs it |
|-------|---------------|--------------|
| **Dashboard** | Headline counts and recent activity. | Everyone. |
| **Subnets** | Every IPv4 subnet with usage bar; click a subnet for a grid of all its IPs. | The IP-attribution flow lives here. |
| **VLANs** | Tagged VLANs, their colors, their description. | Mostly admins; viewers consult. |
| **Switches** | Switch inventory + per-switch rack view of ports, native VLAN per port, link to neighbour. | Anyone troubleshooting cabling. |
| **Devices** | Servers, APs, printers — anything that holds an IP. | Inventory keepers. |
| **Topology** | Live graph of switches and their inter-switch links. PNG export. | Everyone — share the PNG in tickets. |
| **Import** *(admin)* | Bulk-load any entity from a CSV file. Dry-run first. | Initial bootstrap and yearly cleanups. |
| **Audit log** *(admin)* | Every create / update / delete, with a diff and a timestamp. | Forensics, post-incident reviews. |
| **Settings** *(admin)* | Sites, rooms. | Org structure. |

## The two flows you'll do most often

### Assigning a new IP

1. Go to **Subnets**, pick the right subnet.
2. Click **Next free IP** — the editor opens with the first unused address
   pre-filled.
3. Set the status (`Assigned` for permanent allocations, `Reserved` to hold
   a slot, `DHCP` if your DHCP server hands it out).
4. Fill in the hostname / MAC / device if you know them.
5. **Save**.

The grid recolours immediately. Anyone else with the page open sees the
change on their next refresh.

### Recording a new switch

1. Go to **Switches** → **New switch**.
2. Set the name (used everywhere — pick a stable convention),
   `port_count` (immutable once set), and optional site/room.
3. **Save** — NetForge auto-generates the N ports as empty rows in the rack
   view.
4. Click into the switch, then click any port to set its mode (access /
   trunk), native VLAN, tagged VLANs and the device it connects to.
5. For inter-switch links: Switches → switch detail → **Links** tab →
   **New link** → pick the two endpoints.

## Tips that pay off

- **Cmd+K / Ctrl+K** opens the global search palette. Type any IP, hostname,
  MAC, switch name or port label. Arrow keys navigate, Enter opens.
- **`?`** anywhere outside a text field shows the full keyboard-shortcut
  list. `F1` works too if your layout doesn't have a direct `?`.
- **Bulk changes** never happen in the UI. Export the entity as CSV, edit
  in Excel, re-import via Import. The dry-run mode will tell you exactly
  which rows are wrong before anything is written.
- **Every change is audited.** No need to keep a personal changelog —
  the Audit log answers "who changed what, when, from where" forever.
- **Light / dark / system theme + FR/EN** are in the top-right corner.
  Settings persist per-browser.

## When something looks wrong

1. Hit **F5** — many "stale data" reports are just an unrefreshed tab.
2. Check the **Audit log** — was the row edited recently?
3. If a CSV import refuses an apparently-valid row, run it again with
   **dry-run** ticked and read the per-row error column.
4. If the topology graph is empty: at least two switches must exist and at
   least one link must connect them.
5. Last resort: contact the team running the server (the same people who
   handed you this guide). Mention the time, your username and the page
   you were on.

## What NetForge will *not* do for you

- It does not poll your switches via SNMP yet (planned for v2). You enter
  port → device associations manually or via CSV import.
- It does not run your DHCP. The `DHCP` IP status is a record, not a
  control — your existing DHCP server still owns the lease.
- It does not push configuration to switches. It's a documentation tool,
  not a config-management one.

---

# Feature reference

The day-to-day reference for operators. The in-app UI keeps the surface
clean and uses small **?** tooltips next to fields that need a hint; this
section goes deeper for anyone who wants the full picture.

## Sections

- [Subnets, VLANs and IP addresses](#subnets-vlans-and-ip-addresses)
- [VRFs and subnet hierarchy](#vrfs-and-subnet-hierarchy)
- [Switches, ports and links](#switches-ports-and-links)
- [Cables](#cables)
- [CSV import](#csv-import)
- [AI features](#ai-features)
- [Snapshot diff](#snapshot-diff)
- [Webhooks](#webhooks)
- [API tokens](#api-tokens)
- [Permissions and audit log](#permissions-and-audit-log)

## Subnets, VLANs and IP addresses

A **subnet** is one IPv4 CIDR block (e.g. `10.0.30.0/24`) tied to a site.
Two subnets that share or overlap a CIDR in the same scope are refused
at creation — see [VRFs](#vrfs-and-subnet-hierarchy) if you legitimately
need overlapping CIDRs in two isolated contexts.

A **VLAN** is a tag (1–4094) with a colour, optionally referenced by a
subnet. VLANs are inventory-only: NetForge doesn't push anything to your
network gear.

An **IP** is a single address inside a subnet. Statuses:

- **reserved** — kept aside, not assigned to any device yet
- **assigned** — given to a device
- **dhcp** — known to be served by DHCP
- **free** — synthesised by the UI for any address in the subnet that has
  no row in the DB; not actually stored

`Next free IP` on the subnet detail view scans the address space and
returns the first usable host. It refuses to scan subnets larger than
`/20` (4096 addresses) — for bigger ranges, the **utilization** widget
gives you the fill rate via aggregated counts instead.

## VRFs and subnet hierarchy

A **VRF** (Virtual Routing and Forwarding instance) is a separate
routing world. Two subnets in different VRFs may share the same CIDR
without conflict; subnets *inside* one VRF still cannot overlap.

**Most installations don't need VRFs** — leave the subnets in the
default *Global* scope. Reasons to create one:

- Two tenants in a shared lab both use `10.0.0.0/16` internally.
- Prod and dev environments mirror each other's IP plan for blue/green
  testing.

The optional **route distinguisher** (RD) is a BGP/MPLS identifier like
`65000:42`. NetForge stores it for documentation purposes but does not
push anything to any router.

### Hierarchy

A subnet can optionally have a **parent subnet**. The child CIDR must
be strictly contained in the parent's, and both must live in the same
VRF. The Subnets list view has a **Tree** toggle that renders the
hierarchy as nested rows; the **List** view stays flat.

You cannot change a subnet's VRF while children still point to it —
detach or move the children first.

## Switches, ports and links

A **switch** has a `port_count`; NetForge auto-generates that many
**port** rows on creation. Each port can:

- be tagged with a `mode` (`access`, `trunk`, `hybrid`, `disabled`),
- carry a native VLAN and a list of trunk VLANs,
- be wired to one **device** (server, laptop, AP, …) via
  `connected_device_id`,
- be linked to another switch port via a **Link** row.

Link endpoints are stored canonically: `port_a_id < port_b_id`. That's
why the editor refuses two endpoints whose IDs would tie or invert.

The Topology view renders inter-switch links as a graph (multiple layout
algorithms available). Click a node or edge to see its details in the
side panel.

## Cables

A **cable** is a sibling of a link, not a column on it. Why: the
physical cable outlives the link it currently realises. When you
re-patch, the same labelled cable now plugs into a different port pair —
the metadata (label, length, vendor, install date) follows the cable,
not the topology row.

The Cable section appears inside the Link editor in edit mode. Leave it
empty if you don't track cable inventory. A cable with no `link_id` is
"in stock".

## CSV import

The Import page accepts one or many CSV files at once (also a `.zip`).
For each file the importer:

1. Detects which entity the headers belong to.
2. Validates every row.
3. Either commits the rows or rolls back if you ticked **Dry-run**.

**Always start with a dry-run** to catch validation errors before
writing anything. The report tells you exactly which rows failed and
why.

Dependency order is honoured automatically: sites first, then rooms,
then VLANs / subnets, then devices / switches, then ports, finally
links. If you're unsure of the column names, click **Download current
data as template** — it exports the entity as a CSV with the exact
header row the importer expects.

### CSV mapping assistant (AI-powered)

If your CSV uses arbitrary column names ("IP Address", "VLAN Tag"…), the
mapping assistant proposes a `csv_column → netforge_field` mapping
based on the headers AND a few sample rows. It also flags **data-
quality issues** it spots in the sample:

- empty required cells,
- malformed CIDR / IPv4 / MAC / VLAN id,
- duplicates in unique columns,
- mixed unit conventions or casing (from the LLM observation).

The assistant is a *suggestion* — review the proposals, then apply
the mapping when you upload.

## AI features

Every AI feature is **opt-in** via `AI_ENABLED` in `.env`. When
disabled, the related UI is hidden. Sub-toggles exist for drafts
(`AI_DRAFTS_ENABLED`) and the scheduler (`AI_SCHEDULER_ENABLED`).

### Ask AI

Natural-language questions about your inventory. The model receives a
JSON snapshot of your entities (sites, rooms, switches, ports, …) plus
your question.

**Lite mode** is a checkbox in the input area. When on, only
identifiers (names, IDs) are sent — no descriptions, notes, MACs or
vendor info. Cheaper and faster, but turn it off if your question is
about content in those free-text fields.

The conversation is single-shot for each turn: the server replays your
recent history on every call (capped at 10 turns to bound tokens). Use
**New conversation** to wipe it.

### AI Advisor

Runs a full review of your inventory and lists weak points (single
points of failure, capacity warnings, security gaps, segmentation
issues, etc.). Output is one **InfraInsight** row per finding,
persisted so you can compare reports week-over-week.

A finding that appears in multiple consecutive runs shows a
**Recurring ×N** badge — useful to spot issues you've been ignoring.

### Drafted actions (NL-to-action)

You describe what you want ("Create VLAN 50 named IoT on site PAR"),
the AI prepares a structured payload, and **you** click Apply to
actually mutate the inventory. Nothing runs without an explicit
operator click. Drafts that fail at apply time stay in the list with
their error message.

### Webhooks for scheduled runs

The AI scheduler can fire a webhook when a periodic advisor or
suggest-links run produces a new finding above a severity threshold —
see the **AI** tab in Settings.

## Snapshot diff

`/api/snapshots/compare?from=&to=` aggregates the audit log between two
timestamps and lists every affected entity. Statuses:

- **created** — exists at the end of the window, didn't at the start
- **updated** — existed before, mutated during the window
- **deleted** — existed before, removed during the window
- **transient** — created AND deleted in the same window (look for
  botched migration scripts)

The window is capped at 90 days for performance.

## Webhooks

Webhooks let an external system react in real time when your inventory
changes. Each delivery is signed with HMAC-SHA256 of the body using the
secret you got at create time.

### Subscribing

Create a webhook with:

- a **URL** (HTTPS recommended),
- a list of **event patterns**: `*` for everything, `port.*` for one
  entity type, or `port.create` for one specific event.

NetForge POSTs a JSON body and three custom headers:

| Header | Meaning |
|---|---|
| `X-Netforge-Event` | The event name (e.g. `port.update`) |
| `X-Netforge-Signature` | `sha256=<hex>` HMAC of the raw body |
| `X-Netforge-Delivery` | Unique id per delivery — log it for replay debugging |

### Verifying the signature (Python)

```python
import hmac, hashlib

def verify(body: bytes, header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header)
```

### When deliveries fire

Webhooks fire **after** the SQLAlchemy session that produced the change
commits. A CSV import in dry-run mode (which flushes + rolls back)
never triggers a delivery. 5xx server crashes also drop pending events
so subscribers don't see ghost mutations.

### Delivery log

Each attempt produces one `WebhookDelivery` row visible from the
webhook's actions menu. Rows older than 30 days are trimmed
automatically.

## API tokens

API tokens are personal credentials for calling the API from a script
or CI job. They **inherit your permissions** — treat them like a
password. Revoke any you stop using.

### Creating

Name + optional expiry date. The plaintext is shown **once** at
creation; we store only its SHA-256 digest. There is no recovery — if
you lose it, generate a new one.

### Using

```http
GET /api/sites
Authorization: Bearer nfp_xxxxxxxxxxxxxxxxxxxxxxxxxx
```

Tokens stop working when:

- you click Revoke,
- the expiry date passes,
- your user account is deleted,
- your role is downgraded below what the endpoint requires.

## Permissions and audit log

Two roles:

- **viewer** — read-only. Browses the inventory and exports, but cannot
  change anything and cannot use the AI surfaces (Ask AI, Advisor, Drafts)
  or access Settings and Audit — those are all admin-only.
- **admin** — full CRUD plus Settings, Webhooks, VRFs, the AI surfaces (Ask
  AI, Advisor, Suggest links, Drafts) and their configuration, audit log,
  and snapshot diff.

Every create / update / delete on a tracked entity (sites, rooms,
vlans, subnets, ips, devices, switches, ports, links) writes one row
into the **audit log** with:

- who (user id),
- what (entity + action + before/after diff),
- when (timestamp),
- from where (IP + user-agent of the request).

Auth-plumbing tables (`users`, `sessions`, `audit_log` itself) are
deliberately *not* audited — it would cause infinite recursion during
login.

The Audit page (admins only) lets you filter by entity, user, action,
and date range, then expand a row to see the field-level diff.

# 12 — End-user guide

NetForge is your team's single source of truth for **IP addresses, VLANs,
subnets, switches and the cables between them**. This page is the half-page
version: enough to be productive on day one. Detailed conventions live in
the other docs (`03-data-model.md`, `08-import-csv.md`, `09-topology.md`).

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

# 3. The Build tab

The Build tab is where you write a lab's definition. Everything on it edits one
YAML document — the stored definition — and this page says what each control
does and which key it writes.

This page does not explain the protocols. Where a setting turns on a netlab
module, the page names the module. What OSPF or BGP then does with it is
[netlab's documentation](https://netlab.tools/modules/).

## Getting there

`/labs/{name}/build`. You need `lab:edit`. Without it the tab says so and shows
nothing else.

Two modes, switched top-right:

- **Visual** — a canvas on the left, an inspector on the right, Save at the
  bottom of the inspector.
- **Text** — the definition as YAML.

Both edit the same definition. Switching discards unsaved changes in the mode
you leave, and asks first.

This tab is the only place to edit a definition. The Overview tab shows the same
topology read-only.

## Save

Save takes the document, writes YAML from it, and sends it to the server. The
server validates by running `netlab create` without deploying anything. If
netlab refuses, the rejection appears above the canvas with netlab's own error
output.

Saving does not deploy. It changes the stored definition and leaves a running
lab alone until you deploy again.

The Save button is disabled until something changes. Once it is dirty you also
get **Discard**, which returns to the stored definition.

Three things can appear beside it:

- **"Not saveable yet"** with a list. The builder found these before it reached
  the server. See [Save blockers](#save-blockers).
- **A notice.** The document is fine, but saving will re-spell part of it. See
  [Text mode](#text-mode).
- **"Definition changed on the server — saving overwrites it."** Someone else
  changed the definition while you edited. Saving wins, and merges nothing.

Leaving the tab or closing the browser with unsaved changes asks first.

## The canvas

### Adding

The **Add** control is split. The left half adds one node of the lab's default
device in a click. The chevron opens a searchable list:

- **Devices** — the supported set, searchable by netlab name or label.
- **Node templates** — saved node fragments, if the deployment has any.
- **LAN segment** — an empty multi-access segment to attach nodes to.
- **From config file…** — build one node from a real device configuration
  ([page 6](06-config-import.md)).

If the lab has no default device, or the catalog does not know the default, the
whole button opens the menu instead. There is nothing sensible to add in one
click.

New nodes take their device's name: `vyos1`, `vyos2`, and so on.

### Linking

Two ways, and they accept exactly the same links:

- **Drag** from the grip on a node to another node or to a LAN segment.
- **Aim** — select a node, pick a target in **Connect to**, press **Link**. The
  list contains only valid targets.

What the builder allows:

- Node to node, including a pair that is already linked — parallel links are
  legitimate.
- A node to itself. netlab gives it two interfaces on one link, and the canvas
  draws a loop. Read the [self-link note](#self-links) before you address it.
- A node to a LAN segment, unless it is already a member.

What it refuses, with the reason:

- Two LAN segments to each other.
- Anything to a stub link — a stub has its one endpoint and no room for another.

**Add stub link** on the node inspector makes a one-endpoint link. netlab
resolves it to a loopback-style interface on that node.

### Selecting and deleting

Click a node, a link, a LAN segment, a stub, or the line joining a node to a
segment. Clicking empty canvas selects nothing, which is how you get back to the
lab settings.

<kbd>Delete</kbd> or <kbd>Backspace</kbd> removes the selection. Deleting a node
removes its links and its group memberships with it.

### Copying nodes

**Duplicate** and **Copy** sit on the node inspector.
<kbd>Ctrl</kbd>/<kbd>Cmd</kbd>+<kbd>C</kbd> and <kbd>V</kbd> do the same, and
the paste button appears on the toolbar once you copy something.

A copy carries the node's settings and its group memberships. It does not carry
links — a copy is a new node, not a second attachment to the same wires. It
lands next to the node it came from.

<kbd>Ctrl</kbd>+<kbd>C</kbd> with text selected on the page copies the text, not
the node.

### Undo and redo

Undo is <kbd>Ctrl</kbd>/<kbd>Cmd</kbd>+<kbd>Z</kbd>. Redo is
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> or <kbd>Ctrl</kbd>+<kbd>Y</kbd>.
The toolbar has a button for each.

Undo covers changes to the document. It does not cover selecting something, and
it does not cover dragging a node — positions are not part of the definition.
Shortcuts do nothing while you type in a field, which keeps a text field's own
undo intact.

Undoing every change back to the stored definition marks the tab clean again.

### Toolbar

Top-right: undo, redo, paste (only with something copied), minimap,
**auto-layout**, the rank direction toggle (left-to-right or top-to-bottom), and
the switch to text mode.

Auto-layout replaces your manual arrangement. There is no undo for it — undo
covers the document, and this is layout.

### Positions and colours are not the definition

Twinlab saves node positions and group colours separately from the definition,
once per lab, shared by everyone who can read it. There is one arrangement, not
one per person.

The Build tab is the only thing that writes them, and Overview renders the same
arrangement read-only. They save as you go — there is no unsaved state for a
position, and moving a node does not make the definition dirty. Renaming a node
or a group carries its position and colour across.

## Lab settings

The inspector shows these when you select nothing. Four tabs, and each tab label
carries a count of what it holds.

### Defaults

- **Default device** — the device new nodes get, and what a node without its own
  device falls back to. Writes `defaults.device`.
- **Global modules** — netlab modules every node inherits. Writes `module`. The
  checkboxes offer the modules some supported device can run. The rest of
  netlab's vocabulary still parses and still saves, it is just not offered. Per
  node, greying does the finer work.
- **BGP AS** — appears once you turn `bgp` on. Writes `bgp.as`.
- **LDP transport (mpls.ldp)** — appears once you turn `mpls` on. Writes
  `mpls.ldp`.

The builder writes the last two as `bgp.as:` and `mpls.ldp:` when there is
nothing else under that module. It folds them into `bgp:` or `mpls:` when the
document carries other keys there.

### VRFs

Declaring the lab's VRFs. Writes `vrfs`. Needs the `vrf` module, and says so
when it is missing.

Type a name and press Add. Each VRF shows how many nodes are in it, and removing
one that has members asks first — the memberships go with it.

You edit `rd`, `rt`, `import`/`export` as YAML beside the name rather than as
four more controls, because netlab derives them when they are absent. They stay
attached to their VRF, so a declaration can never lose its attributes.

You set which nodes are *in* a VRF per node, on the node's Protocols tab.

### Groups

A group broadcasts settings to its members. Writes `groups`.

Type a name and press Add. The inspector expands one group for editing at a
time.

- **Members** — checkboxes over the lab's nodes.
- **Member groups** — a group can contain another group, which then broadcasts
  to its members too. Shown once there is more than one group.
- **Config templates** — custom-config attached to every member ([page
  6](06-config-import.md)). The builder greys a template that does not apply to
  *every* member, and says which member it fails on.
- **Colour** — the dot beside the name. This is canvas styling, saved with the
  layout, and never written into the definition.
- **Advanced properties** — anything else the group broadcasts, such as `module`
  or `bgp.as`.

Some definitions carry settings that sit beside the groups rather than being a
group — netlab reads a groups-level `_auto_create` this way. Those get their own
box below, shown only when they exist.

### Advanced

Everything at lab level the controls do not model. See
[Typed settings and Advanced
properties](#typed-settings-and-advanced-properties).

## Node settings

Three tabs. The Protocols and Advanced labels carry a count of what they hold.

### General

- **Name** — writes the node's key under `nodes`. Renaming carries through
  links, groups and the saved position.

  Two different rules apply, which is worth knowing if the builder refuses a
  rename to a name the lab already contains. Names you *type here* must be
  lowercase letters, digits and underscores, up to 16 characters — no hyphens.
  netlab splits the terse `a-b` link form on the hyphen, so you can only spell a
  hyphenated node in the longer link forms.

  Names *loaded from an existing definition* get netlab's full rule instead:
  letters in either case, digits, underscores and hyphens, up to 16. So a
  hand-written or imported definition keeps its names.

- **Duplicate** / **Copy** — see [Copying nodes](#copying-nodes).

- **Device** — the searchable device picker. Writes `device`. Leaving it empty
  falls back to the lab default, which the control names.

  It will tell you two things. First, that the node has no device and the lab
  has no default, which blocks Save — the builder never guesses a device.
  Second, that the device's default image is not on the host, in which case
  deploy will try to pull it.

- **Modules** — inherits the lab list until you press **Override for this
  node**, which writes `module` on the node. **Use global modules** removes it
  again. The builder greys a module the device cannot run, and names the device.
  A device that runs no routing modules at all says so — it joins links as a
  plain host.

- **Groups** — which groups this node belongs to. Same memberships the Groups
  tab edits, from the other side.

- **Connect to** / **Link** — see [Linking](#linking).

- **Add stub link** — a one-endpoint link on this node.

- **Save as template** — snapshots this node's settings (not its name, not its
  links) into the deployment-wide node library, where the Add menu can stamp it.
  Needs `template:manage`, and the node needs a device.

- **Delete node** — removes the node and its links.

### Protocols

Empty until the node has `bgp`, `mpls` or `vrf`, and says so.

- **BGP AS (node)** — overrides the lab AS for this node. Writes `bgp.as` on the
  node. The placeholder shows the lab value it would otherwise use.
- **MPLS VPN edge (mpls.vpn)** — writes `mpls.vpn`. Needs `mpls`, `bgp` and
  `vrf` all on this node. Without all three the builder greys it and gives that
  reason.
- **VRF membership** — which of the lab's VRFs this node is in. Writes `vrfs` on
  the node. Each membership can add **customer loopback (the site)**, which
  writes `loopback: true` inside it.

Only VRFs declared at lab level appear here. A node in an undeclared VRF blocks
Save.

### Advanced

- **Image override** — the container image. Writes `image`, or `box` if the
  document already used that spelling. These are one setting: netlab accepts
  both and `box` wins, so the builder shows one field rather than two that
  contradict each other.
- **Role** — writes `role`: `router`, `host`, `bridge` or `gateway`, or the
  device's own default. Only a router-role node gets a loopback interface.
- **Loopback IPv4** / **Loopback IPv6** — pin the loopback address instead of
  taking one from the pool. Writes `loopback`.
- **Config templates** — custom-config attached to this node ([page
  6](06-config-import.md)). Writes `config`. The builder greys a template with
  no variant for this node or its device, and says so — attaching one anyway
  would fail the save in netlab's voice. A template the lab does not carry stays
  put and stays removable instead of vanishing.
- **Advanced properties** — everything else.

## Link settings

What a link *is* comes from how many endpoints it has, not from a type you
choose. One endpoint is a stub, two are point-to-point, three or more are a LAN
segment. The inspector changes shape to match.

### Point-to-point

Tabs: General, one per endpoint, Advanced.

**General**

- **Name** — writes `name`, and labels the edge on the canvas.
- **Prefix** — the link's subnet. Writes `prefix`. Accepts a CIDR or the name of
  a declared pool, and empty takes one from the pool.
- **no addressing (L2 link)** — writes `prefix: false`. A checkbox rather than
  an empty field, because empty means "assign me one" — netlab invents
  addressing unless told not to. This is the unnumbered link, the trunk, the LAG
  member.
- **Bandwidth** — writes `bandwidth`, in kbps.
- **MTU** — writes `mtu`, in bytes, 64 to 9216.
- **Delete link**.

**Endpoint tabs** carry their node's name — see below.

#### Self-links

The inspector labels a node linked to itself, and its two endpoints wear `#1`
and `#2` because they share a name.

It needs addressing you choose. netlab derives an interface address from the
link prefix and the node's id, so both ends of a self-link would draw the *same*
address, and `netlab create` fails on the duplicate. Either tick **no
addressing** for an L2 link, or set an IPv4 on each end. The builder points this
out rather than blocking Save, since the server judges it either way.

### Endpoint settings

The same fields on every link shape.

- **Interface name** — the interface name on the device. Writes `ifname`. netlab
  assigns one when it is empty. Pin it when fidelity matters, as an imported lab
  does.
- **IPv4** — this end's address. Writes `ipv4`, overriding what the prefix would
  give it.
- **no IPv4 here** — writes `ipv4: false`. Same reason as `prefix: false`: an
  endpoint left bare on an addressed link gets an address invented for it. On a
  partly-addressed link netlab does that even outside the prefix you pinned. "No
  address" has to be said.
- **IPv6** — writes `ipv6`.
- **Advanced** — anything else this end carries, such as `ospf.cost`.

### Stub link

Tabs: General, the endpoint, Advanced. One endpoint, drawn as a small terminator
on the canvas. netlab resolves it to a loopback interface on the node.

Same General fields as a point-to-point link.

### LAN segment

Tabs: General, Advanced. Three or more endpoints, drawn as a hub.

General lists the members with a remove button each, then the same name, prefix,
bandwidth and MTU fields. Add members by dragging a node onto the segment.

**A segment needs at least three members to save.** With two it is a
point-to-point link, and the inspector says so — connect a third, or delete it
and link the two directly.

A LAN segment also needs a bridge on the host, which Twinlab creates at deploy.
Two labs whose names share their first ten characters can collide there. Twinlab
refuses that rather than let the labs be cross-wired ([page
8](08-troubleshooting.md), `bridge_conflict`).

### LAN membership

Selecting the line between a node and a segment: that endpoint's fields, plus
**Remove from segment**.

## Typed settings and Advanced properties

This rule explains a good deal of the UI.

The builder models a core of netlab's vocabulary with real controls. Every key
outside that core stays exactly as written, and you edit it as YAML under
**Advanced properties**. That happens at whichever level the key belongs to —
lab, node, group, link or endpoint. The builder drops nothing and rewrites
nothing.

A key lives in one place or the other, never both. So:

- The builder refuses a key the controls own if you put it in Advanced
  properties, and the message names the control to use instead: *"use the Prefix
  field"*, *"use the member checkboxes"*.
- If a document already carries such a key in a shape the controls cannot edit,
  the control disappears and a line says *"managed in Advanced properties"*.

Advanced properties is a YAML mapping with an **Apply** button. Changes land in
the document when you apply them, not as you type. Applying checks that it is
valid YAML and that no key belongs to a control. It does not check the content —
the server's dry `netlab create` does that on save.

The split is per key, not per block. A `bgp:` carrying `as` and `router_id`
gives you the AS control and keeps `router_id` in Advanced. One key going
unmodelled does not send the whole block there.

Tab labels carry counts, so you can see that a node has three advanced
properties without opening the tab.

## Save blockers

The builder finds these before it reaches the server. Each names what to do.

- The lab has no nodes.
- A node has no device and the lab has no default. A device is intentful, and
  the builder never guesses one.
- A node is in a VRF that is not declared at lab level.
- A LAN segment has fewer than three members.
- An advanced property duplicates a key a control already writes.
- A link's advanced property names a declared node — the builder would read that
  back as an endpoint.
- A group member is neither a declared node nor another group. (Waived for a
  group that sets `_auto_create`, where netlab creates the members itself.)
- Some links are in named lists and others are not. netlab's `links:` is either
  one list or a mapping of named lists, never a mix.

## Text mode

The definition as YAML, with syntax highlighting and a lint gutter.

The lint marks YAML that will not parse. It does not gate Save — the server's
dry `netlab create` is the real validator, and it catches things a YAML linter
cannot. When netlab rejects a definition, its output appears as a panel above
the editor rather than as a marker in the gutter. It reports no line numbers.

**Reset** returns to the stored definition.

Switching back to Visual re-reads the document. Two things can happen:

- **A notice.** The document is representable but will be re-spelled on save — a
  link group comes back expanded, an `interfaces:` link is rewritten as the
  equivalent dict form. netlab expands both identically, and the builder says so
  rather than changing your file quietly.
- **The builder refuses it.** The canvas cannot represent every definition. The
  Build tab then lists the reasons, offers the text editor, and shows a
  read-only preview of the topology, so the tab is still worth opening.

The builder rejects a definition only where netlab itself would:

- invalid YAML,
- a link entry that is only attributes,
- `interfaces:` mixed with node keys,
- an endpoint naming a node that was never declared,
- a name outside netlab's identifier rule.

Plus one rule of its own: a device outside the supported set. That last one is
policy, not a limitation. Everything else netlab accepts, the builder parses.

## What the builder will not do

These stay advanced properties on purpose, because netlab's own behaviour there
is richer than a control would suggest: `vlans:`, `plugin:`, address pools, link
`tc:`, `tools:`, `validate:`, and node `cpu` / `memory` (libvirt-only, so inert
here).

The server refuses two of those outright rather than ignoring them. It refuses
`tools:`, whose side containers Twinlab never starts. It also refuses link and
interface `tc:`. netlab applies that during `netlab up` — the step Twinlab
replaces — and impairment here is the netem API's job ([page
4](04-operating.md)). `validate:` is not refused. It is simply unused, since
Twinlab runs its own test suites ([page 5](05-test-suites.md)). [Page
9](09-definition-reference.md) has the full list of what the server refuses, and
why.

Devices outside the supported set are not offered, and a definition naming one
will not open on the canvas. It still edits as text and may well deploy, but
Twinlab promises nothing about it.

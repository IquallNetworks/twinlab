# 6. Real configurations in

Three ways to start from something that already exists: importing real device
configurations, the template library, and custom-config templates.

## Config import

You supply the running configurations of real devices, plus the wiring between
them. You get a lab that stands up carrying those configurations.

### What it promises

Every line of every source configuration lands in exactly one of three places:

| Bucket | What happens to it |
| --- | --- |
| **modeled** | becomes definition structure — nodes, links, addressing — and netlab regenerates it |
| **carried** | applies to the node verbatim, as custom config |
| **quarantined** | Twinlab keeps it and shows it, and deliberately does not apply it |

Nothing falls off the edge. That partition is the whole reason to trust an
imported twin: you can point at any line of the original and say where it went.

A modeled line never also rides the carry, because netlab already regenerates
it. Otherwise you would configure the same thing twice, from two sources.

### What you need first

**A configuration per device**, as the device prints it. Twinlab parses VyOS
(`show configuration commands`) and IOS-style (`show running-config`).

That parser set is narrower than the set of platforms Twinlab can deploy, and
the two lists do not line up:

- **VyOS** imports *and* deploys. It is the only platform where import → deploy
  → config diff works end to end.
- **FRR, RouterOS 7, linux, bird and dnsmasq** deploy, but Twinlab cannot
  import them yet.
- **IOS** imports, but Twinlab does not support the platform. An imported IOS
  lab is a real definition that Twinlab promises nothing about.

**The wiring.** You must know which interface connects to which. Read on.

### The wizard

`/labs/import`, or the **Import** button on the labs page. Four steps:

1. **Sources** — the configuration files, each tagged with its device type.
2. **Wiring** — which interface connects to which.
3. **Analyze** — what Twinlab modeled, renamed, carried and quarantined.
4. **Review and create**.

Creating composes three calls in a fixed order: create the lab, store the custom
config, then store the definition. That order matters, because the definition
references the carry templates and the server validates those references.

### Wiring is something you declare

This is the part Twinlab cannot guess, so it gets its own section.

**A link exists because you said so.** Twinlab does not infer adjacency from
addressing. Topology is intent, and two interfaces in the same subnet are
evidence, not proof.

Each wiring entry lists endpoints as `node:interface`, using the **source**
interface names. The count decides the kind:

- Two endpoints make a point-to-point link.
- Three or more make a LAN.

**A wire whose endpoints carry no addresses becomes an L2 link.** That is how
you express an unnumbered core, a trunk, or a LAG member — links that addressing
can never reveal, because there is no address to join on. LAG needs nothing
special: wire the members, and the bundle rides the carry.

On a **mixed** wire, where some endpoints have addresses and some do not,
Twinlab marks the unaddressed ends explicitly. netlab would otherwise invent an
address for them, and not even from the pinned prefix.

Twinlab does offer a suggestion. It proposes wiring from the subnet join and
prefills the editor with it, and it consumes only what you confirm. Advice, not
inference.

#### What stays automatic

Three things are not adjacency, so Twinlab still does them for you:

- Twinlab pins loopback addresses.
- Twinlab quarantines management interfaces.
- **An addressed interface you did not wire becomes a stub.** That is the
  boundary of the twin — the edge where the real network continued and your lab
  stops.

#### What Twinlab refuses

Contradictions are errors, not guesses. `wiring_invalid` covers:

- an unknown node or interface,
- an interface wired twice,
- a self-link,
- a loopback or management endpoint,
- an entry with fewer than two endpoints.

`wiring_conflict` covers endpoints in different subnets. That is usually a mask
typo, caught before it becomes a lab that quietly does not work.

Both errors name the offending entry.

### Quarantine

Four classes, and the vocabulary is closed:

| Class | Why Twinlab holds it back |
| --- | --- |
| `mgmt` | management addressing and routes point at your real network |
| `auth` | credentials, keys, AAA servers |
| `telemetry` | syslog, SNMP, streaming targets — a lab should not phone home |
| `hardware` | platform specifics with no meaning in a container |

Quarantined lines stay in the lab and stay visible. Twinlab simply does not
reference them from the definition, so nothing applies them.

**Twinlab never quarantines routing policy, ACLs, QoS or non-management VRFs.**
They carry and they apply, because they are the network's own behaviour and they
are usually the reason you built the twin.

### Names

netlab node names obey a narrow rule, so some hostnames change. Twinlab renames
only when it must, and tells you every time.

- **Hyphens are fine** and stay.
- A leading non-letter, or a dot, forces a rewrite.
- Names truncate at 16 characters.

Truncation can collide. Two hostnames that differ only past character 16 produce
`duplicate_node`, and you resolve it by naming that node yourself.

### Checking fidelity afterwards

Once you deploy the imported lab, **config diff** compares the running
configuration against the source line by line. It classifies each comparable
line as matched, missing or extra. It accounts for quarantine, and it
recomputes the interface-name join itself.

It is informational. It never gates anything. It is the answer to "is this twin
actually like the original", asked at any time.

### Importing a single node

The builder's **From config file…** adds one node from one configuration.

It arrives unattached, keeping its source interface names, because a single
configuration implies no links. Its carry and quarantine go into the lab's
custom config, unreferenced until you attach them.

## The template library

Two collections with separate namespaces.

**Network templates** are whole topologies. The built-in ones mirror the files
in `examples/`. Your own come from publishing a lab, and a published lab is a
**live view** of its definition rather than a snapshot — edit the lab and the
template follows.

**Node templates** are single-node fragments, offered in the builder's Add menu.
A stamped node is indistinguishable from one you built by hand, because the
stamp goes through the same parser.

Where you meet them:

- **"Start from"** in the create-lab dialog, for a network template.
- **The Add menu** in the builder, for a node template.
- **"Save as template"** on a node's General tab, to add one.

Publishing needs `template:manage` and a description, and the lab must have a
definition. Reading needs no permission at all. Deleting a lab withdraws its
template.

There is no "instantiate" button. Starting from a template creates a lab and
stores the template's content, which is two ordinary operations.

## Custom-config templates

Configuration Twinlab pushes to nodes beyond what netlab generates, as Jinja2
templates rendered per node.

A template is a **record** with a name, a description and one or more
**variants**. Each variant has a scope:

| Scope | Applies to |
| --- | --- |
| node | one node, by name |
| device | every node of that device type |
| universal | every node |

Lookup follows netlab's own precedence: node first, then device, then universal.

### Applicability, and why the picker greys things

One rule decides whether a template applies to a node. A variant matches by node
name, else by device, else universally. For a **group**, the template must cover
**every** member, because a group attaches to all of them.

The builder's picker offers non-applicable templates greyed out, with the
reason, rather than hiding them. That is deliberate. Attaching an MPLS-TE
template to a VyOS node would fail the save in netlab's voice, minutes later and
far from the cause. Greying it says so at the point of the mistake.

A template the lab does not carry stays listed and stays removable, so a
definition that references something missing does not silently lose it.

### Where import meets this

Config import writes its results here. The carry becomes an `imported` template
with a variant per node, and the definition references it by name. Quarantined
lines go beside it, unreferenced.

That is the join between the two halves of this page: import produces custom
config, and custom config is what applies it.

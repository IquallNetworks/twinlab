# 9. Definition reference

What Twinlab accepts in a definition, what it refuses, and what it writes in
without asking. The reference for text mode and for anyone authoring YAML by
hand.

## It is netlab YAML, nearly

A Twinlab definition is a netlab topology. The vocabulary — `provider`,
`defaults.device`, `module`, `nodes`, `links`, `groups`, `vrfs` and the rest —
is [netlab's](https://netlab.tools/topology-overview/), and this page does not
duplicate it.

Twinlab's dialect differs in three ways:

1. It **refuses** a small set of otherwise-legal keys.
2. It **writes in** the keys that belong to the lab record.
3. It **normalizes** the text when it stores it.

## Keys Twinlab refuses

Each of these is a legal netlab key that Twinlab rejects at save time with
`unsupported_directive`.

| Key | Why | Instead |
| --- | --- | --- |
| `tools:` | Twinlab never starts netlab's side containers | run the tool yourself against the lab |
| `defaults.netlab.up`, `defaults.netlab.down` | arbitrary shell from a stored definition, on a multi-user server | nothing — this is a deliberate refusal |
| `defaults.providers.clab.bridge_type: ovs-bridge` | Twinlab's host-preparation sidecar creates Linux bridges | use the default bridge type |
| link and interface `tc:` | netlab applies `tc:` during `netlab up`, the step Twinlab replaces | the impairment API — [page 4](04-operating.md) |

**Twinlab refuses rather than ignoring.** That is the point of the list.
Accepting a key and silently dropping it is what people expect, and it is worse:
you would get a lab that quietly is not what you asked for. The only bug in the
old behaviour was the silence.

Two deliberate non-refusals are worth knowing:

- **`defaults.tc.enable` and a bare, knob-less `tc:` are fine.** You may
  legitimately name a node `tc`, and Twinlab will not refuse a definition over a
  name collision.
- **`validate:` is not refused.** Twinlab simply does not use it, because it
  runs its own test suites — [page 5](05-test-suites.md). netlab's own
  validation is not wired up.

## Keys Twinlab writes

When you save, the server pins the record's own identity into the text:

| Key | What it becomes |
| --- | --- |
| `name` | the lab's name, always |
| `addressing.mgmt.ipv4` | the management `/24` reserved at create |
| `addressing.mgmt._network` | a distinct Docker network, so concurrent labs do not share a management bridge |

The name is not the definition's to choose. It is the lab's durable identity,
and Twinlab overwrites whatever the text says.

The management subnet is different: **an explicit `addressing.mgmt.ipv4` of your
own wins.** `_network` is only set when absent, so an explicit choice survives
there too. Other `addressing.mgmt` keys are left alone.

The consequence to expect: **what you get back is not byte-identical to what you
sent.** Save a definition and read it again, and it will carry keys you did not
write.

## Normalization

Twinlab re-serializes the definition when it stores it. Comments and formatting
do not survive.

That also explains a drift behaviour. Reformatting a deployed lab's definition
does not flag it as drifted. Twinlab compares the two after normalization, so
cosmetic changes vanish and only a real change counts.

## Naming rules

Both lab names and node names obey netlab's identifier rule:

> A leading letter or underscore, then letters, digits, dash or underscore. At
> most 16 characters.

Hyphens are legal. Dots are not.

**A lab name must start with a letter**, which is narrower. The name prefixes
the lab's containers and Docker networks, and those have their own rule.

The visual builder is stricter again about names *you type into it*: lowercase
only, no hyphens. A hyphenated node cannot use netlab's terse `a-b` link form.
The builder still loads and keeps any name netlab accepts.
[Page 3](03-build-tab.md) explains that split.

## What the builder models

Relevant if you move between text mode and the visual builder.

The builder has real controls for a core of the vocabulary, and keeps every
other key verbatim under **Advanced properties**. Round-tripping a definition
through the builder does not lose anything, and a regression suite guards that
invariant.

A save may rewrite the document in two ways. The builder reports each as a
notice rather than doing it quietly:

- A **link group** comes back expanded, exactly as netlab would expand it.
- An **`interfaces:`** link is re-spelled as the equivalent dict form. netlab
  expands both identically.

[Page 3](03-build-tab.md) has the full list of what has controls, what stays in
Advanced, and what blocks a save.

## Things that are not in the definition

Twinlab stores several things *about* a lab that its definition never carries.
Worth knowing when you export, publish or diff one:

| What | Where it lives |
| --- | --- |
| Node positions and group colours | the lab's layout, shared per lab |
| Test suites | the lab record |
| Custom-config templates | the lab record |
| Impairment | live qdisc state on the running containers only |

So a definition on its own describes the topology, not the whole lab. Publishing
a lab as a network template shares the definition, with the record's own pins
stripped so another lab can instantiate it.

## Worked examples

Three definitions in `examples/`, each demonstrating something different:

| File | Shows |
| --- | --- |
| `mpls-l3vpn.yml` | a VyOS MPLS L3VPN core — OSPF, LDP, MP-BGP VPNv4, groups, VRFs |
| `campus-lan.yml` | multi-access LAN segments, a stub link, named links, explicit bandwidth and MTU |
| `mixed-nos.yml` | every supported platform in one lab, in a full OSPF mesh |

All three are fully representable in the visual builder, and the builder's own
regression checks parse and re-emit them.

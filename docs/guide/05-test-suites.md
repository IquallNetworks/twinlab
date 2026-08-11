# 5. Test suites

Assertions that run against a deployed lab. Is OSPF up? Did the VPN route
arrive? Does this ping work?

## What a suite is

A test suite is **data stored on the lab**, not code. Each test runs a command
on a node, optionally parses the output, and asserts something about it. Twinlab
never sends suites to netlab — this is Twinlab's own validation, not
`netlab validate`.

Suites live on the lab record, so they survive a destroy and a redeploy. You
author them as JSON on the **Operations** tab, under **Edit suites**.

Every test follows the same pipeline:

> **render** the command per node → **execute** it on that node → **parse** the
> output → **assert** against it

## A first suite

The smallest useful thing. Two VyOS routers, and you want to know OSPF came up:

```json
{
  "convergence": {
    "stage": "config-time",
    "description": "The core is converged.",
    "tests": {
      "ospf_adjacency": {
        "nodes": ["r1", "r2"],
        "wait": 240,
        "run": {
          "command": "vtysh -c \"show ip ospf neighbor\"",
          "expect": { "contains": "Full" }
        }
      }
    }
  }
}
```

Reading it outward: `convergence` is the suite, `ospf_adjacency` is one test,
and the test runs on `r1` and `r2`. The command runs on each of them, and each
node produces its own result.

`wait` is the convergence knob. It polls up to that many seconds for the
assertion to hold, rather than failing on the first attempt. Protocols take time
to come up, so a routing assertion nearly always wants one. `0` means a single
attempt.

## Commands, and the mistake everyone makes once

A command runs over whatever transport netlab uses for that device. **For a
container-based device that transport lands in the container's shell, not the
network OS prompt.**

So a VyOS command written the way you would type it at the router:

```
ping 10.0.0.2 vrf blue count 5
```

reaches Linux's `/bin/ping`, which has no `vrf` flag. The test sees an error or
empty output and you spend an hour wondering why.

`mode` names the language you wrote the command in:

| `mode` | Meaning |
| --- | --- |
| `shell` (default) | send the command verbatim to whatever the transport reaches |
| `cli` | the command is in the device's own CLI, and Twinlab wraps it to get there |

With `mode: "cli"`, Twinlab rewrites the command per device — a VyOS operational
wrapper, `vtysh -c` for FRR, `birdc`, and so on. A device with no CLI of its own
(`linux`, `dnsmasq`) refuses `cli` with a 422 rather than guessing.

The results show the **rendered and adapted** command, so you can always see
what actually ran.

Both spellings are legitimate. `vtysh -c "show ip ospf neighbor"` as a shell
command is fine and explicit. `mode: "cli"` is better when the idiom is awkward
to wrap by hand, as on RouterOS.

### interactive

`"interactive": true` runs the command in a real interactive session rather than
a one-shot. Two cases need it:

- A device whose operational mode comes from an interactive login shell.
- A command that a one-shot channel truncates, such as a long `ping ... repeat`.

## Templating with facts

Commands and every string inside `expect` are Jinja2, rendered per node against
the lab's facts — netlab's own view of each node. So one test covers every node:

```json
{ "command": "ping -c 3 {{ nodes.r2.loopback.ipv4 | address }}" }
```

Hard-coded addresses go stale the moment addressing changes. Facts do not.

`address` is the one filter the namespace ships. netlab carries addresses in
CIDR form, and most commands want the address without the prefix length.

### Two tiers, and the path tells you which

Twinlab partitions the fact namespace, on purpose:

- **The promised core** is stable contract: identity, `mgmt`, `loopback`,
  `interfaces` (with `neighbors`), and the `ospf`, `bgp`, `ldp` and `vrfs`
  subtrees. `{{ node.ospf.router_id }}` will keep working.
- **`_extras`** holds every other key verbatim, with no promises.
  `{{ node._extras.mtu }}` renders today and may break when netlab changes.

Both work. The path tells you which risk you took.

**An undefined value is an error, not an empty string.** A typo fails loudly
instead of silently asserting against nothing. That also means the old spelling
of a key that moved into `_extras` fails rather than quietly emptying.

The **Facts** viewer on the Operations tab shows exactly what a node offers.

Twinlab checks your templates when you save the suite, and dry-renders them when
the lab has facts. A broken template is a 422 that names the suite, the test and
the field.

## One suite, several platforms

`run` is either one case for every node, or a **map keyed by device**:

```json
"run": {
  "vyos":      { "command": "vtysh -c \"show ip ospf neighbor\"",
                 "expect": { "matches": "(?s)Full.*Full.*Full" } },
  "frr":       { "command": "vtysh -c \"show ip ospf neighbor\"",
                 "expect": { "matches": "(?s)Full.*Full.*Full" } },
  "routeros7": { "command": "/routing ospf neighbor print terse", "mode": "cli",
                 "expect": { "matches": "(?s)Full.*Full.*Full" } },
  "bird":      { "command": "birdc show ospf neighbors",
                 "expect": { "matches": "(?s)Full.*Full.*Full" } }
}
```

One test, four platforms, each asserted in its own idiom. A node whose device
has no case reports `skip` rather than failing, so a mixed lab needs no
per-platform suites.

## Parsing

Set `parse` when you want to assert over structure instead of text:

| `parse` | Use |
| --- | --- |
| `json` | commands that emit JSON, such as `vtysh -c "show ip ospf neighbor json"` |
| `textfsm` | text output, parsed with ntc-templates plus Twinlab's own templates |

A missing template or a failed parse is an `error` result. Twinlab never falls
back to raw text quietly, because an assertion that silently changed what it
asserted over is worse than a failure.

## Assertions

Exactly one per test:

| Matcher | Asserts |
| --- | --- |
| `contains` | a literal substring of stdout |
| `not_contains` | the substring is absent |
| `matches` | a regular expression against stdout |
| `compare` | a structured comparison over **parsed** data |

`compare` and `parse` go together, and Twinlab refuses one without the other.
The comparison is a nested partial match by default, so you name only the fields
you care about. It also takes `_mode: strict` for exhaustiveness and numeric
operators such as `"<15"`.

A `compare` result carries a structured diff of what complied, what was missing
and what was extra. That is usually faster to read than a regex failure.

## When suites run

`stage` controls **automatic** execution only:

- **`config-time`** suites also run after a configure, and gate it. If one
  fails, the lab stays deployed and the job reports `validation_failed`. The
  deploy worked. The network did not converge.
- **`runtime`** suites run only when you ask.

Any suite runs on demand from the Operations tab, whatever its stage. Running
one needs `lab:validate` and a running lab — the **Run** button is disabled
otherwise, and says "Run is available while the lab is running".

A skipped config-time gate keeps the previous verdict rather than resetting it.

## Reading results

Results persist per suite, so the panel shows the last run.

| Status | Meaning |
| --- | --- |
| `pass` | the expectation held |
| `fail` | the command ran, the expectation did not hold, and `wait` expired |
| `error` | the command could not run, render or parse |
| `skip` | the node's device has no case in a device-keyed test |

`fail` and `error` are worth distinguishing. `fail` is a finding about the
network. `error` is a problem with the test.

Each result carries the rendered command, the captured output, what it expected,
and the structured diff when a `compare` decided it.

## Worked examples

Two suites in `examples/` are worth reading before writing your own:

- **`mpls-l3vpn.test-suites.json`** — a VyOS MPLS L3VPN core, with every address
  rendered from facts.
- **`mixed-nos.test-suites.json`** — the fuller reference. It carries
  device-keyed cases across four platforms, `parse: json` with `compare`,
  `parse: textfsm` with `compare`, and an `interactive` case. It asserts the
  every-platform lab and passes 9 out of 9 live.

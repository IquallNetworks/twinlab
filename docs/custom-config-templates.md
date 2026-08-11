# Custom-config templates: the structured remodel (contract delta 27)

Decision record, 2026-08-07. Approved direction: remodel now, while the v1.0 contract has no
external consumers (the release train — PyPI publish + tag — is still the last ROADMAP item).

## The defect

Custom-config templates (netlab's `config: [name]` hook — the seam for config netlab has no
module for) were stored as a raw `{relpath: content}` fileset, per lab, with the shipped
built-ins beside it. The **path did double duty as the storage key and the entire metadata
model**: name, tier, and device scope were all encoded in one string, and every consumer
re-derived them independently and badly:

- The builder's template picker offered every template on every lab. `mpls_te`/`ip_sla` ship an
  `ios.j2` variant only, so attaching one to a VyOS node failed two steps later, at the PUT's
  dry `netlab create`, in netlab's voice ("Cannot find mpls_te configuration template …").
- A dir-form user template `nat/vyos.j2` was offered under the non-name `nat/vyos` (the
  `config:` reference is `nat`).
- Config import's per-node carry templates (`imported/pe1.j2`) were offered on **every** node —
  pe1's running config attachable to pe2.

All three are one disease: applicability was never modeled, only spelled into filenames.

## The model

A template is a record; the fileset is derived, not stored:

```
ConfigTemplate:
  name         — the `config:` reference a definition uses. [A-Za-z_][A-Za-z0-9_-]*, ≤64.
  description  — user-facing; may be empty.
  tier         — builtin | user (derived: builtins live in code, user records on the lab row).
  variants     — ≥1 of {scope, source}, scope exactly one of:
                   node: <name>      applies to that one node
                   device: <slug>    applies to any node of that catalog device
                   universal         applies to any node
```

The three scopes are not invented — they mirror netlab's own `first_found` lookup order for
`config: [X]`, which is what makes precedence free:

| Scope | Materialized as | netlab candidate it hits | Precedence |
| --- | --- | --- | --- |
| node `n` | `X/n.j2` | `X/{inventory_hostname}.j2` | highest |
| device `d` | `X/d.j2` | `X/{netlab_device_type}.j2` | middle |
| universal | `X.j2` | `X.j2` | lowest |

"The pe1-specific override beats the vyos variant beats the generic one" needs zero code of
ours — it falls out of the filenames we emit and netlab's own search order.

**Applicability is one rule, used everywhere** (picker filter, group intersection, greyed-out
copy): *a template applies to a node if some variant matches it (node name, else device, else
universal); it applies to a group iff it applies to every member.* Templates that don't apply
are **greyed with the reason, not hidden** — consistent with how the builder greys
device×module combinations. Members of a group resolve transitively through nested groups; a
member that can't be resolved to a device (an `include:` node, an `_auto_create` name) only
matches a universal or node-scoped variant.

## Materialization: the catalog slug IS the filename

Variants are keyed by the **catalog device slug**; the backend materializes the fileset at the
one boundary where netlab needs files (`_config_fileset` → runner / `netlab create` workdir).
Probed against the installed netlab (2026-08-07, generated inventory group_vars):
`netlab_device_type` resolves to exactly the catalog slug for all six supported devices —
vyos/frr/linux by fallback from `ansible_network_os`, routeros7/bird/dnsmasq explicitly. So
materialization is identity (`X/<slug>.j2`), pinned by a drift-guard test that runs a probe
`netlab create` over the whole catalog and checks the resolved type per device. If a netlab
upgrade ever breaks identity, the guard fails and the materialization map gains an explicit
alias entry — the *contract* (slugs) doesn't move.

**Deliberate narrowing:** netlab's lookup would also match `X/linux.j2` for bird/dnsmasq nodes
(their `ansible_network_os` is `linux`, a lower-precedence candidate). The picker does NOT
honor that aliasing — applicability is slug equality only. Scoping is intent: a template meant
for bird declares a bird variant, even if the source is identical. Materializing only the
`netlab_device_type` form keeps what-we-emit consistent with what-we-offer.

## What the remodel deliberately drops

No arbitrary-relpath side door. netlab's ~24 lookup forms beyond the three scopes, examined:

- **Provider-scoped variants** (`X/vyos-clab.j2`) — vacuous under clab-only Twinlab.
- **`.cfg` (non-Jinja) sources** — expressible later as a `format` flag on a variant if ever
  wanted; not a reason to keep raw paths.
- **Dotted spellings** (`X.<host>.j2`) — alternate spellings of node scope.
- **Custom deploy task lists** (`X/deploy.yml`) — user *code* executing in the runner. Test
  suites drew the "all data, no user code" line deliberately; losing this form is a feature.

Two storage models forever is the real cost of a side door: the picker would still face
unclassifiable paths, which is the disease being cured.

## No OS-version axis

netlab models major OS versions as separate devices (`routeros` vs `routeros7`, `cumulus` vs
`cumulus_nvue`, the ios family) — when a version changes behaviour enough to break config
generation, upstream splits the device, and everything version-sensitive Twinlab owns (template
variants, netmiko device_type, TextFSM platform, import parsers, suite device keys) is already
keyed on the device slug. Minor versions ride the image tag (the node `image` override).
Adding an `os_version` field would mean four new matching rules with no netlab counterpart to
anchor them. If a supported NOS ever diverges within one netlab device, the answer is an
upstream device split, not a Twinlab version axis.

Related decision (same discussion): the catalog keeps **one default image + free-text
override** — no curated per-device image list.

## Built-ins under the model

`mpls_te`/`ip_sla` become records with one device variant each, labeled `ios` — a label that
matches no catalog device since IOL's withdrawal (2026-08-05), so they apply to no node and the
picker greys them everywhere with the reason. That is the honest state; they remain because
they ARE the built-in library and the mechanism is device-agnostic. Builtin variant labels are
trusted code (packaged filename stems) and bypass the catalog gate that user variants get.
A user template may not reuse a builtin's **name** (409) — replacing the old path-prefix
reservation with plain name equality.

## Config import under the model

`imported/pe1.j2` is not a legal template *name*, so import emits **one record `imported`**
with a node variant per carry node, and **one record `imported_quarantine`** with a node
variant per quarantined node — materializing to `imported/pe1.j2` / `imported_quarantine/pe1.j2`.
The carry paths are byte-identical to the old scheme, so existing definitions' direct-path
references (`config: [imported/pe1.j2]`, netlab's `endswith('.j2')` fast path) keep resolving
against the materialized fileset — no migration of stored definitions.

Quarantine stops being a magic unreferenced file and becomes an ordinary node-scoped template:
attachable *deliberately, per node* — an improvement, since consciously re-applying a
quarantined class (e.g. auth) to one node is a legitimate act, while accidental broadcast was
the old failure mode. (Old scheme's quarantine relpath `imported/<n>.quarantine.j2` migrates to
the `imported_quarantine` record; its materialized path changes, but nothing referenced it.)

The cleaner definition emit — `config: [imported]`, letting netlab's per-node lookup resolve —
is adopted only if the *create-time* existence check walks the hostname form the way the
push-time lookup does (live checkpoint during implementation); otherwise import keeps
direct-path references, which the same materialization serves.

## Not absorbed: the delta-21 template library

Considered and rejected. Network/node templates are authoring seeds the **client composes** at
create/stamp time — global, never touching netlab; custom-config templates are Jinja rendered
**per node by netlab** at configure time — per-lab, riding the config push. The defects being
fixed here don't exist there: a node template already pins its own `device`; a network template
is a whole lab. Homonyms, not one concept. The systems stay distinct; UI copy distinguishes
"Config templates" (this system) from the library's "Templates".

## Wire and storage

`GET /labs/{name}/custom-config` → `{templates: [{name, description, tier, variants:
[{device?, node?, source}]}]}` — one merged list, builtins first. `PUT` takes the user tier
only: `{templates: [{name, description, variants}]}`, full replace as before. A variant's
scope is spelled by presence: `device` XOR `node` XOR neither (universal).

Validation: name rule + uniqueness; per-template variant uniqueness per scope key, at most one
universal; user `device` must be a catalog slug; `node` names structurally valid (netlab id
rule) but NOT checked against the definition (labs author incrementally; import writes
templates before the definition PUT — compose order is contract); a node variant whose
materialized filename would collide with a device variant's in the same template is rejected;
source ≤64KB (the node-template bound). Shape violations are 422s; a builtin name collision
stays 409 `builtin_template_shadowed`.

Storage: `labs.custom_config` JSONB holds the user records list verbatim. Alembic migration
0020 reshapes existing rows — flat `X.j2` → universal variant of `X`; `imported/<n>.quarantine.j2`
→ node variant of `imported_quarantine`; `X/<seg>.j2` → device variant when `<seg>` is a
catalog slug, else node variant. All existing data is Twinlab's own (import output + test
fixtures use exactly these forms); an unmappable path fails the migration loudly rather than
guessing.

**What does not change:** the runner contract and `netlab create` workdir write still receive
a `{relpath: content}` fileset — now rendered from records at the boundary; PUT keeps
full-replace semantics; the PUT dry `netlab create` stays the real validator of `config:`
references; templates stay per-lab (a lab remains self-contained; cross-lab sharing is the
delta-21 library's job).

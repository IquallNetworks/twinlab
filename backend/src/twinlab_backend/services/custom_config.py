"""Custom-configuration templates: the seam for config netlab does not model.

netlab's 19 modules cover topology + control-plane routing/switching; features
like MPLS-TE, IP SLA, QoS, ACLs, NAT, multicast and telemetry have no module on
any NOS. netlab's own answer is the custom-configuration hook: a node/group
`config: [name]` attribute renders a per-node template and pushes it via
`netlab initial`. Twinlab exposes that hook in two tiers:

- **built-in** templates authored and shipped here, non-deletable, identical
  for every lab (MPLS-TE and IP SLA are the first two); and
- **user** templates stored per-lab on the record.

Since contract delta 27 (design record: docs/custom-config-templates.md) a
template is a STRUCTURED RECORD — name, description, and >=1 variants each
scoped by exactly one of `node` (that one node), `device` (any node of that
catalog device), or neither (universal). The scopes mirror netlab's own lookup
precedence for `config: [X]` — node beats device beats universal — so
precedence needs no code here: it falls out of the filenames `materialize`
emits (`X/<node>.j2` | `X/<device>.j2` | `X.j2`) and netlab's `first_found`
order over them.

The netlab-facing `{relpath: content}` fileset is DERIVED, never stored: both
tiers are materialized into one fileset per configure/create and the runner
stays a generic executor. Materializing `X/<device>.j2` relies on netlab's
`netlab_device_type` resolving to exactly the catalog slug for every supported
device (vyos/frr/linux by fallback from `ansible_network_os`; routeros7/bird/
dnsmasq explicitly) — pinned by a drift-guard test over a probe `netlab
create`, so a netlab upgrade that breaks the identity fails there, not by
silently materializing a filename the lookup never visits.

Built-in template sources live packaged as `builtin_templates/<name>/<stem>.j2`
where the stem is the variant's device label — trusted code, allowed to name a
non-catalog device (both current builtins ship `ios` only, which since IOL's
withdrawal applies to no catalog node; clients grey them with the reason).
Loading is a file-I/O boundary, so it returns a typed Result; the app fails
fast at startup on error.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable

from twinlab_backend.result import Err, Ok, Result

# The built-in library, as (config name, one-line description) pairs. Each name
# maps to a `builtin_templates/<name>/` directory of per-device `.j2` variants.
# Keep the description user-facing: it is what the UI shows for a built-in.
_BUILTIN_SPECS: tuple[tuple[str, str], ...] = (
    # Both ship an `ios` variant only. Cisco IOL left the supported device
    # set 2026-08-05 (CML licensing — ROADMAP 17.1), so these currently target
    # no catalog device; they stay because they ARE the built-in library and
    # the mechanism they demonstrate is device-agnostic — netlab picks the
    # variant matching whatever device a node declares.
    (
        "mpls_te",
        "MPLS-TE: an RSVP-TE tunnel mesh between PE routers with OSPF-TE and RSVP "
        "bandwidth on the core. IOS variant only.",
    ),
    (
        "ip_sla",
        "IP SLA: ICMP-echo probes from each PE into the L3VPN toward every remote "
        "customer site, scheduled to run forever. IOS variant only.",
    ),
)


@dataclass(frozen=True, slots=True)
class TemplateVariant:
    """One source of a template, scoped by exactly one of `node` / `device` /
    neither (universal). Both-set is rejected at the API boundary; instances
    here are already valid."""

    source: str
    device: str | None = None
    node: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigTemplate:
    """One template record: the `config:` name a definition references, a
    user-facing description, and its scoped variants. Tier travels beside the
    record (builtins live in code, user records on the lab row), not in it."""

    name: str
    description: str
    variants: tuple[TemplateVariant, ...]


def variant_relpath(name: str, variant: TemplateVariant) -> str:
    """The workdir path netlab's lookup finds this variant at. Node before
    device: a variant carries at most one scope key, so the order here only
    documents the precedence the filenames give netlab."""
    if variant.node is not None:
        return f"{name}/{variant.node}.j2"
    if variant.device is not None:
        return f"{name}/{variant.device}.j2"
    return f"{name}.j2"


def materialize(templates: Iterable[ConfigTemplate]) -> dict[str, str]:
    """Render records into the `{relpath: content}` fileset netlab needs on
    disk. Injective for valid records: template names are unique per tier and
    disjoint across tiers (409 at PUT), and within a template the scope keys
    are unique with node/device filename collisions rejected."""
    return {
        variant_relpath(template.name, variant): variant.source
        for template in templates
        for variant in template.variants
    }


@dataclass(frozen=True, slots=True)
class BuiltinLibrary:
    """The loaded built-in templates, plus the derived views the API and config
    push need: the materialized fileset to ship, and the reserved names user
    templates may not take."""

    templates: tuple[ConfigTemplate, ...]

    @property
    def fileset(self) -> dict[str, str]:
        """Every built-in variant materialized — shipped to the runner on
        every configure (netlab renders only the referenced ones)."""
        return materialize(self.templates)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(template.name for template in self.templates)


def _read_builtin(root: Traversable, name: str, description: str) -> Result[ConfigTemplate, str]:
    subdir = root / name
    if not subdir.is_dir():
        return Err(f"built-in template '{name}' has no directory")
    variants: list[TemplateVariant] = []
    for entry in sorted(subdir.iterdir(), key=lambda item: item.name):
        if entry.name.endswith(".j2") and entry.is_file():
            variants.append(
                TemplateVariant(source=entry.read_text(), device=entry.name.removesuffix(".j2"))
            )
    if not variants:
        return Err(f"built-in template '{name}' has no .j2 variants")
    return Ok(ConfigTemplate(name=name, description=description, variants=tuple(variants)))


def load_builtins() -> Result[BuiltinLibrary, str]:
    """Load the built-in template library from packaged sources. A missing or
    empty built-in is a packaging error surfaced at startup, not swallowed."""
    root = files("twinlab_backend.services").joinpath("builtin_templates")
    if not root.is_dir():
        return Err("builtin_templates directory is missing from the package")
    templates: list[ConfigTemplate] = []
    for name, description in _BUILTIN_SPECS:
        read = _read_builtin(root, name, description)
        if isinstance(read, Err):
            return read
        templates.append(read.value)
    return Ok(BuiltinLibrary(templates=tuple(templates)))

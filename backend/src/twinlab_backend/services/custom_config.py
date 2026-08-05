"""Custom-configuration templates: the seam for config netlab does not model.

netlab's 19 modules cover topology + control-plane routing/switching; features
like MPLS-TE, IP SLA, QoS, ACLs, NAT, multicast and telemetry have no module on
any NOS. netlab's own answer is the custom-configuration hook: a node/group
`config: [name]` attribute renders `name.j2` (Jinja over the node model) and
pushes it via `netlab initial`. Twinlab exposes that hook in two tiers:

- **built-in** templates authored and shipped here, non-deletable, available to
  every lab (MPLS-TE and IP SLA are the first two); and
- **user** templates stored per-lab on the record.

Both tiers are delivered to the netlab-runner as one fileset ({relpath: content})
per configure; the runner writes them into its workdir and netlab renders
whichever the definition references. The backend owns the data (as it owns test
suites); the runner stays a generic executor.

Built-in template sources live in `builtin_templates/<name>/<device>.j2` (netlab
resolves `config: [<name>]` to the per-device variant). Loading is a file-I/O
boundary, so it returns a typed Result; the app fails fast at startup on error.
"""

from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable

from twinlab_backend.result import Err, Ok, Result

# The built-in library, as (config name, one-line description) pairs. Each name
# maps to a `builtin_templates/<name>/` directory of per-device `.j2` variants.
# Keep the description user-facing: it is what the UI shows for a built-in.
_BUILTIN_SPECS: tuple[tuple[str, str], ...] = (
    # Both ship an `ios.j2` variant only. Cisco IOL left the supported device
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
class BuiltinTemplate:
    """One built-in template: the `config:` name a definition references, a
    user-facing description, and its per-device source files keyed by the relpath
    netlab searches (e.g. `mpls_te/ios.j2`)."""

    name: str
    description: str
    files: dict[str, str]


@dataclass(frozen=True, slots=True)
class BuiltinLibrary:
    """The loaded built-in templates, plus the derived views the API and config
    push need: the merged fileset to ship, and the reserved namespace user
    templates may not shadow."""

    templates: tuple[BuiltinTemplate, ...]

    @property
    def fileset(self) -> dict[str, str]:
        """Every built-in source file, keyed by relpath — shipped to the runner on
        every configure (netlab renders only the referenced ones)."""
        merged: dict[str, str] = {}
        for template in self.templates:
            merged.update(template.files)
        return merged

    @property
    def names(self) -> frozenset[str]:
        return frozenset(template.name for template in self.templates)

    def collision(self, user_fileset: dict[str, str]) -> str | None:
        """The first user template path that shadows a built-in, or None. A user
        path may not use a built-in's name as its top segment — that reserves the
        whole `mpls_te/*` (and flat `mpls_te.j2`) namespace, so a user can neither
        override nor extend a built-in."""
        reserved = self.names
        for relpath in user_fileset:
            top = relpath.split("/", 1)[0].removesuffix(".j2")
            if top in reserved:
                return relpath
        return None


def _read_builtin(root: Traversable, name: str) -> Result[dict[str, str], str]:
    subdir = root / name
    if not subdir.is_dir():
        return Err(f"built-in template '{name}' has no directory")
    files_by_path: dict[str, str] = {}
    for entry in subdir.iterdir():
        if entry.name.endswith(".j2") and entry.is_file():
            files_by_path[f"{name}/{entry.name}"] = entry.read_text()
    if not files_by_path:
        return Err(f"built-in template '{name}' has no .j2 variants")
    return Ok(files_by_path)


def load_builtins() -> Result[BuiltinLibrary, str]:
    """Load the built-in template library from packaged sources. A missing or
    empty built-in is a packaging error surfaced at startup, not swallowed."""
    root = files("twinlab_backend.services").joinpath("builtin_templates")
    if not root.is_dir():
        return Err("builtin_templates directory is missing from the package")
    templates: list[BuiltinTemplate] = []
    for name, description in _BUILTIN_SPECS:
        read = _read_builtin(root, name)
        if isinstance(read, Err):
            return read
        templates.append(BuiltinTemplate(name=name, description=description, files=read.value))
    return Ok(BuiltinLibrary(templates=tuple(templates)))

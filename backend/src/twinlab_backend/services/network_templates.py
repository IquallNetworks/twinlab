"""Built-in network templates: the template library's shipped tier (delta 21).

A network template is a complete netlab definition offered as a lab's starting
point — instantiation is plain clone-and-edit through the normal lifecycle
(create → PUT → deploy), where PUT re-pins the record's name and mgmt subnet,
so whatever pinning the template text carries is irrelevant.

The built-in tier mirrors the repo's `examples/` (the backend image cannot see
the repo root, so the sources are packaged here; a drift-guard test keeps the
copies honest). The USER tier is not stored here at all: a user-tier network
template is a lab PUBLISHED via `PUT /labs/{name}/template`, served live from
the lab record.

Loading is a file-I/O boundary, so it returns a typed Result; the app fails
fast at startup on error (the custom-config builtin pattern).
"""

from dataclasses import dataclass
from importlib.resources import files

from twinlab_backend.result import Err, Ok, Result

# The built-in library, as (template name, one-line description) pairs. Each
# name maps to `builtin_network_templates/<name>.yml`. Keep the description
# user-facing: it is the library card the UI shows. Names carry the `example-`
# prefix ON PURPOSE: a builtin name reserves itself against lab publication
# (409 name_taken), and the bare example names are exactly what real labs
# deployed from these examples get called — the prefix keeps them publishable.
_BUILTIN_SPECS: tuple[tuple[str, str], ...] = (
    (
        "example-mpls-l3vpn",
        "MPLS L3VPN service-provider core on VyOS: four PE + three P routers, "
        "OSPF area-0 core, LDP transport, one customer VPN over MP-BGP VPNv4.",
    ),
    (
        "example-mpls-l3vpn-iol",
        "The same MPLS L3VPN core on Cisco IOL. Requires your own licensed "
        "vrnetlab/cisco_iol image on the host — Cisco IOL is proprietary and "
        "not distributed with Twinlab.",
    ),
    (
        "example-campus-lan",
        "A small campus on VyOS routers and linux hosts: a redundant OSPF "
        "backbone, multi-access LAN segments, and a stub drop — exercises "
        "every link form the topology view renders.",
    ),
)


@dataclass(frozen=True, slots=True)
class BuiltinNetworkTemplate:
    """One built-in network template: name, library-card description, and the
    complete netlab definition text."""

    name: str
    description: str
    content: str


@dataclass(frozen=True, slots=True)
class NetworkTemplateLibrary:
    """The loaded built-in network templates. `names` is the namespace a lab
    publication may not collide with (409 name_taken)."""

    templates: tuple[BuiltinNetworkTemplate, ...]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(template.name for template in self.templates)

    def get(self, name: str) -> BuiltinNetworkTemplate | None:
        for template in self.templates:
            if template.name == name:
                return template
        return None


def load_network_templates() -> Result[NetworkTemplateLibrary, str]:
    """Load the built-in network templates from packaged sources. A missing or
    empty source is a packaging error surfaced at startup, not swallowed."""
    root = files("twinlab_backend.services").joinpath("builtin_network_templates")
    if not root.is_dir():
        return Err("builtin_network_templates directory is missing from the package")
    templates: list[BuiltinNetworkTemplate] = []
    for name, description in _BUILTIN_SPECS:
        source = root / f"{name}.yml"
        if not source.is_file():
            return Err(f"built-in network template '{name}' has no source file")
        content = source.read_text()
        if not content.strip():
            return Err(f"built-in network template '{name}' is empty")
        templates.append(
            BuiltinNetworkTemplate(name=name, description=description, content=content)
        )
    return Ok(NetworkTemplateLibrary(templates=tuple(templates)))

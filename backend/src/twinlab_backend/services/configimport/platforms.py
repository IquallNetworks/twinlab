"""The per-platform importer table — the single dispatch point for config import.

Every stage that must know a source platform's syntax (parse, classify, rewrite
the carry, dump the running config for the fidelity diff) reaches it through one
`PlatformImporter` record. Nothing downstream branches on a device name.

This is deliberately a table while only two platforms exist. The shape it
replaced was four independent `device == "vyos"` ternaries whose `else` meant
IOS — so a third platform would not have failed, it would have been silently
classified and rewritten as Cisco. A table cannot do that: a device is either in
it or it is `unsupported_device`.

Admitting a platform is therefore additive throughout: a parser module, a
`ClassifySpec` beside the existing ones, a rewriter, and one entry here.
"""

from collections.abc import Callable
from dataclasses import dataclass

from twinlab_backend.result import Result
from twinlab_backend.services.configimport.classify import (
    IOS_CLASSIFY,
    VYOS_CLASSIFY,
    ClassifySpec,
)
from twinlab_backend.services.configimport.ios import parse_ios
from twinlab_backend.services.configimport.model import Note, ParsedSource, ParseError
from twinlab_backend.services.configimport.rewrite import rewrite_ios, rewrite_vyos
from twinlab_backend.services.configimport.vyos import parse_vyos

type Parser = Callable[[str], Result[ParsedSource, ParseError]]

# (carry lines, source-if -> lab-if map, node) -> (rewritten lines, notes).
type Rewriter = Callable[[tuple[str, ...], dict[str, str], str], tuple[tuple[str, ...], list[Note]]]


@dataclass(frozen=True, slots=True)
class PlatformImporter:
    """One importable platform, end to end."""

    device: str
    parse: Parser
    classify: ClassifySpec
    rewrite: Rewriter
    # The running-config dump, written in the DEVICE'S OWN CLI. Reaching that
    # CLI from the exec transport is `cli_adapters`' job (delta 28) — callers
    # adapt this with mode "cli", which is what puts VyOS's op-mode wrapper
    # back in front of a bare spelling that would otherwise return empty
    # stdout. Config-diff is pinned to the exec transport deliberately: it must
    # work on a lab whose config is broken, which is when it is worth running.
    dump_command: str


PLATFORMS: dict[str, PlatformImporter] = {
    "vyos": PlatformImporter(
        device="vyos",
        parse=parse_vyos,
        classify=VYOS_CLASSIFY,
        rewrite=rewrite_vyos,
        dump_command="show configuration commands",
    ),
    "iol": PlatformImporter(
        device="iol",
        parse=parse_ios,
        classify=IOS_CLASSIFY,
        rewrite=rewrite_ios,
        dump_command="show running-config",
    ),
}


def importer_for(device: str) -> PlatformImporter | None:
    """The importer for a device, or None when it has no parser."""
    return PLATFORMS.get(device)


def import_capable_devices() -> frozenset[str]:
    """The devices with an importer — the catalog's `config_import` flag."""
    return frozenset(PLATFORMS)

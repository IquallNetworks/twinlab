"""What language a test command is written in (contract delta 28, `mode`).

A `TestCase.command` used to be "a string handed to `netlab exec`", which says
nothing about which interpreter receives it. For a docker-transport device that
interpreter is the container's SHELL — Debian userland, not the NOS CLI — so a
command written in the device's own CLI silently hits the wrong thing:
`ping 10.2.0.4 vrf vpn_a count 5` on VyOS reaches `/bin/ping`, which has no
`vrf` flag, and the suite sees an empty stdout instead of an explanation.

`mode` names the language, and this module is the one place that knows how to
reach each device's CLI from the shell:

- `shell` (default) — the command goes verbatim to whatever the transport
  lands in. This is the pre-delta-28 behavior, so no stored suite changes
  meaning.
- `cli` — the command is written in the device's own CLI, and gets rewritten
  to whatever reaches that CLI here.

VyOS is the reason `interactive` participates: its op-mode is installed by
INTERACTIVE SHELL INITIALIZATION, not by the transport. A one-shot
(`su - vyos -c "…"`, which is exactly what `netlab exec` runs) is
non-interactive and has no op-mode, so it needs the wrapper — while an
interactive session (delta 28's `docker exec -it` channel) already IS op-mode
and must NOT be wrapped. Verified live on all four combinations 2026-08-10.

Everything here is per-device policy, so it lives in the backend beside the
catalog, `DEVICE_KMODS` and the import parsers; the runner stays a generic
executor that receives a finished command string.
"""

import shlex
from dataclasses import dataclass
from typing import Literal

from twinlab_backend.result import Err, Ok, Result

# How a command's words are meant to be interpreted (contract delta 28).
type CommandMode = Literal["shell", "cli"]


@dataclass(frozen=True, slots=True)
class CliEntry:
    """How to reach one device's CLI. `template` carries `{command}` and is
    applied for `mode: cli`; None means the device's transport already lands
    in its CLI, so `cli` is the identity."""

    template: str | None
    # True when the command must be shell-quoted into a single argument
    # (a CLI *binary* taking one string) rather than pasted as bare words.
    quote: bool = False
    # True when an INTERACTIVE session already lands in the CLI, so the
    # template must be skipped there (VyOS op-mode — see the module docstring).
    native_when_interactive: bool = False


# Devices with a CLI tier. A device ABSENT from this map has no CLI of its own
# (linux, dnsmasq: the shell IS the interface), and `mode: cli` on it is a
# caller error rather than a silent identity — saying "run this in the CLI" to
# a device with no CLI is a mistake worth naming.
CLI_ENTRIES: dict[str, CliEntry] = {
    # Op-mode via the wrapper VyOS ships for exactly this purpose (running an
    # op-mode command from a non-interactive context).
    "vyos": CliEntry(
        template="/opt/vyatta/bin/vyatta-op-cmd-wrapper {command}",
        native_when_interactive=True,
    ),
    # FRR's CLI is a binary taking one string, so it is mode-independent —
    # `vtysh -c` behaves identically interactive or not.
    "frr": CliEntry(template="vtysh -c {command}", quote=True),
    # The BIRD control client takes the command as bare words (netlab's own
    # show command uses the same client).
    "bird": CliEntry(template="birdc {command}"),
    # SSH-transport network OSes: the session already IS the CLI, so `cli` is
    # the identity and `shell` (no shell tier exists to reach) is too.
    "routeros7": CliEntry(template=None),
    # Not in the catalog since the 2026-08-05 licensing withdrawal, but the
    # mechanism is device-agnostic and an IOL lab still deploys.
    "iol": CliEntry(template=None),
}


def adapt_command(
    device: str, command: str, *, mode: CommandMode, interactive: bool
) -> Result[str, str]:
    """Rewrite `command` for the interpreter `mode` names on `device`.

    Returns the command unchanged for `shell` (and for devices whose transport
    already lands in their CLI). `cli` on a device with no CLI tier is an
    Err — the caller turns it into a 422 at authoring time or an `error`
    result at run time, never a silently mis-sent command."""
    if mode == "shell":
        return Ok(command)
    entry = CLI_ENTRIES.get(device)
    if entry is None:
        return Err(
            f"device {device!r} has no CLI of its own — its shell IS the "
            f"interface, so use mode 'shell'"
        )
    if entry.template is None:
        return Ok(command)
    if interactive and entry.native_when_interactive:
        # An interactive session is already in the CLI; wrapping again would
        # nest a second interpreter.
        return Ok(command)
    return Ok(entry.template.format(command=shlex.quote(command) if entry.quote else command))


def cli_capable(device: str) -> bool:
    """Whether `mode: cli` is meaningful on this device — the check the suites
    PUT runs so an impossible case is rejected at authoring time."""
    return device in CLI_ENTRIES

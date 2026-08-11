"""Command-language adaptation (contract delta 28, `mode`).

The table IS the contract: which interpreter a command's words reach on each
device, and how `interactive` changes that. Every row here was verified live
against a running VyOS node (2026-08-10) before being written down.
"""

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.cli_adapters import CLI_ENTRIES, adapt_command, cli_capable
from twinlab_backend.services.device_catalog import SUPPORTED_DEVICES

_PING = "ping 10.2.0.4 vrf vpn_a count 5"


def test_shell_mode_is_always_verbatim() -> None:
    # The default mode is the pre-delta-28 behavior, so no stored suite can
    # change meaning: whatever the transport lands in gets the words as typed.
    for device in ("vyos", "frr", "linux", "routeros7", "dnsmasq"):
        for interactive in (False, True):
            adapted = adapt_command(device, _PING, mode="shell", interactive=interactive)
            assert isinstance(adapted, Ok)
            assert adapted.value == _PING


def test_vyos_cli_needs_the_wrapper_only_when_not_interactive() -> None:
    # VyOS op-mode is installed by INTERACTIVE SHELL INITIALIZATION. A one-shot
    # (`su - vyos -c`, what netlab exec runs) has none, so it needs the
    # wrapper; an interactive session already is op-mode and must not be
    # wrapped — both proven live.
    one_shot = adapt_command("vyos", _PING, mode="cli", interactive=False)
    assert isinstance(one_shot, Ok)
    assert one_shot.value == f"/opt/vyatta/bin/vyatta-op-cmd-wrapper {_PING}"

    interactive = adapt_command("vyos", _PING, mode="cli", interactive=True)
    assert isinstance(interactive, Ok)
    assert interactive.value == _PING


def test_frr_cli_quotes_into_one_vtysh_argument() -> None:
    # vtysh takes the whole command as a single argument, so it must be quoted
    # — and it behaves identically interactive or not (it is a binary, not a
    # shell mode).
    for interactive in (False, True):
        adapted = adapt_command("frr", "show ip ospf neighbor", mode="cli", interactive=interactive)
        assert isinstance(adapted, Ok)
        assert adapted.value == "vtysh -c 'show ip ospf neighbor'"


def test_bird_cli_uses_its_control_client() -> None:
    adapted = adapt_command("bird", "show ospf neighbors", mode="cli", interactive=False)
    assert isinstance(adapted, Ok)
    assert adapted.value == "birdc show ospf neighbors"


def test_native_cli_devices_are_identity() -> None:
    # An SSH-transport network OS lands in its own CLI already; `cli` is then
    # a statement of intent, not a rewrite.
    adapted = adapt_command(
        "routeros7", "/routing ospf neighbor print", mode="cli", interactive=False
    )
    assert isinstance(adapted, Ok)
    assert adapted.value == "/routing ospf neighbor print"


def test_cli_mode_on_a_shell_only_device_is_an_error() -> None:
    # linux and the dnsmasq daemon have no CLI of their own — saying "run this
    # in the CLI" is a mistake worth naming, not a silent identity.
    for device in ("linux", "dnsmasq"):
        adapted = adapt_command(device, "ip route", mode="cli", interactive=False)
        assert isinstance(adapted, Err), device
        assert "no CLI of its own" in adapted.error
        assert not cli_capable(device)


def test_every_cli_entry_names_a_real_device() -> None:
    # The table may carry devices outside the catalog (iol keeps working after
    # its licensing withdrawal), but never a typo: each entry is either a
    # catalog device or a known-withdrawn one.
    catalogued = {spec.device for spec in SUPPORTED_DEVICES}
    assert set(CLI_ENTRIES) <= catalogued | {"iol"}

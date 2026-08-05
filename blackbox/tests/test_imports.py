"""Config import (contract delta 22, wiring revision delta 23): the
definition factory, its wiring rules and error slugs, the permission split —
and the deploy-marked round trip: imported configs deploy, configure, and
survive the fidelity diff.
"""

import pytest
from twinlab_client import DiffSource, ImportSource, TwinlabApiError, TwinlabClient

from _config import LabFactory, UserClientFactory

# Two VyOS sources (set form), a p2p on 10.77.0.0/30 with pinned loopbacks.
# Beyond the modeled skeleton each carries a description + OSPF (the CARRY —
# protocol config rides verbatim, delta 22's thin-skeleton rule) and an NTP
# server (quarantined: telemetry). eth2 is UNNUMBERED on both: addressing
# can never place it, so only an explicit wire realizes it (delta 23).
_R1_VYOS = """\
set interfaces ethernet eth1 address '10.77.0.1/30'
set interfaces ethernet eth1 description 'to r2'
set interfaces ethernet eth2 description 'unnumbered core'
set interfaces ethernet eth3 address '10.88.0.1/24'
set interfaces loopback lo address '10.0.77.1/32'
set protocols ospf area 0 network '10.77.0.0/30'
set protocols ospf area 0 network '10.0.77.1/32'
set system host-name 'r1'
set system ntp server 'ntp.prod.example.com'
"""

_R2_VYOS = """\
set interfaces ethernet eth1 address '10.77.0.2/30'
set interfaces ethernet eth2 description 'unnumbered core'
set interfaces loopback lo address '10.0.77.2/32'
set protocols ospf area 0 network '10.77.0.0/30'
set protocols ospf area 0 network '10.0.77.2/32'
set system host-name 'r2'
"""

_SOURCES = [
    ImportSource(device="vyos", content=_R1_VYOS),
    ImportSource(device="vyos", content=_R2_VYOS),
]

# The addressed p2p only — the wiring the suggestion can propose.
_WIRING = [["r1:eth1", "r2:eth1"]]

# Plus the unnumbered wire: an L2 link no addressing could infer.
_WIRING_WITH_L2 = [*_WIRING, ["r1:eth2", "r2:eth2"]]


async def test_catalog_names_the_import_capable_devices(admin: TwinlabClient) -> None:
    catalog = {d.device: d for d in (await admin.device_catalog()).devices}
    assert catalog["vyos"].config_import is True
    assert catalog["linux"].config_import is False  # no config-dump concept
    # The flag lives on a CATALOG entry, so a parser without one is invisible
    # here: the IOS parser is still installed and `POST /import/*` still
    # accepts `device: iol`, but IOL left the catalog 2026-08-05 on CML
    # licensing (ROADMAP 17.1) and nothing advertises it.
    assert "iol" not in catalog


async def test_wiring_suggestion_is_advice_the_factory_accepts(admin: TwinlabClient) -> None:
    suggestion = await admin.suggest_wiring(_SOURCES)
    # The subnet join proposes the addressed p2p...
    assert [sorted(entry) for entry in suggestion.wiring] == [["r1:eth1", "r2:eth1"]]
    # ...and warns about exactly what it cannot place.
    assert any("eth2" in warning.message for warning in suggestion.warnings)
    # Feeding it straight back is accepted (the suggestion is in the wiring
    # format, spelled with the final node names).
    result = await admin.import_network(_SOURCES, suggestion.wiring)
    assert "10.77.0.1/30" in result.definition


async def test_import_network_factory_output(admin: TwinlabClient) -> None:
    result = await admin.import_network(_SOURCES, _WIRING)

    # The thin skeleton: both nodes, pinned addressing, no modules.
    assert "device: vyos" in result.definition
    assert "10.77.0.1/30" in result.definition
    assert "module" not in result.definition
    assert result.name_map == {"r1": "r1", "r2": "r2"}

    # Carry referenced by the definition, quarantine kept unattached.
    assert "imported/r1.j2" in result.custom_config
    assert "imported/r1.j2" in result.definition
    assert (
        "set protocols ospf area 0 network '10.77.0.0/30'" in result.custom_config["imported/r1.j2"]
    )
    assert "imported/r1.quarantine.j2" in result.custom_config
    assert "imported/r1.quarantine.j2" not in result.definition
    assert [q.reason for q in result.quarantine["r1"]] == ["telemetry"]

    # Identity interface map (same platform), loopback realized as dum0.
    assert result.interface_map["r1"]["eth1"] == "eth1"
    assert result.interface_map["r1"]["lo"] == "dum0"
    # eth2 was NOT wired here: unnumbered and unwired means no link at all,
    # and a warning that names it.
    assert "eth2" not in result.interface_map["r1"]
    assert any("eth2" in warning.message for warning in result.warnings)


async def test_unnumbered_wire_becomes_an_l2_link(admin: TwinlabClient) -> None:
    result = await admin.import_network(_SOURCES, _WIRING_WITH_L2)
    # The L2 link: no prefix, and every endpoint's address suppressed — bare
    # endpoints would make netlab INVENT addresses.
    assert "prefix: false" in result.definition
    assert "ipv4: false" in result.definition
    # And it is REAL: the unnumbered interfaces now map to lab interfaces.
    assert result.interface_map["r1"]["eth2"] == "eth2"
    assert result.interface_map["r2"]["eth2"] == "eth2"


async def test_mixed_wire_pins_one_side_and_suppresses_the_other(
    admin: TwinlabClient,
) -> None:
    # One addressed endpoint, one unnumbered: legal. The unaddressed side
    # emits `ipv4: false` — left bare, netlab would INVENT an address.
    result = await admin.import_network(_SOURCES, [["r1:eth3", "r2:eth2"]])
    assert "10.88.0.1/24" in result.definition
    assert "ipv4: false" in result.definition
    assert result.interface_map["r1"]["eth3"] == "eth1"  # first link of the doc
    assert result.interface_map["r2"]["eth2"] == "eth1"


async def test_import_error_slugs(admin: TwinlabClient) -> None:
    for sources, wiring, slug in (
        ([ImportSource(device="linux", content="hostname x\n")], [], "unsupported_device"),
        ([ImportSource(device="vyos", content="not a config\n")], [], "config_unparseable"),
        (
            [
                ImportSource(device="vyos", content=_R1_VYOS),
                ImportSource(device="vyos", content=_R1_VYOS),
            ],
            [],
            "duplicate_node",
        ),
        # Delta 23: asserted wiring makes contradictions ERRORS.
        (_SOURCES, [["r1:eth1"]], "wiring_invalid"),
        (_SOURCES, [["r1:eth9", "r2:eth1"]], "wiring_invalid"),
        (_SOURCES, [["r1:lo", "r2:eth1"]], "wiring_invalid"),
        # Two ADDRESSED endpoints in different subnets: the mask-typo case.
        (_SOURCES, [["r1:eth3", "r2:eth1"]], "wiring_conflict"),
    ):
        with pytest.raises(TwinlabApiError) as raised:
            _ = await admin.import_network(sources, wiring)
        assert raised.value.status_code == 422
        assert raised.value.code == slug, (slug, raised.value.code)
        if slug.startswith("wiring_"):
            assert raised.value.extras["entry"] == 0


async def test_import_permission_split(make_user_client: UserClientFactory) -> None:
    # import_network is the create-a-lab flow's factory: global lab:create.
    _, plain = await make_user_client(None)
    with pytest.raises(TwinlabApiError) as raised:
        _ = await plain.import_network(_SOURCES, _WIRING)
    assert raised.value.status_code == 403
    # The suggestion is the factory's prefill and rides the same gate.
    with pytest.raises(TwinlabApiError) as raised:
        _ = await plain.suggest_wiring(_SOURCES)
    assert raised.value.status_code == 403

    # import_node is a pure parse — any authenticated user (the builder flow).
    node = await plain.import_node("vyos", _R1_VYOS)
    assert "device: vyos" in node.fragment
    assert "ipv4: 10.0.77.1/32" in node.fragment  # loopback pin modeled
    assert node.interfaces == {"eth1": "10.77.0.1/30", "eth2": None, "eth3": "10.88.0.1/24"}
    # The carry keeps SOURCE names in this flow — the contract QUIRK, flagged.
    assert any("SOURCE interface names" in w.message for w in node.warnings)

    _, creator = await make_user_client({"creator"})
    result = await creator.import_network(_SOURCES, _WIRING)
    assert result.name_map == {"r1": "r1", "r2": "r2"}


async def test_config_diff_prechecks(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    sources = [DiffSource(node="r1", content=_R1_VYOS)]

    with pytest.raises(TwinlabApiError) as raised:
        _ = await admin.config_diff(lab.name, sources)
    assert raised.value.code == "no_definition"

    imported = await admin.import_network(_SOURCES, _WIRING)
    _ = await admin.put_custom_config(lab.name, imported.custom_config)
    _ = await admin.update_definition(lab.name, imported.definition)
    with pytest.raises(TwinlabApiError) as raised:
        _ = await admin.config_diff(lab.name, sources)
    assert raised.value.code == "lab_not_running"


async def test_imported_definition_lands_through_the_normal_lifecycle(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    """The compose path without deploying: custom config FIRST (the
    definition PUT's dry create validates its `config:` references against
    the STORED fileset — the reason for the contract's compose order), then
    the factory's definition passes the real PUT."""
    imported = await admin.import_network(_SOURCES, _WIRING_WITH_L2)
    lab = await make_lab(None)
    stored = await admin.put_custom_config(lab.name, imported.custom_config)
    assert "imported/r1.j2" in stored.custom_config
    assert "imported/r1.quarantine.j2" in stored.custom_config
    detail = await admin.update_definition(lab.name, imported.definition)
    assert detail.definition is not None


@pytest.mark.deploy
async def test_import_round_trip_deploys_and_diffs_clean(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    """The flagship: import (with an unnumbered L2 wire) -> compose -> deploy
    WITH configure (the carry actually applies — OSPF is carried, not
    modeled) -> the fidelity diff finds every comparable source line in the
    running config, with the import's interface map fed back so the
    L2-linked interfaces map (delta 23)."""
    imported = await admin.import_network(_SOURCES, _WIRING_WITH_L2)
    lab = await make_lab(None)
    _ = await admin.put_custom_config(lab.name, imported.custom_config)
    _ = await admin.update_definition(lab.name, imported.definition)

    job = await admin.deploy_lab(lab.name, configure=True)
    finished = await admin.wait_job(lab.name, job.id, timeout=600)
    assert finished.status == "succeeded", finished.error

    report = await admin.config_diff(
        lab.name,
        [
            DiffSource(node="r1", content=_R1_VYOS, interface_map=imported.interface_map["r1"]),
            DiffSource(node="r2", content=_R2_VYOS, interface_map=imported.interface_map["r2"]),
        ],
    )
    by_node = {entry.node: entry for entry in report.nodes}
    for node in ("r1", "r2"):
        entry = by_node[node]
        # Every comparable source line landed (addresses, carried OSPF, and
        # the unnumbered core interface the explicit wire realized).
        assert entry.missing == [], (node, entry.missing)
        assert entry.matched > 0
    # r1's NTP server was quarantined: excluded from comparison, counted.
    assert by_node["r1"].quarantined == 1

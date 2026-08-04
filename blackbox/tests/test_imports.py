"""Config import (contract delta 22): the definition factory, its error
slugs, the permission split — and the deploy-marked round trip: imported
configs deploy, configure, and survive the fidelity diff.
"""

import pytest
from twinlab_client import DiffSource, ImportSource, TwinlabApiError, TwinlabClient

from _config import LabFactory, UserClientFactory

# Two VyOS sources (set form), a p2p on 10.77.0.0/30 with pinned loopbacks.
# Beyond the modeled skeleton each carries a description + OSPF (the CARRY —
# protocol config rides verbatim, delta 22's thin-skeleton rule) and an NTP
# server (quarantined: telemetry).
_R1_VYOS = """\
set interfaces ethernet eth1 address '10.77.0.1/30'
set interfaces ethernet eth1 description 'to r2'
set interfaces loopback lo address '10.0.77.1/32'
set protocols ospf area 0 network '10.77.0.0/30'
set protocols ospf area 0 network '10.0.77.1/32'
set system host-name 'r1'
set system ntp server 'ntp.prod.example.com'
"""

_R2_VYOS = """\
set interfaces ethernet eth1 address '10.77.0.2/30'
set interfaces loopback lo address '10.0.77.2/32'
set protocols ospf area 0 network '10.77.0.0/30'
set protocols ospf area 0 network '10.0.77.2/32'
set system host-name 'r2'
"""

_SOURCES = [
    ImportSource(device="vyos", content=_R1_VYOS),
    ImportSource(device="vyos", content=_R2_VYOS),
]


async def test_catalog_names_the_import_capable_devices(admin: TwinlabClient) -> None:
    catalog = {d.device: d for d in (await admin.device_catalog()).devices}
    assert catalog["vyos"].config_import is True
    assert catalog["iol"].config_import is True
    assert catalog["linux"].config_import is False  # no config-dump concept


async def test_import_network_factory_output(admin: TwinlabClient) -> None:
    result = await admin.import_network(_SOURCES)

    # The thin skeleton: both nodes, pinned addressing, no modules.
    assert "device: vyos" in result.definition
    assert "10.77.0.1/30" in result.definition
    assert "module" not in result.definition
    assert result.name_map == {"r1": "r1", "r2": "r2"}

    # Carry referenced by the definition, quarantine kept unattached.
    assert "imported/r1.j2" in result.custom_config
    assert "imported/r1.j2" in result.definition
    assert "set protocols ospf area 0 network '10.77.0.0/30'" in result.custom_config["imported/r1.j2"]
    assert "imported/r1.quarantine.j2" in result.custom_config
    assert "imported/r1.quarantine.j2" not in result.definition
    assert [q.reason for q in result.quarantine["r1"]] == ["telemetry"]

    # Identity interface map (same platform), loopback realized as dum0.
    assert result.interface_map["r1"]["eth1"] == "eth1"
    assert result.interface_map["r1"]["lo"] == "dum0"


async def test_import_error_slugs(admin: TwinlabClient) -> None:
    for sources, slug in (
        ([ImportSource(device="linux", content="hostname x\n")], "unsupported_device"),
        ([ImportSource(device="vyos", content="not a config\n")], "config_unparseable"),
        (
            [
                ImportSource(device="vyos", content=_R1_VYOS),
                ImportSource(device="vyos", content=_R1_VYOS),
            ],
            "duplicate_node",
        ),
    ):
        with pytest.raises(TwinlabApiError) as raised:
            _ = await admin.import_network(sources)
        assert raised.value.status_code == 422
        assert raised.value.code == slug


async def test_import_permission_split(make_user_client: UserClientFactory) -> None:
    # import_network is the create-a-lab flow's factory: global lab:create.
    _, plain = await make_user_client(None)
    with pytest.raises(TwinlabApiError) as raised:
        _ = await plain.import_network(_SOURCES)
    assert raised.value.status_code == 403

    # import_node is a pure parse — any authenticated user (the builder flow).
    node = await plain.import_node("vyos", _R1_VYOS)
    assert "device: vyos" in node.fragment
    assert "ipv4: 10.0.77.1/32" in node.fragment  # loopback pin modeled
    assert node.interfaces == {"eth1": "10.77.0.1/30"}
    # The carry keeps SOURCE names in this flow — the contract QUIRK, flagged.
    assert any("SOURCE interface names" in w.message for w in node.warnings)

    _, creator = await make_user_client({"creator"})
    result = await creator.import_network(_SOURCES)
    assert result.name_map == {"r1": "r1", "r2": "r2"}


async def test_config_diff_prechecks(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    sources = [DiffSource(node="r1", content=_R1_VYOS)]

    with pytest.raises(TwinlabApiError) as raised:
        _ = await admin.config_diff(lab.name, sources)
    assert raised.value.code == "no_definition"

    imported = await admin.import_network(_SOURCES)
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
    imported = await admin.import_network(_SOURCES)
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
    """The flagship: import -> compose -> deploy WITH configure (the carry
    actually applies — OSPF is carried, not modeled) -> the fidelity diff
    finds every comparable source line in the running config."""
    imported = await admin.import_network(_SOURCES)
    lab = await make_lab(None)
    _ = await admin.put_custom_config(lab.name, imported.custom_config)
    _ = await admin.update_definition(lab.name, imported.definition)

    job = await admin.deploy_lab(lab.name, configure=True)
    finished = await admin.wait_job(lab.name, job.id, timeout=600)
    assert finished.status == "succeeded", finished.error

    report = await admin.config_diff(
        lab.name,
        [
            DiffSource(node="r1", content=_R1_VYOS),
            DiffSource(node="r2", content=_R2_VYOS),
        ],
    )
    by_node = {entry.node: entry for entry in report.nodes}
    for node in ("r1", "r2"):
        entry = by_node[node]
        # Every comparable source line landed (addresses AND carried OSPF).
        assert entry.missing == [], (node, entry.missing)
        assert entry.matched > 0
    # r1's NTP server was quarantined: excluded from comparison, counted.
    assert by_node["r1"].quarantined == 1
    # And the twin is not just configured but CONVERGED enough to have run
    # OSPF over the carried config — the running config serving the diff came
    # over the same exec transport the suites use, which is proof enough here.

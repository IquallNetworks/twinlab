"""Custom-config template records (contract delta 27): builtins, materialization,
and the device-type identity drift guard the materialization relies on."""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from twinlab_backend.result import Ok
from twinlab_backend.services.custom_config import (
    BuiltinLibrary,
    ConfigTemplate,
    TemplateVariant,
    load_builtins,
    materialize,
    variant_relpath,
)
from twinlab_backend.services.device_catalog import SUPPORTED_DEVICES


def test_load_builtins_ships_mpls_te_and_ip_sla() -> None:
    loaded = load_builtins()
    assert isinstance(loaded, Ok), loaded
    library = loaded.value
    assert library.names == frozenset({"mpls_te", "ip_sla"})
    by_name = {template.name: template for template in library.templates}
    # Each built-in ships its IOS variant as a device-scoped record (a label a
    # builtin may carry even though `ios` is no catalog device — it then
    # simply applies to no node), with real template content.
    for name, marker in (("mpls_te", "traffic-eng"), ("ip_sla", "ip sla")):
        variants = by_name[name].variants
        assert [variant.device for variant in variants] == ["ios"]
        assert marker in variants[0].source
    # Materialized paths keep the packaged relpaths.
    fileset = library.fileset
    assert "mpls_te/ios.j2" in fileset
    assert "ip_sla/ios.j2" in fileset


def test_variant_relpath_per_scope() -> None:
    assert variant_relpath("nat", TemplateVariant(source="x", node="pe1")) == "nat/pe1.j2"
    assert variant_relpath("nat", TemplateVariant(source="x", device="vyos")) == "nat/vyos.j2"
    assert variant_relpath("nat", TemplateVariant(source="x")) == "nat.j2"


def test_materialize_merges_all_variants() -> None:
    templates = (
        ConfigTemplate(
            name="nat",
            description="",
            variants=(
                TemplateVariant(source="generic"),
                TemplateVariant(source="for-vyos", device="vyos"),
                TemplateVariant(source="for-pe1", node="pe1"),
            ),
        ),
        ConfigTemplate(
            name="imported",
            description="",
            variants=(TemplateVariant(source="carry", node="r1"),),
        ),
    )
    assert materialize(templates) == {
        "nat.j2": "generic",
        "nat/vyos.j2": "for-vyos",
        "nat/pe1.j2": "for-pe1",
        "imported/r1.j2": "carry",
    }


def test_builtin_fileset_merges_all_builtin_files() -> None:
    lib = BuiltinLibrary(
        templates=(
            ConfigTemplate(
                name="a", description="", variants=(TemplateVariant(source="1", device="ios"),)
            ),
            ConfigTemplate(
                name="b",
                description="",
                variants=(
                    TemplateVariant(source="2", device="ios"),
                    TemplateVariant(source="3", device="eos"),
                ),
            ),
        )
    )
    assert lib.fileset == {"a/ios.j2": "1", "b/ios.j2": "2", "b/eos.j2": "3"}


def test_device_type_identity_matches_installed_netlab() -> None:
    """The drift guard materialization relies on: `X/<catalog slug>.j2` is only
    found by netlab's `X/{netlab_device_type}.j2` lookup form if the resolved
    device type IS the slug — true for the whole catalog today (vyos/frr/linux
    by fallback from ansible_network_os; routeros7/bird/dnsmasq explicitly). A
    netlab upgrade that breaks the identity must fail HERE, not by silently
    materializing a filename the lookup never visits."""
    nodes = "\n".join(
        f"  n{i}: {{ device: {spec.device} }}" for i, spec in enumerate(SUPPORTED_DEVICES)
    )
    definition = f"provider: clab\nname: devguard\nnodes:\n{nodes}\n"
    with tempfile.TemporaryDirectory() as workdir:
        _ = (Path(workdir) / "topology.yml").write_text(definition)
        _ = subprocess.run(
            ["netlab", "create", "topology.yml"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        for spec in SUPPORTED_DEVICES:
            path = Path(workdir) / "group_vars" / spec.device / "topology.json"
            group_vars = cast("dict[str, object]", json.loads(path.read_text()))
            resolved = group_vars.get("netlab_device_type", group_vars.get("ansible_network_os"))
            assert resolved == spec.device, spec.device

"""Device catalog (delta 18): drift guards + assembly.

The curated specs mirror the installed netlab's module-support view and
default clab images so catalog reads never pay a subprocess; a netlab upgrade
that changes either must fail HERE, not silently misadvertise a device.
"""

import importlib.util
import subprocess
from pathlib import Path
from typing import cast

import httpx
import yaml

from twinlab_backend.api.catalog import build_catalog
from twinlab_backend.result import Err, Ok
from twinlab_backend.services.device_catalog import (
    SUPPORTED_DEVICES,
    image_reference,
)
from twinlab_backend.services.runner_client import RunnerClient


def _netsim_root() -> Path:
    spec = importlib.util.find_spec("netsim")
    assert spec is not None and spec.submodule_search_locations is not None
    return Path(next(iter(spec.submodule_search_locations)))


def _clab_supported_modules(entry: dict[str, object], providers: frozenset[str]) -> set[str]:
    """netlab's module-support value per module is truthy/falsy or a feature
    dict; a dict keyed ONLY by provider names scopes support to those
    providers (e.g. linux dhcp is libvirt-only) and counts here only when
    "clab" is among them."""
    supported: set[str] = set()
    for module, value in entry.items():
        if isinstance(value, dict):
            keys = set(cast("dict[str, object]", value))
            if keys and keys <= providers:
                if "clab" in keys:
                    supported.add(module)
                continue
        if value:
            supported.add(module)
    return supported


def test_modules_mirror_matches_installed_netlab() -> None:
    shown = subprocess.run(
        ["netlab", "show", "module-support", "--format", "yaml"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    matrix = cast("dict[str, dict[str, object]]", yaml.safe_load(shown.stdout))
    providers = frozenset(p.stem for p in (_netsim_root() / "providers").glob("*.yml"))
    for spec in SUPPORTED_DEVICES:
        expected = _clab_supported_modules(matrix[spec.device], providers)
        assert set(spec.modules) == expected, spec.device


def test_image_mirror_matches_installed_netlab() -> None:
    root = _netsim_root()
    for spec in SUPPORTED_DEVICES:
        # netlab splits its catalog in two: real devices and the daemon tier
        # (bird, dnsmasq, …), which is otherwise identical from here.
        paths = [root / "devices" / f"{spec.device}.yml", root / "daemons" / f"{spec.device}.yml"]
        path = next((candidate for candidate in paths if candidate.exists()), None)
        assert path is not None, f"no netlab definition for {spec.device}"
        device_data = cast("dict[str, object]", yaml.safe_load(path.read_text()))
        clab = cast("dict[str, object]", device_data["clab"])
        assert clab["image"] == spec.image, spec.device


def test_image_reference_normalizes_untagged() -> None:
    assert image_reference("ghcr.io/sysoleg/vyos-container") == (
        "ghcr.io/sysoleg/vyos-container:latest"
    )
    assert image_reference("vrnetlab/mikrotik_routeros:7.21.4") == (
        "vrnetlab/mikrotik_routeros:7.21.4"
    )
    # A registry port is not a tag separator.
    assert image_reference("registry.local:5000/vyos") == "registry.local:5000/vyos:latest"


def test_build_catalog_matches_presence() -> None:
    catalog = build_catalog(
        frozenset({"ghcr.io/sysoleg/vyos-container:latest", "python:3.13-alpine"})
    )
    assert catalog.live
    by_device = {d.device: d for d in catalog.devices}
    assert by_device["vyos"].image_present is True
    assert by_device["routeros7"].image_present is False
    assert by_device["linux"].image_present is True


def test_build_catalog_degrades_without_runner() -> None:
    catalog = build_catalog(None)
    assert not catalog.live
    assert [d.device for d in catalog.devices] == [spec.device for spec in SUPPORTED_DEVICES]
    assert all(d.image_present is None for d in catalog.devices)


async def test_runner_list_images_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/images"
        return httpx.Response(200, json={"images": ["a:1", "b:latest"]})

    client = RunnerClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://runner.test",
    )
    result = await client.list_images()
    assert isinstance(result, Ok), result
    assert result.value == frozenset({"a:1", "b:latest"})


async def test_runner_list_images_error_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": {"stage": "docker-images"}})

    client = RunnerClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://runner.test",
    )
    result = await client.list_images()
    assert isinstance(result, Err)
    assert result.error.reason == "runner"

"""Deployable-device catalog: what this deployment can actually run (delta 18).

The curated device set with per-device module support, the default clab image,
and best-effort image presence resolved through the netlab-runner (the
component that owns the Docker socket). Any authenticated user may read it —
it names no lab, and a failed deploy would reveal a missing image anyway.
Image presence is advisory: deploy does not pre-flight it.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from twinlab_backend.auth.dependencies import CurrentUserDep
from twinlab_backend.deps import RunnerClientDep
from twinlab_backend.result import Ok
from twinlab_backend.services.configimport.platforms import import_capable_devices
from twinlab_backend.services.device_catalog import (
    SUPPORTED_DEVICES,
    DeviceRole,
    image_reference,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


class CatalogDeviceOut(BaseModel):
    device: str
    label: str
    role: DeviceRole
    modules: list[str]
    image: str
    image_present: bool | None  # None = presence unknown (see live)
    # Delta 22: dumped running configs of this device can be imported
    # (POST /import/*). Narrower than deployability — derived from the
    # importer's parser set, so it can never drift from what actually parses.
    config_import: bool


class DeviceCatalogOut(BaseModel):
    devices: list[CatalogDeviceOut]
    live: bool  # False = the runner could not report images; presence unknown


def build_catalog(present_images: frozenset[str] | None) -> DeviceCatalogOut:
    """Pure assembly: the curated specs joined with the daemon's image set
    (None = the runner was unreachable — every presence degrades to None,
    never an error; the link-table honesty pattern)."""
    importable = import_capable_devices()
    return DeviceCatalogOut(
        devices=[
            CatalogDeviceOut(
                device=spec.device,
                label=spec.label,
                role=spec.role,
                modules=list(spec.modules),
                image=spec.image,
                image_present=(
                    None
                    if present_images is None
                    else image_reference(spec.image) in present_images
                ),
                config_import=spec.device in importable,
            )
            for spec in SUPPORTED_DEVICES
        ],
        live=present_images is not None,
    )


@router.get("")
async def device_catalog(_: CurrentUserDep, runner: RunnerClientDep) -> DeviceCatalogOut:
    images = await runner.list_images()
    return build_catalog(images.value if isinstance(images, Ok) else None)

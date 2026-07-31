"""Client for the hostprep sidecar (host bridges + kernel modules).

The sidecar is the one component allowed to touch host network devices: it
creates/deletes the per-lab Linux bridges multi-access links need and
modprobes the kernel modules netlab's clab provider asks for — `netlab up`
pre-start work, which Twinlab never runs. It is a dumb executor behind a
shared token; THIS side owns the policy (bridge ownership, collisions,
required-vs-optional modules), applied in the deploy/destroy jobs.

httpx is a third-party boundary: its exceptions and the sidecar's JSON are
translated here into typed results; nothing propagates as an exception.
"""

from dataclasses import dataclass
from http import HTTPStatus
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from twinlab_backend.result import Err, Ok, Result

# Bridge/module operations are a handful of netlink calls and modprobes —
# milliseconds each; the cap only bounds a wedged sidecar.
_TIMEOUT_SECONDS = 30.0

# The sidecar's per-item vocabulary, pinned here because the jobs branch on it.
type BridgeStatus = Literal[
    "created", "existed", "deleted", "absent", "in_use", "not_bridge", "error"
]


@dataclass(frozen=True, slots=True)
class HostPrepError:
    message: str


@dataclass(frozen=True, slots=True)
class BridgeOutcome:
    name: str
    status: BridgeStatus
    detail: str


@dataclass(frozen=True, slots=True)
class ModuleOutcome:
    name: str
    ok: bool
    detail: str


class _BridgeModel(BaseModel):
    name: str
    status: BridgeStatus
    detail: str


class _BridgesResponse(BaseModel):
    bridges: list[_BridgeModel]


class _ModuleModel(BaseModel):
    name: str
    ok: bool
    detail: str


class _ModulesResponse(BaseModel):
    modules: list[_ModuleModel]


@dataclass(frozen=True, slots=True)
class HostPrepClient:
    client: httpx.AsyncClient
    base_url: str
    token: str

    async def _bridges(
        self, method: str, names: list[str]
    ) -> Result[tuple[BridgeOutcome, ...], HostPrepError]:
        try:
            resp = await self.client.request(
                method,
                f"{self.base_url}/bridges",
                json={"names": names},
                headers={"X-Hostprep-Token": self.token},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            return Err(HostPrepError(f"hostprep request failed: {exc}"))
        if resp.status_code != HTTPStatus.OK:
            return Err(HostPrepError(f"hostprep rejected the request: {resp.text}"))
        try:
            parsed = _BridgesResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(HostPrepError(f"unexpected hostprep response: {exc}"))
        return Ok(
            tuple(
                BridgeOutcome(name=b.name, status=b.status, detail=b.detail) for b in parsed.bridges
            )
        )

    async def ensure_bridges(
        self, names: list[str]
    ) -> Result[tuple[BridgeOutcome, ...], HostPrepError]:
        """Create-if-missing (idempotent, convergent). Item statuses: `created`,
        `existed`, `not_bridge` (a same-named non-bridge interface exists —
        never touched), `error`."""
        return await self._bridges("PUT", names)

    async def delete_bridges(
        self, names: list[str]
    ) -> Result[tuple[BridgeOutcome, ...], HostPrepError]:
        """Delete-if-present. Item statuses: `deleted`, `absent`, `in_use`
        (ports still attached — someone else is wired to it), `not_bridge`,
        `error`."""
        return await self._bridges("DELETE", names)

    async def load_modules(
        self, names: list[str]
    ) -> Result[tuple[ModuleOutcome, ...], HostPrepError]:
        """modprobe each allowlisted module (already-loaded is a no-op success).
        Per-item ok/detail; the caller applies the required-vs-optional policy."""
        try:
            resp = await self.client.post(
                f"{self.base_url}/modules",
                json={"names": names},
                headers={"X-Hostprep-Token": self.token},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            return Err(HostPrepError(f"hostprep request failed: {exc}"))
        if resp.status_code != HTTPStatus.OK:
            return Err(HostPrepError(f"hostprep rejected the request: {resp.text}"))
        try:
            parsed = _ModulesResponse.model_validate_json(resp.content)
        except ValidationError as exc:
            return Err(HostPrepError(f"unexpected hostprep response: {exc}"))
        return Ok(
            tuple(ModuleOutcome(name=m.name, ok=m.ok, detail=m.detail) for m in parsed.modules)
        )

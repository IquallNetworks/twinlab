"""Environment-sourced configuration: one setting, required."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    # The backend's origin inside the compose network (no path; the client
    # appends /api/v1). No default: the sidecar has one job and cannot guess
    # where it points.
    api_url: str


@dataclass(frozen=True, slots=True)
class SettingsError:
    message: str


def load_settings(env: Mapping[str, str]) -> Settings | SettingsError:
    api_url = env.get("TWINLAB_API_URL", "")
    if not api_url:
        return SettingsError("TWINLAB_API_URL is not set")
    if not api_url.startswith(("http://", "https://")):
        return SettingsError(f"TWINLAB_API_URL must be an http(s) origin, got {api_url!r}")
    return Settings(api_url=api_url.rstrip("/"))

"""Runtime configuration, loaded from the environment as a typed result.

Every field is required: there is no sensible universal default for a database
URL or the clab-api credentials, so a missing (or empty) value is a load-time
error, not a silent fallback. Loading returns a `Result` rather than raising;
the app fails startup on an `Err`.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from twinlab_backend.result import Err, Ok, Result

# Settings field -> the environment variable it is read from.
_ENV_KEYS = {
    "database_url": "DATABASE_URL",
    "clab_api_url": "CLAB_API_URL",
    "clab_api_username": "CLAB_API_USERNAME",
    "clab_api_password": "CLAB_API_PASSWORD",
    "netlab_runner_url": "NETLAB_RUNNER_URL",
    "bootstrap_admin_username": "BOOTSTRAP_ADMIN_USERNAME",
    "bootstrap_admin_password": "BOOTSTRAP_ADMIN_PASSWORD",
}

# Optional settings: read from the environment when present, else the model
# default applies. Kept out of the required set above.
_OPTIONAL_ENV_KEYS = {
    "session_cookie_name": "SESSION_COOKIE_NAME",
    "session_ttl_hours": "SESSION_TTL_HOURS",
    "session_cookie_secure": "SESSION_COOKIE_SECURE",
    "mgmt_subnet_pool": "MGMT_SUBNET_POOL",
}


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Postgres DSN, e.g. postgresql://user:pass@postgres:5432/twinlab.
    database_url: str
    # Base URL of the containerlab API server (no trailing slash), e.g.
    # http://host.docker.internal:8090 when it runs on the host network.
    clab_api_url: str
    # Host (PAM) user the API server authenticates; must be in its clab_api group.
    clab_api_username: str
    clab_api_password: SecretStr
    # Base URL of the netlab-runner config-push sidecar (no trailing slash).
    netlab_runner_url: str

    # Admin created on first startup when the users table is empty.
    bootstrap_admin_username: str
    bootstrap_admin_password: SecretStr

    # Login session cookie. `secure` defaults True (only sent over HTTPS); set it
    # false for local HTTP dev. 8h TTL is a starting policy, tune per deployment.
    session_cookie_name: str = "twinlab_session"
    session_ttl_hours: int = 8
    session_cookie_secure: bool = True

    # Pool the per-lab management /24s are carved from, so concurrent labs get
    # distinct mgmt subnets (netlab otherwise defaults every lab to
    # 192.168.121.0/24 and they collide). Default sits in the roomy 10/8 private
    # block, deliberately away from the host LAN (usually 192.168.x) and Docker's
    # 172.16/12 bridges; override per deployment if 10.77/16 clashes with a route.
    mgmt_subnet_pool: str = "10.77.0.0/16"


@dataclass(frozen=True, slots=True)
class ConfigError:
    message: str


def load_settings(env: Mapping[str, str]) -> Result[Settings, ConfigError]:
    missing = sorted(var for var in _ENV_KEYS.values() if not env.get(var))
    if missing:
        return Err(ConfigError(f"missing required environment variables: {', '.join(missing)}"))

    values = {field: env[var] for field, var in _ENV_KEYS.items()}
    for field, var in _OPTIONAL_ENV_KEYS.items():
        if env.get(var):
            values[field] = env[var]
    try:
        return Ok(Settings.model_validate(values))
    except ValidationError as exc:
        return Err(ConfigError(f"invalid configuration: {exc}"))

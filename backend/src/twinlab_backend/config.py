"""Runtime configuration, loaded from the environment as a typed result.

Required fields have no sensible universal default (a database URL, the
clab-api credentials), so a missing (or empty) value is a load-time error, not
a silent fallback. One variable is required yet may be EMPTY:
FRONTEND_BASE_PATH, where '' is the explicit "served at the origin root".
Loading returns a `Result` rather than raising; the app fails startup on an
`Err`.
"""

from base64 import urlsafe_b64decode
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import (
    BaseModel,
    ConfigDict,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

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
    "bootstrap_admin_email": "BOOTSTRAP_ADMIN_EMAIL",
}

# Required to be PRESENT, but the empty string is a legitimate value (contract
# delta 33): the frontend's base path, where '' means the origin root. Kept
# apart from the required set above, whose rule is "present and non-empty".
_PRESENT_ENV_KEYS = {
    "frontend_base_path": "FRONTEND_BASE_PATH",
}

# Optional settings: read from the environment when present, else the model
# default applies. Kept out of the required set above.
_OPTIONAL_ENV_KEYS = {
    "session_cookie_name": "SESSION_COOKIE_NAME",
    "session_ttl_hours": "SESSION_TTL_HOURS",
    "session_cookie_secure": "SESSION_COOKIE_SECURE",
    "mgmt_subnet_pool": "MGMT_SUBNET_POOL",
    "ssh_jump_token": "SSH_JUMP_TOKEN",
    "ssh_jump_address": "SSH_JUMP_ADDRESS",
    "hostprep_url": "HOSTPREP_URL",
    "hostprep_token": "HOSTPREP_TOKEN",
    "lab_files_dir": "LAB_FILES_DIR",
    "public_origin": "PUBLIC_ORIGIN",
    "oidc_secret_key": "OIDC_SECRET_KEY",
}

# A Fernet key is 32 random bytes, URL-safe base64 encoded (44 characters).
_FERNET_KEY_BYTES = 32


def is_email_address(value: str) -> bool:
    """The structural email check Twinlab applies everywhere (delta 33): one
    @, a non-empty local part and domain, no whitespace. Deliberately no
    DNS/deliverability check — a provider verifies an address better than a
    lookup can, and a lookup would be a network call at validation time."""
    local, at, domain = value.partition("@")
    return (
        bool(at)
        and bool(local)
        and bool(domain)
        and "@" not in domain
        and not any(char.isspace() for char in value)
    )


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
    # Every user carries an email (delta 33), the bootstrap admin included.
    bootstrap_admin_email: str

    # The path the frontend is served under ('' = the origin root, else like
    # "/twinlab"). REQUIRED to be set — compose spells it `${FRONTEND_BASE_PATH?}`
    # and passes the same value to the frontend build — because the backend
    # builds browser-facing URLs (the OIDC callback, post-login redirects) from
    # it, and a guessed base path would send a browser to the wrong place.
    frontend_base_path: str

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

    # SSH jump host (both optional in code — the backend runs without the
    # feature; the compose stack requires them so a deployed stack can't
    # silently ship a jump with no token). `ssh_jump_token` is the shared
    # secret the jump's key-lookup script presents to /internal; None disables
    # that route (404). `ssh_jump_address` is the EXTERNALLY reachable
    # "host:port" advertised on GET /ssh-access; "" = not advertised.
    ssh_jump_token: SecretStr | None = None
    ssh_jump_address: str = ""

    # Host-shared lab-files directory: where deploy materializes netlab's
    # generated `node_files/` so the topology's binds can be rewritten to
    # absolute paths instead of stripped (frr's daemons file, the shared
    # /etc/hosts, sh-mode config scripts all ride binds). SAME-PATH INVARIANT:
    # this must be the directory's path on the host AND its mount point in both
    # the backend and clab-api containers — dockerd resolves bind sources on the
    # host, clab-api pre-flights them in its own fs (see compose). Optional in
    # code — unset keeps the strip behavior — while the compose stack always
    # sets it.
    lab_files_dir: str = ""

    # Host-preparation sidecar (lab bridges + kernel modules). Optional in code
    # — the backend runs without it and only a deploy that NEEDS host prep
    # fails, with a clear job error — while the compose stack requires the
    # token so a deployed stack can't ship without one. URL and token are one
    # feature: setting only one of them is a configuration mistake, not a
    # choice, so it fails loading.
    hostprep_url: str = ""
    hostprep_token: SecretStr | None = None

    # The origin the browser reaches Twinlab at ("https://tools.example.com",
    # no path — the base path is `frontend_base_path`). Optional: "" turns OIDC
    # sign-in off, since a callback URL cannot be built without it, and a
    # deployment that does not use OIDC should not have to invent one.
    public_origin: str = ""

    # Fernet key encrypting OIDC client secrets at rest (delta 33). Optional in
    # code — the JUMP_TOKEN/HOSTPREP_TOKEN pattern: the backend runs without
    # it, and only saving a provider WITH a secret is refused — while compose
    # requires it so a deployed stack cannot ship without one.
    oidc_secret_key: SecretStr | None = None

    @model_validator(mode="after")
    def _hostprep_pair(self) -> Settings:
        if bool(self.hostprep_url) != (self.hostprep_token is not None):
            raise ValueError("HOSTPREP_URL and HOSTPREP_TOKEN must be set together")
        return self

    @field_validator("bootstrap_admin_email")
    @classmethod
    def _bootstrap_email_is_an_address(cls, value: str) -> str:
        if not is_email_address(value):
            raise ValueError("BOOTSTRAP_ADMIN_EMAIL must be an email address")
        return value

    @field_validator("frontend_base_path")
    @classmethod
    def _base_path_shape(cls, value: str) -> str:
        # The frontend build's own rule (vite.config.ts), mirrored so both
        # halves of the stack agree on what a base path is.
        if value and (not value.startswith("/") or value.endswith("/") or "//" in value):
            raise ValueError(
                'FRONTEND_BASE_PATH must be empty or like "/twinlab" '
                "(leading slash, no trailing slash)"
            )
        return value

    @field_validator("public_origin")
    @classmethod
    def _public_origin_shape(cls, value: str) -> str:
        if not value:
            return value
        scheme, sep, rest = value.partition("://")
        if scheme not in ("http", "https") or not sep or not rest or "/" in rest:
            raise ValueError(
                'PUBLIC_ORIGIN must be an origin like "https://tools.example.com" '
                "(scheme and host, optional port, no path)"
            )
        return value

    @field_validator("oidc_secret_key")
    @classmethod
    def _oidc_key_is_fernet(cls, value: SecretStr | None) -> SecretStr | None:
        # Validated at load so a malformed key fails startup, not the first
        # provider save or sign-in.
        if value is None:
            return value
        try:
            raw = urlsafe_b64decode(value.get_secret_value().encode())
        except ValueError:  # binascii.Error is a ValueError
            raise ValueError("OIDC_SECRET_KEY must be URL-safe base64") from None
        if len(raw) != _FERNET_KEY_BYTES:
            raise ValueError("OIDC_SECRET_KEY must decode to 32 bytes (a Fernet key)")
        return value

    @field_validator("lab_files_dir")
    @classmethod
    def _lab_files_dir_is_absolute(cls, value: str) -> str:
        # The path goes verbatim into bind specs dockerd resolves on the host —
        # a relative one would silently resolve against dockerd's cwd.
        if value and not value.startswith("/"):
            raise ValueError("LAB_FILES_DIR must be an absolute path")
        return value

    @field_validator("ssh_jump_address")
    @classmethod
    def _jump_address_is_host_port(cls, value: str) -> str:
        if not value:
            return value
        host, _, port = value.rpartition(":")
        if not host or not port.isdigit() or not 0 < int(port) < 65536:
            raise ValueError("SSH_JUMP_ADDRESS must be 'host:port'")
        return value


@dataclass(frozen=True, slots=True)
class ConfigError:
    message: str


def load_settings(env: Mapping[str, str]) -> Result[Settings, ConfigError]:
    missing = sorted(
        [var for var in _ENV_KEYS.values() if not env.get(var)]
        + [var for var in _PRESENT_ENV_KEYS.values() if var not in env]
    )
    if missing:
        return Err(ConfigError(f"missing required environment variables: {', '.join(missing)}"))

    values = {field: env[var] for field, var in (_ENV_KEYS | _PRESENT_ENV_KEYS).items()}
    for field, var in _OPTIONAL_ENV_KEYS.items():
        if env.get(var):
            values[field] = env[var]
    try:
        return Ok(Settings.model_validate(values))
    except ValidationError as exc:
        return Err(ConfigError(f"invalid configuration: {exc}"))

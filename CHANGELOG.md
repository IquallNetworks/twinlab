# Changelog

Notable changes to Twinlab, for the people who run it and the people who build on its API.

This file is **append-only**. A new entry goes at the bottom, and a published entry is never
edited, reordered or removed. If an entry turns out to be wrong, or a later change reverses
it, add a new entry that says so.

The log starts on 2026-09-23 and is not backfilled. Earlier history is in the git log and in
`docs/release-notes-v0.9.md`.

Each entry has a date and a title, then what changed. Where applicable it adds what an operator
must do when upgrading and what changed for API or `twinlab-client` users. The design record
named in an entry has the full reasoning.

---

## 2026-09-23: Sign in through OIDC providers (contract delta 33)

Design record: `docs/oidc.md`.

- Administrators (`user:manage`) configure any number of OpenID Connect providers on a new
  **Sign-in providers** page, and the login page offers a "Sign in with …" button for each
  enabled one. Password sign-in stays.
- Each provider has three switches, all off by default:
  - **create accounts** for people Twinlab does not know;
  - **tie** a sign-in to the existing account with the same verified email;
  - **trust email**, for providers that never state whether an email is verified.

  A provider can also name a default group that newly created accounts join.
- A provider sign-in ends in an ordinary Twinlab session. Provider tokens are discarded, so API
  keys, SSH access, the terminal and the event stream are unchanged.
- Every user now has a **required email**, unique regardless of case, and a **display name**,
  which the UI shows. Only an administrator can change an email, their own included. Users can
  change their own display name.
- Creating a user no longer needs a password: leave it empty and Twinlab generates one and
  shows it once.

**Upgrading:**

- Three new settings are required, and the stack refuses to start without them:
  - `BOOTSTRAP_ADMIN_EMAIL`;
  - `OIDC_SECRET_KEY`, which encrypts providers' client secrets;
  - `FRONTEND_BASE_PATH`, which must be set but may be empty (empty serves the UI at the
    root).
- `PUBLIC_ORIGIN` is new and optional. Provider sign-in stays off until it is set.
- Migration 0023 gives every existing account its username as its display name and the
  placeholder email `<username>@users.invalid`. The Users page flags placeholders until an
  administrator replaces them. A placeholder can never be verified by a provider, so it never
  ties.

**API and `twinlab-client`:**

- User records carry `email`, `display_name` and linked identities.
- `POST /users` (`create_user`) requires `email` and `display_name`, takes an optional
  password, and returns `UserCreated`, which includes the generated password when one was
  made.
- New: profile edits (by an administrator, or of your own display name), unlinking an
  identity, the public provider list, and the provider administration endpoints.
- `twinlab-client` now depends on **httpx2** instead of httpx. httpx2 is the maintained
  continuation of httpx 0.28.1 and has the same API under a new import name. Code that passes
  its own httpx transport or client to `TwinlabClient` must switch to `httpx2`.

## 2026-09-23: An MCP server for AI agents (contract delta 34)

Design record: `docs/mcp-server.md`.

- A new `mcp` service serves Twinlab to AI agents over the Model Context Protocol, at
  `<base path>/mcp` behind the frontend's nginx. It has no host port of its own.
- An agent connects with a Twinlab **API key** as a bearer token and acts as that key's owner,
  through the public API. It can never do more than the key's owner could, and it can do
  nothing the REST API does not offer. Give an agent its own key so it can be revoked on its
  own.
- 29 tools:
  - reading labs, jobs, links, interfaces, facts, usage, logs, impairment, test suites, the
    device catalog, host resources and network templates;
  - the lab lifecycle, test suites, power, impairment and saving config.

  Each tool is marked read-only or not, and destructive or not, so an agent host can ask
  before acting. User, group, grant and key administration are not offered.
- The user guide is served as MCP resources, so an agent can read it.
- The guide's Access page has a new section, "Connecting an agent (MCP)".

**Upgrading:** nothing to configure. `docker compose up -d --build` adds the service. It needs
no secrets and no database.

**API and `twinlab-client`:** unchanged. The MCP server uses the public API through
`twinlab-client`.

## 2026-10-09: Sign-in providers can be limited to email domains (contract delta 35)

Design record: `docs/oidc.md`, "Allowed email domains".

- A sign-in provider has a new setting, **Allowed email domains**. With `example.com` listed,
  the provider ties and creates accounts only for a verified email at exactly `example.com`.
  Anyone else is refused, and the login page tells them their email domain is not allowed.
- The match ignores case and is exact: a subdomain such as `eu.example.com` must be listed on
  its own.
- Empty allows any domain, which is how providers behaved until now.
- People already linked to the provider keep signing in whatever the list says. To stop one,
  unlink or deactivate the account.

**Upgrading:** nothing to configure. The backend's migration gives every existing provider an
empty list, so nothing changes until you set one.

**API and `twinlab-client`:**

- `OidcProvider` gains `allowed_email_domains`.
- `create_oidc_provider` takes it as an optional keyword (omitted = any domain).
  `update_oidc_provider` requires it, like every other field of the replace.
- Entries are bare domain names, stored lowercase. `@example.com` is a 422.
- New sign-in error code: `oidc_email_domain_not_allowed`.

## 2026-11-17: clab-api server v0.10.0

The stack's containerlab API server moves from v0.5.0 to v0.10.0, which bundles containerlab
0.83.0 instead of 0.77.0. Twinlab needs it for the next change: placing lab nodes in a cgroup
(`cgroup-parent`) arrived in containerlab 0.79.

- Every endpoint and setting Twinlab uses is unchanged; the API only gained endpoints.
- A node whose container exits during deploy now has its output in clab-api's log, so
  a crashing daemon names its own error.

**Upgrading:** `docker compose pull clab-api && docker compose up -d clab-api`. No settings
change. Destroy running labs before the switch: a lab deployed by v0.5.0 and managed by v0.10.0
was not tested.

**API and `twinlab-client`:** unchanged.

## 2026-11-17: Labs can boot in waves, and can be kept from taking over a shared host

Design record: `docs/resource-limits.md`.

- **Deploy can boot a lab's nodes in waves**, a few at a time with a pause between, in
  definition order. Starting every node at once saturates the host's CPU: the 7-node VyOS
  example kept about 6 of 8 cores busy for 30 seconds. **Waves are off by default**, because
  the containerlab API holds one lock for the whole of a deploy, and every other lab's status,
  links, interfaces, impairments and node actions wait on it. While a 7-node VyOS lab booted in
  waves, other labs' pages stalled for about 30 seconds. Turn waves on only where one lab
  deploys at a time. The deploy's progress says when a lab boots in waves, and a node whose
  definition sets `clab.startup-delay` keeps its own.
- **Labs and Twinlab's services can be placed in cgroups you limit**, so that on a host shared
  with other work, Twinlab is throttled and swapped instead of the OOM killer ending other
  processes. Labs are slowed, never killed. Twinlab sets no limit itself: you set it once on the
  host (see Upgrading). This is also the way to keep a boot from starving other work without
  waves: give the Twinlab slice a low `CPUWeight`.

**Upgrading:**

- To turn waves on, set `BOOT_WAVE_INTERVAL_SECONDS` (seconds between waves; 0, the default,
  boots everything at once) and, if 2 nodes per wave is not what you want, `BOOT_WAVE_SIZE`.
  With 2 nodes 10 seconds apart, a lab of about 110 nodes or more reaches the deploy's
  600-second timeout, so raise `BOOT_WAVE_SIZE` for labs that size.
- To limit Twinlab on a systemd host, set the limit on the parent slice once, then point
  Twinlab at its two children in `.env` and recreate the stack:

  ```sh
  sudo systemctl set-property twinlab.slice MemoryHigh=16G CPUWeight=20
  ```

  ```sh
  LAB_CGROUP_PARENT=twinlab-labs.slice
  SERVICES_CGROUP_PARENT=twinlab-services.slice
  ```

  Use `MemoryHigh`, not `MemoryMax`: `MemoryMax` is a kill line. The host needs swap, because
  throttling works by paging lab memory out. Running labs move into the slice on their next
  deploy.
- Needs clab-api v0.10.0 (the previous entry).

**API and `twinlab-client`:** unchanged.

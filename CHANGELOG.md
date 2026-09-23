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

# Signing in through OIDC providers (contract delta 33)

**Status: approved 2026-09-23, implemented the same day.** The shapes are in
`docs/twinlab_client_shape.py` under `delta 33`. The notes under
[Implementation](#implementation) record what building it settled. The first review round
(2026-09-23) settled all five open questions and added three requirements: a trust switch for
providers that never send `email_verified`, a required `FRONTEND_BASE_PATH`, and provider icons.
Those are applied below, and the outcomes are recorded under [Review log](#review-log).

## The problem

Twinlab accounts are local. An admin creates each one, picks its password and hands the password
over out of band. The user then has one more credential to keep, which is separate from the
identity system their organisation already runs. Nothing lets that identity system vouch for a
user, so a team that already has Keycloak, Authentik, Entra or Google Workspace has to maintain a
second user directory by hand.

## Decisions (maintainer, 2026-09-23)

1. **Admins configure providers, and there can be several arbitrary ones.** No provider is built
   in, and there is no env-only configuration.
2. **Each provider has two switches, both off by default:**
   - *create users*: an unknown person who signs in gets an account.
   - *email tying*: a person whose email matches an existing account is signed into it.
3. **Verified email is required** for both tying and creation. A third per-provider switch,
   *trust email*, lets an admin vouch for a provider that never states verification (decision
   13).
4. **Password login stays.** OIDC adds a way to sign in and replaces nothing.
5. **Groups are not mapped from the provider.** OIDC proves who the user is, and access is still
   granted in Twinlab. The one concession is a per-provider **default group** that a *newly
   created* user joins, so they are not stranded with no permissions.
6. **Sign out ends only the Twinlab session.** The session at the provider is left alone. That
   is ordinary single sign-on behaviour: the next "Sign in with X" may go straight through
   without a password prompt.
7. **The callback URL is built from `PUBLIC_ORIGIN` + `FRONTEND_BASE_PATH`.** The base path is
   now a required deployment setting shared by the frontend and backend (decision 14).
8. **`users.email` becomes required and unique, and every user gets a display name.** v1.0 has
   not shipped and there is no production data, so the migration carries no risk. Existing users
   are backfilled with a placeholder, and admins can edit any user's email, including their own
   (decision 12).
9. **Every user has a password hash, including provider-only users.** A user created through a
   provider gets a random password that nobody ever sees. Manual creation may also leave the
   password empty, and the server then generates one and returns it once.
10. **Dependencies:**
    - Authlib (BSD-3-Clause) runs the token exchange in the backend, and its own typed
      JOSE library, joserfc (BSD-3-Clause), validates ID tokens (see
      [Implementation](#implementation)).
    - `cryptography` (Apache-2.0 OR BSD-3-Clause) becomes a *direct* dependency for encrypting
      the client secret. It was already installed indirectly.
    - Dex (Apache-2.0) is the test provider in the compose stacks.

    The frontend needs no OIDC library.
11. **Client secrets are encrypted at rest** under `OIDC_SECRET_KEY` (Fernet).
12. **Provider admin is gated by the existing `user:manage` permission**, so the role catalog
    does not change.
13. **Per-provider `trust_email` switch**, off by default. It lets a provider that never sends
    `email_verified` (Microsoft Entra ID being the prominent one) tie and create accounts.
14. **`FRONTEND_BASE_PATH` is required.** Deployment fails when it is not set, and an empty value
    still means the origin root.
15. **Providers carry an icon**, so the login button reads "[G] Sign in with Google".

## The model

### Twinlab stays the session authority

The browser never holds a provider token, and Twinlab stores none either. The provider's only
job is to prove who is at the keyboard, once, at sign-in. After that the user holds an ordinary
Twinlab session: the same opaque cookie, the same TTL, the same revocation. Nothing else in the
stack learns that OIDC exists. API keys, SSH keys, the jump host, `/events` and the terminal all
keep resolving a *Twinlab user*.

Access and refresh tokens are discarded as soon as the ID token has been validated. Keeping them
would only matter for calling the provider's APIs later, which Twinlab never does, and a stored
token is a liability with no feature behind it.

**What this costs:** deactivating someone at the provider does not end a Twinlab session that is
already open. That session lasts until its TTL runs out (8h by default) or until an admin
deactivates the user in Twinlab, and the next sign-in through the provider is refused either way.
Back-channel logout, where the provider pushes the revocation to Twinlab, is the fix. It was
considered and left out (see [Deliberately not in this delta](#deliberately-not-in-this-delta)).

### The flow (authorization code + PKCE, backend-for-frontend)

```
browser                      backend                                   provider
   │  GET /auth/oidc/{p}/login?next=/labs/x                               │
   │ ───────────────────────────▶ row: state#, nonce, verifier, next     │
   │ ◀── 302 + state cookie ──────                                        │
   │  GET authorize?response_type=code&state&nonce&code_challenge(S256)   │
   │ ────────────────────────────────────────────────────────────────────▶│
   │ ◀────────────────────────────────── 302 …/auth/oidc/{p}/callback?code&state
   │  GET /auth/oidc/{p}/callback ───▶ state == cookie? row live? same p?  │
   │                                   POST token (code + verifier) ───────▶│
   │                                   validate ID token (JWKS, iss, aud, │
   │                                     exp, nonce) · resolve user        │
   │ ◀── 302 {origin}{base}{next} + session cookie                        │
```

- **Both endpoints are browser navigations, not API calls.** Their failures therefore cannot
  arrive as the JSON error envelope, because nobody is reading JSON. A failure redirects to
  `{origin}{base}/login?oidc_error=<code>`, and the login page turns the code into a message the
  user can copy. The page renders its own text for each code and never repeats text supplied by
  the provider, so the login page cannot be used to display text an attacker chose.
- **There is one callback per provider**,
  `{PUBLIC_ORIGIN}{FRONTEND_BASE_PATH}/api/v1/auth/oidc/{name}/callback`. The admin registers
  exactly that string at the provider, and the provider admin API shows it ready to copy. The
  pending row is also bound to its provider and the callback checks that it matches. With
  several providers, that check plus RFC 9207's `iss` response parameter (checked when the
  provider sends it) defeats the "mix-up" attack, in which one provider's code is replayed
  against another.
- **State is bound to the browser** by a short-lived HttpOnly `SameSite=Lax` cookie. Lax cookies
  still travel on the provider's top-level redirect back, and a callback whose state does not
  match that cookie is refused. Without the binding, an attacker could complete a login in the
  victim's browser with the *attacker's* code, and the victim would silently be working inside
  the attacker's account.
- **Pending logins live server-side** in a table, never in a signed-cookie session. That keeps
  Twinlab to one session mechanism. The table stores the state only as a hash, the same way
  sessions and API keys are stored. A row expires after 10 minutes and is consumed on the
  callback whatever the outcome, so a code/state pair works exactly once. Expired rows are swept
  when a new login starts.
- **`next` must be a relative path**: it starts with `/`, is not `//`, and contains no scheme.
  Anything else is replaced by `/`. That closes the open redirect every post-login redirect
  otherwise opens.
- **ID-token validation:**
  - the signature against the provider's JWKS (refetched once on an unknown `kid`, to survive
    key rotation)
  - `iss` equals the configured issuer exactly
  - `aud` contains the client id, and when there are several audiences `azp` equals it
  - `exp` and `iat`, with 60 s leeway
  - `nonce` equals the stored nonce

  Claims come from the ID token. **Userinfo is fetched only when the ID token lacks `email` or
  `email_verified`**, which some providers keep to userinfo. Its `sub` must equal the ID token's
  `sub`, or the login fails.

### Resolving the user: link, then tie, then create

The durable identity is **(provider, `sub`)**, which OIDC guarantees stable and unique per
issuer. Email is never the identity. It is used once, to find the account to link, and after
that the link decides.

**When an email counts as verified.** The claim `email_verified` must be exactly `true`. The
string `"true"` does not count; a provider that sends one is non-conformant, and guessing at its
meaning is how verification gets bypassed. On a provider with **`trust_email`** set, an *absent*
`email_verified` also counts as verified. An explicit `false` is still refused, because a
provider that says an address is unverified is believed even when it is otherwise trusted. With
no `email` claim at all, nothing can tie or create.

1. **Linked:** an identity row for (provider, `sub`) exists, so it names the user. An inactive
   user is refused (`account_disabled`). The user's Twinlab email and display name are *not*
   overwritten from the claims. They are Twinlab data now, and syncing email could collide with
   the uniqueness rule in the middle of a sign-in.
2. **Tie** (only if the provider allows it): the email must count as verified. It is matched
   against `users.email` case-insensitively. If the matched user is already linked to a
   *different* `sub` on this provider, the sign-in is refused (`oidc_identity_conflict`), because
   a user has at most one identity per provider. Otherwise the link is written and the user is
   signed in.
3. **Create** (only if the provider allows it): this also requires a verified email. An
   unverified address would claim an email in the unique column that the real owner could then
   never use. The new account gets:
   - `email` and `display_name` from the claims. The display name is `name`, else
     `preferred_username`, else the email.
   - a username derived from `preferred_username`, else the email's local part. It is truncated
     to 64 characters and suffixed `-2`, `-3`, … on a collision. The suffix is deterministic, so
     the same collision always yields the same name.
   - a random password that is never shown to anyone.
   - the baseline `user` role, plus membership in the provider's default group when one is set.

   The link is written in the same transaction as the user.
4. Otherwise the sign-in is refused with the most specific reason that applies:
   - `oidc_email_missing`: creation is allowed, but the provider sent no `email` claim
   - `oidc_email_unverified`
   - `oidc_email_in_use`: the email belongs to an account, but this provider does not tie
   - `oidc_no_account`: nothing to link, tie or create

**Why tying needs verification:** without it, anyone who can put an arbitrary address on their
provider account can sign into the Twinlab account that owns that address, including an admin's.
For the same reason **an existing user cannot change their own email unless they hold
`user:manage`.** If any user could, a malicious one could set their email to a colleague's, and
the colleague's first provider sign-in would tie *into the attacker's account*. Admins can edit
any user's email, their own included, through the admin route.

**What `trust_email` actually trusts.** Setting it asserts that *every* address the issuer can
put in an `email` claim belongs to the person signing in. That holds for a tenant that controls
its whole mail domain. It does not hold for a multi-tenant issuer, or for one where users can
edit their own email attribute. Entra ID is a case in point: its `email` claim is an optional,
user-editable attribute unless the tenant restricts it. The admin UI puts that sentence next to
the switch, and the switch only matters when tying or creation is also on.

### Provider configuration

A provider is a database record managed under the existing **`user:manage`** permission. A
provider decides who gets an account, which is user management by another route, so the role
catalog does not change.

| Field | Rule |
| --- | --- |
| `name` | URL slug `^[a-z0-9][a-z0-9-]{0,31}$`, unique. It appears in the callback URL, so renaming it would break the registered client, and it is therefore **immutable**. |
| `display_name` | The button label, e.g. "Google". The button reads "Sign in with {display_name}". Required, 1–64 characters. |
| `issuer` | Unique across providers and **immutable**. Links are keyed by the provider, so re-pointing a provider at another issuer would silently map one issuer's `sub`s onto another's people. Changing the issuer means deleting the provider and creating a new one. |
| `client_id` | Required. |
| `client_secret` | **Write-only, encrypted at rest.** Reads say only `has_client_secret`. It is omitted on update to keep the current one and set to `null` to remove it, which makes a public client (PKCE alone). The token-endpoint auth method is taken from discovery: basic when supported, otherwise post. |
| `scopes` | The default is `["openid", "email", "profile"]`, and `openid` is always required. The default comes from what the resolution rules need: `email` for tying and creation, `profile` for the display name and username. |
| `allow_create_users` / `allow_email_tying` | Both `false` by default. The safe state is a provider that can only sign in users who are already linked. |
| `trust_email` | `false` by default. When set, an absent `email_verified` counts as verified (see above). |
| `default_group_id` | An optional group joined *at creation only*, never re-applied on later sign-ins. If the group is deleted, the reference becomes null. |
| `enabled` | `false` hides the provider from the login page and refuses sign-in through it, while keeping its links. |
| icon | Optional, set through its own route (see [Icons](#icons)). |

**Discovery is checked when the provider is created, not when someone first signs in.** Create
fetches `{issuer}/.well-known/openid-configuration` synchronously and requires the document's
`issuer` to equal the configured one. Update does NOT refetch it: the issuer cannot change, and
an admin must be able to edit a provider whose discovery endpoint is down, above all to disable
it. A bad issuer is then a 422
`oidc_discovery_failed` in front of the admin who typed it, rather than a login failure for the
first user. The document and JWKS are cached in-process and refreshed on an unknown `kid`, or at
the latest after an hour.

**Deleting a provider deletes its links and leaves the users.** A user created through that
provider then holds only a random password nobody knows, so they cannot sign in until an admin
resets their password or links them elsewhere. The delete response does not block on this
(an admin may be removing a compromised provider on purpose), and the admin UI warns with the
count first.

### The client secret at rest

The secret has to be *retrievable* to call the token endpoint, so unlike sessions and API keys it
cannot be hashed. It is encrypted with **Fernet** (AES-128-CBC + HMAC-SHA256, from
`cryptography`) under `OIDC_SECRET_KEY`. A database dump therefore does not hand out working
client credentials, which is the bar sessions and API keys were already held to.

- **`OIDC_SECRET_KEY` is a Fernet key**: 32 random bytes, URL-safe base64. It is validated when
  settings load, so a malformed key fails startup instead of failing the first decrypt. To
  generate one: `openssl rand -base64 32 | tr '+/' '-_'`.
- **Optional in code, required by compose.** This is the `JUMP_TOKEN` / `HOSTPREP_TOKEN`
  pattern: the backend runs without the key, and a *deployed* stack cannot ship without it. When
  the key is unset in code, saving a provider **with** a secret is a 409
  `oidc_secret_key_unset`. Public clients still work.
- **Losing or changing the key** makes the stored secrets unreadable. A sign-in through an
  affected provider fails with `oidc_unavailable`, and the admin read reports
  `client_secret_readable: false` so the fix is visible: re-enter the secret. Key rotation, where
  one key encrypts and several decrypt, is `MultiFernet` and cheap to add, but nothing asks for
  it yet.

### Icons

Each provider can carry an **admin-uploaded icon**, and the login button renders it before the
label: "[G] Sign in with Google". Without one, the button shows a **monogram**, the first letter
of the display name in a circle. So "G Sign in with Google" works with no upload at all, and an
uploaded logo replaces the letter.

- **Upload:** `PUT /oidc-providers/{name}/icon` with the image as the raw body and its
  `Content-Type`, and `DELETE` to clear it. Accepted: `image/svg+xml`, `image/png`,
  `image/webp`, up to **32 KiB**, which is plenty for a button glyph. The bytes are checked
  against the declared type: PNG and WebP by their magic bytes, and SVG must parse as XML with an
  `<svg>` root. A mismatch is a 422 `invalid_icon`.
- **Served inline as a `data:` URI** on the unauthenticated provider listing and on the admin
  read, never from a URL of its own. That is the deciding property for SVG. An SVG can carry
  script, and one served from a Twinlab URL would run it on Twinlab's origin if someone opened
  the URL directly. A `data:` URI rendered through `<img>` runs no script, and browsers refuse to
  open `data:` URLs as a top-level page. There is therefore no SVG sanitiser to maintain. The
  price is payload size: the listing carries every enabled provider's icon, at most 32 KiB each,
  on a page loaded once per sign-in.
- **Twinlab ships no brand logos.** A provider's logo is the provider's trademark, and no icon
  set's license grants trademark rights. The biggest brand-icon set, Simple Icons, is also CC0,
  which is not OSI-approved and so does not clear Twinlab's licensing bar. The deployer, who
  already has a relationship with the provider, uploads the mark. Google's sign-in branding
  guidelines, for example, publish the "G" for exactly this use.

### Users, the other half of this delta

- **`email` is required and unique case-insensitively** (a unique index on `lower(email)`). It is
  stored as entered. Validation is structural only: one `@`, a non-empty local part and domain,
  no whitespace. There is no DNS or deliverability check, because that would need a network call
  and a new dependency to prove something a provider verifies better.
- **`display_name` is required**, 1–128 characters, and is what the UI shows. `username` stays
  the login name for password sign-in and the principal name for RBAC, unchanged.
- **The password on `POST /users` is optional.** When it is omitted, the server generates one
  (`secrets.token_urlsafe(18)`, 24 characters) and returns it **once** in `UserCreated`. That is
  the pattern API keys and generated SSH keys already use.
- **Profile edits.** `PUT /users/{id}/profile` (`user:manage`) edits `email` and `display_name`
  for ANY user, **the caller included**, so an admin fixes their own backfilled address there.
  `PUT /auth/profile` edits only the caller's own `display_name`. Email is excluded from
  self-edit for the reason given under the resolution rules above.
- **Linked identities are visible and removable.** `UserSummary.identities` lists them, and
  `DELETE /users/{id}/identities/{identity_id}` (`user:manage`) unlinks one. The next sign-in
  through that provider then goes through the tie/create rules again. Unlinking is how an admin
  repairs a tie that went to the wrong account.

**Migrating existing users.** Every existing row is backfilled with `display_name = username`
and `email = <username>@users.invalid`. The `.invalid` TLD is reserved by RFC 2606, so no
provider can ever verify such an address, and a backfilled account can never be the target of a
tie. The admin UI flags a `.invalid` address as a placeholder to replace. This keeps every
existing stack (dev, e2e, nokia, internal) upgradable in place, instead of forcing a database
reset.

**The bootstrap admin** needs an email like everyone else, so **`BOOTSTRAP_ADMIN_EMAIL`** joins
the required settings. Its display name is its username, since it is the break-glass account and
a second required variable would buy nothing. The variable is read only when the users table is
empty, but it is required on every start, like the other two bootstrap variables, so a stack
that gets reset cannot come up without it.

### The public URL: origin + base path

The callback URL and the post-login redirect need the address the *browser* uses. The backend
sits behind the frontend's nginx and cannot see that address, so it is configured in two parts:

- **`FRONTEND_BASE_PATH` is REQUIRED for every deployment** (decision 14). Compose spells it
  `${FRONTEND_BASE_PATH?…}`, so an unset variable fails `docker compose up`, while an EMPTY value
  is the explicit "served at the origin root". That keeps today's meaning of `''` rather than
  inventing a `/` spelling. Compose passes the same variable to BOTH the frontend build (as
  today) and the backend. It is therefore stated once and cannot drift between the two, which a
  `PUBLIC_URL` that repeated the base path could have. The backend validates the frontend build's
  rule: empty, or a leading `/` with no trailing `/`.
- **`PUBLIC_ORIGIN`**, e.g. `https://tools.example.com`, is scheme, host and optional port, with
  no path. It is **optional**: unset means OIDC sign-in is off. `GET /auth/oidc/providers`
  returns `[]`, login and callback redirect with `oidc_error=oidc_unavailable`, and provider
  records can still be edited, with `callback_url: null`, so an admin can prepare providers
  before the address is settled. Making it required would force a sign-in URL onto deployments
  that do not use OIDC.

The backend's settings loader treats every required variable as non-empty today. It gains the
distinction "required but may be empty" for `FRONTEND_BASE_PATH`, and that distinction stays in
the loader instead of becoming a fallback.

## Wire surface

| Route | Gate | What |
| --- | --- | --- |
| `GET /auth/oidc/providers` | **none** | The enabled providers, as `{name, display_name, icon}`. The login page needs this before anyone is authenticated, so it exposes nothing beyond the buttons. |
| `GET /auth/oidc/{name}/login?next=` | none | Starts the flow with a 302 to the provider. |
| `GET /auth/oidc/{name}/callback` | none | Finishes it with a 302 to `next` plus the session cookie, or to the login page with `oidc_error`. |
| `GET /oidc-providers` · `POST` | `user:manage` | List and create. |
| `GET /oidc-providers/{name}` · `PUT` · `DELETE` | `user:manage` | Read, replace (with the `client_secret` rule above) and delete. |
| `PUT /oidc-providers/{name}/icon` · `DELETE` | `user:manage` | Set the icon (raw body) or clear it. |
| `POST /users` | `user:manage` | Gains `email` and `display_name` (required) and an optional `password`, and returns **`UserCreated`**. |
| `PUT /users/{id}/profile` | `user:manage` | Edits `email` and `display_name` for any user, the caller included. |
| `DELETE /users/{id}/identities/{identity_id}` | `user:manage` | Unlinks one identity. |
| `PUT /auth/profile` | authenticated | Edits the caller's own `display_name`. |
| `GET /auth/me` | authenticated | `UserInfo` gains `email` and `display_name`. |

New slugs:
- API errors: 409 `email_taken`, 409 `provider_name_taken`, 409 `issuer_taken`, 409
  `oidc_secret_key_unset`, 422 `oidc_discovery_failed`, 422 `issuer_immutable`, 422
  `invalid_icon`, 404 `provider_not_found`, 404 `identity_not_found`.
- Callback codes (`oidc_error=`): `oidc_unavailable`, `oidc_state_invalid`,
  `oidc_provider_error`, `oidc_token_invalid`, `oidc_email_missing`, `oidc_email_unverified`,
  `oidc_email_in_use`, `oidc_no_account`, `oidc_identity_conflict`, `account_disabled`.

**The Python client gets no `login_with_oidc`.** The flow needs a browser and a person at the
provider's login form, and `twinlab-client` is headless. Automation for an OIDC user works the
way it already does: sign in once in the browser, create an API key, and use the key. The client
gains the provider admin methods, the icon methods, the profile methods and the new
`create_user` shape.

## Storage

- `users`: `email` becomes NOT NULL (after the backfill), with a unique index on `lower(email)`,
  and `display_name` is a new NOT NULL column.
- `oidc_providers`: the fields in the table above, with `client_secret` stored as its Fernet
  token (nullable), plus `icon` (bytes, nullable), `icon_type` and the timestamps.
- `user_identities`: `user_id` (cascade), `provider_id` (cascade), `subject` (255 characters),
  `email_at_link` (kept for audit, since the claim's email can drift), `created_at` and
  `last_login_at`. It is unique on `(provider_id, subject)` and on `(user_id, provider_id)`.
- `oidc_login_attempts`: `state_hash`, `provider_id` (cascade), `nonce`, `code_verifier`,
  `next_path`, `expires_at`. Rows are short-lived and swept.

## Deployment

- **compose.yaml:**
  - `FRONTEND_BASE_PATH` becomes `${FRONTEND_BASE_PATH?…}` and is passed to the backend too.
  - `OIDC_SECRET_KEY` becomes `${OIDC_SECRET_KEY:?…}`.
  - `BOOTSTRAP_ADMIN_EMAIL` becomes `${BOOTSTRAP_ADMIN_EMAIL:?…}`.
  - `PUBLIC_ORIGIN` is passed through as optional.
- **`.env.example` and the install guide** (`docs/guide/01-install.md`) document all four. The
  dev and e2e stacks' env gains them; the e2e stack's `PUBLIC_ORIGIN` points at its own frontend
  port.
- **Existing `.env` files break on purpose.** A stack whose `.env` lacks `FRONTEND_BASE_PATH`,
  `OIDC_SECRET_KEY` or `BOOTSTRAP_ADMIN_EMAIL` stops coming up until they are added. That is
  what a required setting means. The upgrade note says so in one line with the three values to
  add.

## Frontend

- **Login page:** a "Sign in with {display_name}" button per provider, below the password form
  and outside it. Each shows the provider's icon, or the monogram. Each is a plain link
  (`<a href>`), not a fetch, because it is a navigation. An `oidc_error` renders as a copyable
  message, as every failure in the UI already does.
- **Users admin:**
  - Create gains email and display name, and a password field whose empty state says "leave
    empty to generate". A generated password is shown once, with a copy button.
  - The user view lists linked identities with an Unlink action.
  - Email and display name are edited in place, and a `.invalid` placeholder is flagged.
- **Sign-in providers:** a new admin page (`user:manage`) with the provider form.
  - The callback URL is shown for copying.
  - An icon picker shows a preview of the button as it will render.
  - `trust_email` carries its warning inline.
  - An unreadable secret is flagged.
  - The delete dialog names how many users would be left without a way to sign in.
- **App header and Account page:** they show the display name. The Account page lets the user
  edit their own display name and lists their linked identities read-only.

## Testing

- **Unit:**
  - the resolution rules as a pure function over (claims, provider switches, the lookups it
    needs), covering every branch, including `trust_email` with an absent, `true`, `false` and
    `"true"` claim
  - the case-insensitive email match
  - `next` sanitising and username derivation
  - icon type sniffing
  - the settings loader's required-but-may-be-empty rule
- **Blackbox:**
  - provider CRUD, including issuer immutability, the write-only secret, discovery failure
    against an unreachable issuer, and the icon round trip
  - the new `create_user` shape and generated password
  - email uniqueness, profile edits (an admin's own included) and unlinking
  - one headless walk of the whole flow against **Dex**. That is a test helper, not a client
    method: httpx follows the redirects and posts Dex's local password form.
- **e2e:** the browser flow against Dex, driven through the real login page:
  - sign in creating an account
  - sign in tying an existing one
  - a refused sign-in rendering its message
  - the button rendering an uploaded icon
- **The test-provider trap:** the issuer must be ONE URL that both the browser and the backend
  container can resolve, because the ID token's `iss` is compared exactly. The test stacks
  therefore give Dex a hostname mapped via `extra_hosts: host-gateway` inside the backend, and
  the same hostname on the host. That is settled at implementation. It is the one Dex setup
  detail that is not in its static YAML.

## Implementation

What building it settled, beyond the design above.

- **The HTTP client moved to httpx2 first.** Authlib 1.8 expects `httpx2` and warns on plain
  `httpx`, and httpx itself has had no release since 0.28.1 (December 2024). httpx2 is its
  Pydantic-maintained continuation (BSD-3-Clause), forked from that exact release with no public
  API change. The whole tree switched in a commit of its own, before this delta: the backend,
  the client, the hostprep tests and the blackbox suite.
- **Authlib for the exchange, joserfc for the token.** Authlib's own JOSE module
  (`authlib.jose`) is deprecated in favour of joserfc, its author's typed successor, which
  Authlib now depends on. So `AsyncOAuth2Client` performs the code exchange (client
  authentication and the PKCE verifier), and joserfc verifies the ID token and its claims.
  Authlib ships no type information, so `backend/typings/authlib/` declares the small surface
  used, as `typings/` already does for napalm and textfsm.
- **The asymmetric algorithms only.** Discovery's `id_token_signing_alg_values_supported` is
  intersected with RS, PS, ES and EdDSA. `none` is never acceptable, and HMAC would make the
  client secret a signing key. A provider offering nothing else is refused at create.
- **Failure detail goes to the backend log.** The callback redirect carries only the code, so
  the reason ("the token endpoint refused the code (invalid_grant)") is logged as a warning on
  the `twinlab.oidc` logger. That is the first place to look when a provider will not sign
  anyone in: `docker compose logs backend`.
- **`oidc_email_missing` joined the codes.** Creation with no `email` claim at all was folded
  into `oidc_email_unverified` in the design. It is a different fix for the admin (request the
  `email` scope or map the claim), so it got its own code.
- **The test provider** is `oidc-test/compose.yaml`, an overlay that adds Dex to any stack. Its
  issuer is `http://dex.localhost:<DEX_PORT>/dex`. Browsers and the host resolve `*.localhost`
  to loopback on their own, and the overlay maps that name to the host gateway inside the
  backend, so both sides see one URL.

## Deliberately not in this delta

- **Group or role mapping from claims.** Decided against (decision 5). The provider record could
  later gain a claim name and a mapping table without changing anything here.
- **Signing out at the provider**, whether RP-initiated or back-channel logout. Decided against
  (decision 6). Back-channel logout is the one real gap, since it is how a provider-side
  deactivation would end an open Twinlab session. It is parked, not rejected.
- **Linking from the Account page** ("connect my Keycloak account"). Tying already covers the
  common case, and a self-service link flow is a second flow with its own consent questions.
- **Syncing profile data on every sign-in.** Syncing email conflicts with uniqueness, and a
  display name the admin corrected should stay corrected.
- **Bundled brand icons.** Trademark and licensing, as covered under [Icons](#icons).
- **Rotating `OIDC_SECRET_KEY`** (`MultiFernet`). Cheap, but nothing asks for it yet.
- **SAML, LDAP, and plain OAuth2 providers without OIDC** (e.g. GitHub). OIDC only, which is
  what every mainstream identity product speaks. Dex can front GitHub or LDAP for an
  organisation that needs them.
- **Hiding or disabling password login.** Decided against (decision 4).

## Review log

**Round 1 (2026-09-23).** The five DISCUSS items, all resolved:

1. **The client secret at rest:** encrypted under `OIDC_SECRET_KEY`, making `cryptography` a
   direct dependency. Agreed, now decisions 10 and 11.
2. **Migrating existing users:** backfilled with the `.invalid` placeholder. Agreed on the
   condition that admins can update emails, their own included. `PUT /users/{id}/profile` covers
   every user, the caller too.
3. **The bootstrap admin:** `BOOTSTRAP_ADMIN_EMAIL` is required, and the display name is the
   username. Agreed.
4. **Providers without `email_verified`:** the recommendation was to defer a trust switch. The
   maintainer chose to add it now, so it is decision 13.
5. **Permission:** `user:manage` is reused. Agreed, decision 12.

The maintainer also added: `FRONTEND_BASE_PATH` is required and deployment fails without it
(decision 14, which also replaced the draft's single `PUBLIC_URL` with `PUBLIC_ORIGIN` + the
shared base path), and provider icons (decision 15).

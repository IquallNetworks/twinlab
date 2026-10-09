# 7. Access

Who can do what, and how to reach lab nodes from your own machine.

## Users

Twinlab's users are its own, separate from the host account clab-api
authenticates as. The first one is the bootstrap admin from
[Install](01-install.md).

Managing users needs `user:manage`. You can create them, reset passwords,
deactivate them and delete them.

Every user has an **email**, unique regardless of case, and a **display name**,
which is what the UI shows. The username stays the name you sign in with and the
name grants refer to. When you create a user you can leave the password empty.
Twinlab then generates one and shows it **once**, with a copy button, so hand
it over then. An administrator edits anyone's email and display name, their own
included, through **Profile** on the user's row. Users can change their own
display name on the Account page, but not their email. The reason is in the
next section.

**Resetting someone's password** is a button on their row in the Users page. It
asks for no current password — an administrator does not know it — and signs
out every session that user has open, so tell them the new one. Their API keys
and SSH keys are separate credentials and keep working. Your own row does not
offer it: the reset would revoke the session you are working in.

**Deactivating** is the reversible half of deletion. It signs out the account's
sessions and stops its API keys and SSH keys authorizing, while the record, its
roles and the labs it owns stay exactly as they were — activating again
restores access. **Deleting** removes the account with its credentials and every
role it holds; labs it owned are kept, with no owner.

Twinlab refuses to deactivate or delete the **only active administrator**, with
a `last_admin` error. That guard exists so nobody locks the deployment out of
itself. The Users page refuses both on your own row for the same reason — each
would end the session you are working in.

Changing your own password on the Account page keeps you signed in. It does not
touch your other sessions.

## Signing in through an identity provider

Twinlab can let people sign in through an external identity provider that
speaks OpenID Connect: Keycloak, Authentik, Microsoft Entra ID, Google and the
like. Password sign-in stays available beside it. Configure providers on the
**Sign-in providers** page, which needs `user:manage`. The deployment must
have `PUBLIC_ORIGIN` set ([Install](01-install.md#configuration)). Without it
the page still edits providers, but the login page offers none.

For each provider you give the **issuer** (the provider's base URL, exactly as
its discovery document states it), a **client id** and usually a **client
secret**. Register the client at the provider with the **redirect URI** the page
shows. Twinlab fetches the provider's discovery document when you add it, so a
mistyped issuer is refused on the spot. The issuer and the name cannot change
afterwards. To point at another issuer, add a new provider.

Who a sign-in lands as is decided in this order:

1. **Someone already linked** to this provider signs in as their account.
2. **Tie to existing accounts by email** (off by default): a person whose
   **verified** email matches an account is linked to it and signed in.
3. **Create accounts** (off by default): anyone else with a verified email gets a
   new account. It has the baseline `user` role, plus the provider's **default
   group** if you set one. It also gets a random password nobody knows, so
   password sign-in stays closed until an administrator resets it.

With neither switch on, a provider only signs in people you have already
linked. That is the safe starting point. **Verified** means the provider said
so. Tying by email is how an account gets claimed, and an unverified address is
one anyone could have typed. That is also why nobody but an administrator can
change an account's email: a user who set their email to a colleague's would
receive that colleague's first sign-in. **Trust this issuer's emails** makes a
provider that never states verification count as verified. Entra ID is the
common case. Turn it on only for an issuer whose tenant owns every address it
can put in a sign-in.

**Allowed email domains** narrows both switches to your own people. With
`example.com` listed, tying and creating accept only a verified email ending in
`@example.com`, and anyone else is refused with a message saying their domain
is not allowed. The match is exact and ignores case: `eu.example.com` is a
different domain, so list each subdomain you want. Empty, the default, allows
any domain. The list does not apply to someone already linked: a link is the
identity itself, so narrowing the list later leaves existing links signing in.
Unlink or deactivate an account to stop it. Restricting the domains matters most
for a public provider such as Google, where anyone can have an account.

Each person's linked providers are listed in their **Profile**. **Unlink**
removes one, and the next sign-in through that provider goes through the rules
above again. Unlinking is how you repair a tie that landed on the wrong account.
Deleting a provider removes its links and keeps the accounts. To stop sign-ins
without losing the links, disable the provider instead.

A provider can carry an **icon** (SVG, PNG or WebP, at most 32 KiB), shown on
its login button. Without one the button shows the first letter of its label.
Twinlab ships no provider logos, because they are the providers' trademarks.
Upload the one your provider publishes for sign-in buttons.

**Signing out** of Twinlab ends the Twinlab session only. The provider's own
session is left alone, so the next "Sign in with …" may go straight through
without a password prompt. Deactivating someone at the provider does not end a
Twinlab session they already have open either. Deactivate them in Twinlab to
cut them off at once.

When a sign-in fails, the login page says why in general terms, such as "no
account for you yet" or "the provider's answer could not be verified". The
exact reason goes to the backend's log, where an administrator can read it:
`docker compose logs backend | grep "oidc sign-in"`.

## Permissions

A permission is either **lab-scoped** or **global-only**.

| Permission | Lets you |
| --- | --- |
| `lab:read` | see the lab, its state, its events and its suite results |
| `lab:edit` | edit the definition, deploy, author suites and custom config |
| `lab:configure` | push configuration, power nodes, save config, set impairment |
| `lab:validate` | run test suites on demand |
| `lab:terminal` | open a terminal, and reach the lab over SSH |
| `lab:destroy` | destroy the lab |
| `lab:grant` | give other people access to this lab |

| Global-only permission | Lets you |
| --- | --- |
| `lab:create` | create a lab, becoming its owner |
| `user:manage` | manage users |
| `group:manage` | manage groups |
| `template:manage` | publish network templates and manage node templates |

Reading the template library needs no permission at all.

### Roles and bindings

You do not grant permissions directly. You create a **binding**, which ties a
**principal** — a user or a group — to a **role**, at a **scope**. The scope is
either global or one specific lab.

Roles that bind globally:

| Role | Grants |
| --- | --- |
| `admin` | everything |
| `global_operator` | every lab permission on every lab, plus `lab:create` and `template:manage` |
| `global_viewer` | `lab:read` on every lab |
| `creator` | `lab:create` only |
| `user` | nothing — the baseline every new user gets |

Roles that bind to one lab:

| Role | Grants on that lab |
| --- | --- |
| `lab_owner` | every lab permission, including grant and destroy |
| `lab_manager` | everything except destroy |
| `lab_operator` | read, configure, validate, terminal — operate, not edit |
| `lab_viewer` | read |

A global binding of a lab-scoped role means "on every lab, including labs that
do not exist yet".

**A lab's owner holds `lab_owner` on it implicitly.** There is no binding row,
and you cannot remove it. Whoever created the lab keeps it.

Your effective permissions on a lab are the union of everything that applies:
your own bindings, your groups' bindings, and ownership.

`user` granting nothing is deliberate. A new account can sign in and see the
shell of the application. Access is something somebody gives it.

## Granting access to a lab

The lab's **Access** tab appears only if you hold `lab:grant` there. Add a
binding by choosing a principal and a role.

**Prefer granting to a group.** A group binding survives people joining and
leaving, and it is one row to audit instead of ten. Per-person bindings on a
lab are for exceptions.

This is what lets a lab owner delegate without an administrator. You own a lab,
so you can hand `lab_operator` to the people who need to drive it. Nobody has to
widen a global role to make that work.

## API keys

An API key is a second credential for the same account, with the same
permissions. Create one on the Account page.

**Twinlab shows the secret once.** It stores only a hash, so you replace a lost
key rather than recovering it.

A key dies with its user. Deactivate or delete the account and every key it
owns stops working immediately.

Use a key for scripts and CI. Use your session for the browser.

### Connecting an agent (MCP)

Twinlab serves the Model Context Protocol at `/mcp` on the same address as the
UI: `<twinlab-address>/mcp`, where `<twinlab-address>` is what you type to open
Twinlab, such as `https://twinlab.example.com`. Point an MCP client at that
URL over streamable HTTP and send an API key as a bearer token:

```
Authorization: Bearer <your-api-key>
```

The agent can then list, read, deploy, operate and destroy labs, and read this
guide. It acts as you, with exactly your permissions: a lab you cannot read is
invisible to it, and an action you cannot take comes back to it as a refusal.
It cannot manage users, grants or keys.

Give an agent its own key, so you can revoke it without disturbing your
scripts. Never give one key to an agent that several people use: it would act
as you for all of them.

## SSH to lab nodes

Lab nodes are not on your network. A **jump host** stands in front of them.

### How it works

The jump host runs one forwarding-only account. When you connect, it asks the
backend which addresses your key may reach. The backend answers with the
management addresses of every lab where you hold `lab:terminal`.

That lookup happens **on every connection**. Revoking a key, a grant or a whole
user takes effect on the next connect, with nothing to clean up on the jump
host.

### Register a key

On the Account page, either upload a public key you already have, or let the
server generate a pair. Twinlab shows a generated private key once and never
stores it.

### Connect

Add the jump host to `~/.ssh/config`:

```
Host twinlab-jump
  HostName <jump-host>
  Port <jump-port>
  User jump
  IdentityFile ~/.ssh/<your-registered-key>
  IdentitiesOnly yes
```

`<jump-host>` and `<jump-port>` are your deployment's jump host. **Copy them
from the Account page**, which shows the address this Twinlab advertises: the
host and port depend on how the deployment was installed, so no value printed
in this guide is yours. `<your-registered-key>` is the private key whose public
half you registered above. The Account page also shows this block with the
address filled in.

Then reach a node by its management address:

```bash
ssh -J twinlab-jump vyos@<mgmt-address>
```

`<mgmt-address>` is the node's management address, from the Nodes tab or the
node's Connect drawer. It changes from lab to lab, since each lab gets a subnet
of its own. `vyos` is the VyOS login: use the one for the node's platform.

### Do not use a bare `ssh -J` with `-i`

This costs everyone an afternoon exactly once.

```bash
ssh -J jump@<jump-host>:<jump-port> -i ~/.ssh/<your-registered-key> vyos@<mgmt-address>   # fails
```

Command-line identity options do **not** apply to the jump hop. The hop is its
own connection and never sees your `-i`, so it fails there with
`Permission denied (publickey)`. Worse, the message reads as though the *node*
refused you, which sends you debugging the wrong host.

Put the identity in a `Host` block, as above, or write an explicit
`ProxyCommand`. The Connect drawer on the Nodes tab hands you both forms with
the real address filled in.

### Reaching nodes by name

The Nodes tab also hands out a per-node alias block, and the whole lab's blocks
at once:

```
Host r1.mylab
  HostName <r1-mgmt-address>
  User vyos
  ProxyJump twinlab-jump
```

Here the lab is `mylab` and the node `r1`. The blocks the tab hands out carry
your own names and the real addresses.

```bash
ssh r1.mylab
```

**Your machine resolves the alias, and nothing else sees it.** `HostName` stays
the management address on purpose. The jump host matches its address
restrictions literally and performs no name lookup. It therefore refuses a name
nobody told it about, however well that name resolves locally.

### Ansible

A deployed lab is reachable over the same path, so it is Ansible-ready with no
extra machinery. Point your inventory at the management addresses and set the
same `ProxyJump` in your SSH configuration.

## The web terminal

The Nodes tab opens a terminal in the browser. It needs `lab:terminal`, the same
permission as SSH.

Use it for a quick look — it needs no key registration and no SSH configuration.
Use real SSH when you want your own tooling, file transfer, or automation.

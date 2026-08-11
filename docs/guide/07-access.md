# 7. Access

Who can do what, and how to reach lab nodes from your own machine.

## Users

Twinlab's users are its own, separate from the host account clab-api
authenticates as. The first one is the bootstrap admin from
[Install](01-install.md).

Managing users needs `user:manage`. You can create them, reset passwords,
deactivate them and delete them.

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
  HostName localhost
  Port 2222
  User jump
  IdentityFile ~/.ssh/<your-registered-key>
  IdentitiesOnly yes
```

Then reach a node by its management address:

```bash
ssh -J twinlab-jump vyos@10.77.0.101
```

### Do not use a bare `ssh -J` with `-i`

This costs everyone an afternoon exactly once.

```bash
ssh -J jump@host:2222 -i ~/.ssh/mykey vyos@10.77.0.101   # fails
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
  HostName 10.77.0.101
  User vyos
  ProxyJump twinlab-jump
```

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

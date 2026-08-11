# What a test command means, and how it gets there (contract delta 28)

Design record of the 2026-08-10 discussion. Approved: **A** (a command's
language) and **C** (`interactive` over the docker transport). **B** (a per-test
transport selector) was considered and **deferred** — reasoning at the bottom.

## The defect

`TestCase.command` was "a string handed to `netlab exec`", which says nothing
about which interpreter receives it. `netlab exec` on a docker-connection device
runs `docker exec <node> <docker_shell> -c "<command>"`, and VyOS's
`docker_shell` is `su - vyos` — so the words land in a **non-interactive Debian
shell**, not the VyOS CLI.

The live failure: `examples/mpls-l3vpn.test-suites.json` asserted a VRF-scoped
ping with VyOS op-mode syntax (`ping 10.2.0.4 vrf vpn_a count 5`). That reached
`/bin/ping`, which has no `vrf` flag, and the suite saw an empty stdout — no
explanation anywhere. Its sibling `examples/mixed-nos.test-suites.json` uses
Linux syntax (`ping -c 3 -W 2`) for the same device and passes, so the two
shipped examples disagreed about what a command even is.

Root cause is not the transport: it is that **the language was never modeled**.

## What op-mode actually depends on

Measured on a running VyOS node (2026-08-10), same command every time:

| Invocation | Result |
| --- | --- |
| `su - vyos -c "ping … vrf …"` (what `netlab exec` runs) | `ping: vrf: System error` |
| same, with a PTY (`docker exec -t`) | `ping: vrf: System error` |
| piped into `su - vyos` (non-TTY stdin) | `ping: vrf: System error` |
| `su - vyos -c "vbash -i -c 'ping … vrf …'"` | **0% packet loss** |
| `/opt/vyatta/bin/vyatta-op-cmd-wrapper ping … vrf …` | **0% packet loss** |
| PTY-backed `docker exec -it … su - vyos`, typed | **0% packet loss** |

So VyOS op-mode is installed by **interactive shell initialization**, not by the
transport. Two ways in: the wrapper (works non-interactively) or a genuinely
interactive session. Notably `ssh node "cmd"` is *also* a non-interactive login
shell — which is why switching transports would not have fixed this.

## A — `mode: shell | cli`

Per case, default `shell`, so no stored suite changes meaning. `cli` says "these
words are the device's own CLI" and the backend rewrites them
(`services/cli_adapters.py`, the one place with this knowledge, beside the
catalog and `DEVICE_KMODS`):

| device | non-interactive | interactive |
| --- | --- | --- |
| vyos | `vyatta-op-cmd-wrapper <cmd>` | native (already op-mode) |
| frr | `vtysh -c '<cmd>'` | `vtysh -c '<cmd>'` (a binary, mode-independent) |
| bird | `birdc <cmd>` | `birdc <cmd>` |
| routeros7, iol | identity — the transport already lands in the CLI | identity |
| linux, dnsmasq | **error**: no CLI of its own | error |

That last row is a 422 at PUT (a device-keyed case names its device, so it is
caught even before a lab has facts) and an `error` result at run time — never a
silently mis-sent command.

`TestResult.command` now reports the **adapted** command: it is what actually
ran, and it is what someone debugging would paste.

Config-diff's hard-coded `vyatta-op-cmd-wrapper` — previously the only place in
the tree that knew this trap — becomes `show configuration commands` with
`mode: cli`, adapted through the same table.

## C — `interactive` over the docker transport

`interactive: true` used to fall through to the one-shot path on docker nodes:
the flag an author reaches for when a command misbehaves did *nothing*, quietly.
It now opens a PTY-backed `docker exec -it <container> <docker_shell>` session.

Two implementation facts worth keeping:

- **Framing is the prompt, captured per session.** Writing the command and a
  trailing `exit` together does not work: bash's readline DISCARDS type-ahead,
  so the `exit` is swallowed, the session never closes and the exec burns its
  full timeout (observed live). The shell reprints its prompt when a command
  returns, and that prompt — read from the session banner, so no per-platform
  regex — marks the end. Matched only at the END of the transcript, so output
  mentioning it cannot cut the read short.
- **The transcript needs cleaning.** A container TTY echoes what we type and the
  shell frames it with prompts, a farewell (`logout`) and terminal escapes;
  `clean_pty_output` strips exactly those (unit-tested against a real captured
  transcript). The feared pager hazard did not materialize on VyOS.

## B — deferred, and why

A per-test `transport: exec | ssh` was on the table. Three of its four claimed
benefits are covered elsewhere:

- *"It proves SSH works"* — already expressible today with `mode: shell` from a
  peer node: `ssh -o BatchMode=yes vyos@<peer> 'echo reached'` distinguishes
  reachable/refused/filtered, and VyOS ships an OpenSSH client.
- *"Operator fidelity"* — that is the web terminal, which already has
  `protocol=ssh|shell`.
- *"Timed commands need SSH"* — C covers that over docker.
- *"CHR needs SSH"* — netlab already chooses `network_cli` for it; this only
  becomes a requirement if we remove netlab's per-device default, which we did
  not.

What survives is narrow but real: **B is the only way to test the out-of-lab
management path** — a source-based ACL or AAA policy that permits lab-internal
traffic and denies external would pass a peer-node probe and fail the real
operator path. No test wants that yet, and B is the most expensive of the three
(it moves transport ownership from netlab to the runner, and needs mgmt-IP
resolution — `ansible_host` on a docker node is the container name — plus a
session cache, host-key lifecycle and a new could-not-run failure class).

**Revisit trigger:** the first assertion someone wants about the out-of-lab
management path. Until then netlab keeps picking the transport per device, and
there is no `transport` field to name or default.

## Consequences elsewhere

Admitting a platform gains one more coordinated change: its **CLI entry** in
`cli_adapters.py` (or a deliberate absence, for a shell-only device), alongside
the catalog entry, kmods, Ansible collection, connection override and TextFSM
platform. A platform admitted without it simply cannot use `mode: cli` — a
loud 422, not a silent mis-send.

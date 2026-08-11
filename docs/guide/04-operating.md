# 4. Operating a lab

What you can do to a running lab: power it, watch it, reach into it, and break
it on purpose.

## Live state is not the definition

Everything on this page acts on containers, not on the stored text. Power, logs,
terminals, the interface inventory, the link table and impairment all read and
change what runs. None of them touch the definition.

That separation is what lets a lab **drift**. Edit the definition of a deployed
lab, and the header adds a `drifted` badge. The Overview tab's Definition card
then offers a **Changes** view, which diffs the deployed text against the stored
text.

Drift is a hint. Nothing blocks on it, and a drifted lab keeps working — it is
just no longer the lab its definition describes. A redeploy resolves it.

Comment and whitespace edits do not count. Twinlab re-serializes a definition
when it stores it, so cosmetic changes normalize away and never flag.

## Jobs

Deploy, configure, destroy and test-suite runs are **jobs**, not requests that
block until they finish. Four consequences:

- **Submitting returns at once.** The work continues on the server, so closing
  the browser changes nothing.
- **One job per lab.** A second submission of any kind gets `job_in_flight`,
  whatever kind it is.
- **A job reports its own steps** as it goes, and Twinlab stores them. The
  deploy dialog, the jobs drawer and the lab's job history all show the same
  list, during and after.
- **A failed job means it ran and could not finish.** That is different from a
  rejected submission, which changed nothing. [Page 8](08-troubleshooting.md)
  covers the distinction.

`/jobs` lists recent jobs across every lab you can read. Each lab also keeps its
own history, and a row opens a drawer with the request, the step log, and the
result or error.

Two job outcomes are deliberately *successes*. A config push that ran but failed
on some nodes reports `config_failed` with per-node detail. A config-time test
suite that failed reports `validation_failed`. In both cases the operation
worked. What it found is the bad news, and that belongs on the record rather
than in an error.

## Power

**Per node**, from the Nodes tab or from a node you select on the canvas: start,
stop, restart, pause, unpause.

**Whole lab**, from the header's `⋯` menu rather than a card of its own. Twinlab
offers each verb only where it can act, and names its reason when it cannot:

- A lab with nodes in both states offers **Start** and **Stop** together, since
  it has containers of each kind.
- **Pause** and **Unpause** appear according to what runs. With nothing running,
  Pause is disabled and says "no running nodes".
- A lab with no containers at all disables everything and says so.

Whole-lab pause fans out over the nodes one at a time. containerlab has no
lab-level pause, so this is not atomic — a failure part way leaves some nodes
paused.

**Save configuration** is in the same menu. It writes each node's running
configuration to its startup configuration, inside the container. It does not
change the definition, and it does not survive a destroy.

## Logs and terminals

**Logs** give you a node's container output, with a tail count. This is the
container's stdout, not the NOS log, so what you see depends on the platform.

**The web terminal** opens a session in a node from the browser. It needs
`lab:terminal`.

Use the web terminal for a quick look. Use real SSH — [page 7](07-access.md) —
when you want your own tools, a file transfer, or Ansible. Both reach the same
node.

## Interfaces and links

The Nodes tab carries two tables, and the difference is worth knowing.

**Links** is the logical list from netlab's expanded topology. A LAN segment is
**one** link with several endpoints, not one link per member. Each link carries
the subnet netlab assigned, live state, and any impairment.

**Interfaces** is a per-node inventory, one node at a time, behind a node
selector.

### Operational state

Twinlab derives each link's `oper_state` from its endpoints. The vocabulary is
a closed set of four:

| State | Meaning |
| --- | --- |
| `up` | every endpoint is up |
| `down` | Twinlab could read every endpoint, and none is up |
| `degraded` | endpoints disagree |
| `unknown` | Twinlab could not read at least one endpoint's state |

`degraded` means exactly "the two ends disagree". It is not a health score, and
an impaired link is not degraded — impairment is behaviour you asked for.

When Twinlab cannot reach live state it says so instead of guessing. The table
marks itself not live and keeps showing the topology, which is still true.

## Impairment

Netem shapes a link so you can test what happens when the network misbehaves.
Twinlab exposes five dimensions:

| Dimension | Unit | Note |
| --- | --- | --- |
| `delay` | µs, ms or s | |
| `jitter` | µs, ms or s | only meaningful with a delay, and refused without one |
| `loss` | percent | |
| `corruption` | percent | |
| `rate` | kbit/s | |

### Setting impairment replaces it

This is the rule that catches everyone once. **What you send is the complete
desired state of that interface.** Twinlab clears anything you leave out, and an
empty request clears everything.

So if a link already has 50 ms of delay and you set 1% loss without restating
the delay, the delay goes away. It is not additive, and there is no "add"
operation. State the whole condition every time.

### Two places, and they are not the same

- **The Links table** shapes a link in **both directions**. It writes the same
  settings to every endpoint. Advanced splits the endpoints so you can differ
  them, and endpoints that already differ read "mixed".
- **The Interfaces table** shapes **one endpoint**. Netem shapes traffic leaving
  an interface, so one interface is one direction.

That asymmetry is real, not a UI accident. A one-way delay is a legitimate test,
and a link-level form cannot express it.

The topology canvas offers the same form: an impaired link draws animated, and
clicking the edge opens the impairment editor.

### Staging a whole condition

The API takes many impairments and power changes in one request, so you can
stage a degraded network without a round trip per change. It runs the items in
order and continues past failures, and reports each item's outcome. It is not a
transaction — nothing rolls back.

The UI does not expose the batch form. Use the client or the API for it. Runtime
control stays available while a job holds the lab's mutex, so you can impair a
lab mid-test.

## Activity

The dashboard's activity feed fills from a live event stream as containers
change state and jobs start and end.

It is **session-scoped**. There is no server-side history, so a reload starts it
empty. That is expected, not a fault. The jobs list is the durable record.

A reconnect after a dropped stream misses whatever happened while it was down.
Twinlab falls back to a slow poll, so a running job still updates.

## Redeploying

Deploying a lab that is already deployed replaces it in place. You do this after
editing the definition, which is what clears a `drifted` badge.

What survives a redeploy: the record, its definition, its test suites, its
custom-config templates, its topology layout, and its management subnet. Node
state does not — the containers are rebuilt.

**Redeploying changes each node's SSH host key**, because the nodes are new
containers. If you already reached a node over SSH from your own machine, your
`known_hosts` now disagrees and SSH refuses to connect. Remove the stale entries
for that lab's management addresses.

## Destroy, and the two kinds of removal

Both are in the header's `⋯` menu, below a separator, because they are the
destructive pair.

- **Destroy** removes the containers and keeps everything else. The lab becomes
  `destroyed`, and deploy rebuilds it from the same definition into the same
  management subnet. Destroy needs containers to remove.
- **Delete** removes the record as well, and releases the subnet. It does not
  need a running lab.

A destroyed lab is cheap to keep. It holds a subnet allocation, and nothing
else.

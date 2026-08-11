# 2. Your first lab

Two routers on one link, built and deployed in the UI. The topology does not
matter. The shape of the workflow does.

This page assumes a stack that starts and a VyOS image on the host. See
[Install](01-install.md).

## Three steps, and why they are separate

Twinlab splits the lifecycle into **create**, **author** and **deploy**:

1. **Create** makes an empty lab record. It has a name and a reserved management
   subnet, and no definition at all.
2. **Author** writes the definition onto that record.
3. **Deploy** reads the stored definition and builds the lab from it.

The split matters because of what deploy does *not* take. Deploy accepts no
definition. It reads the one on the record, every time, so a redeploy cannot
drift from what you authored. The definition is the single source of truth, and
the record outlives any one deployment.

## 1. Create the lab

Go to **Labs** and press **New lab**. Name it `demo` and press **Create**.

The name is the lab's durable identity. It keys every URL, Twinlab pins it into
the definition as netlab's topology `name:`, and it prefixes every container the
lab creates. That is why the rule is narrow:

> Start with a letter, then letters, digits, dash or underscore. At most 16
> characters.

The dialog enforces this before it calls the server. A name outside the rule
would produce a lab whose definition can never save.

Creating also reserves the lab's management `/24` from `MGMT_SUBNET_POOL`. Every
node gets an address there, and that is how you reach them later.

You land on the lab's **Overview** tab. The lab wears a `created` badge, the
Definition card is empty, and a Getting started card lists what to do next.

**Starting from a template instead.** The create dialog has a "Start from"
selector that fills the new lab with a built-in topology or one published from
your own fleet. It is the faster path once you know what you want. [Page
6](06-config-import.md) covers the library. This page builds from empty, because
the point is the workflow.

## 2. Author the definition

Open the **Build** tab.

Add two nodes and link them:

1. Press the chevron beside **Add** and pick **VyOS**. Do it twice. The nodes
   arrive named `vyos1` and `vyos2`.
2. Drag from the grip on one node to the other. That is the link.
3. Press **Save**.

A toast confirms it: `Definition saved. Deploy demo to apply it.`

Saving sends the YAML to the server, which validates it by running
`netlab create` without deploying anything. A definition netlab refuses comes
back with netlab's own error text, above the canvas.

Look at the Overview tab now and the Definition card holds real YAML, including
two keys you never typed: the topology `name:` and the management addressing.
Twinlab pins both onto every definition it stores.

Every control on the Build tab, and the definition key each one writes, is
[page 3](03-build-tab.md). You do not need it yet.

## 3. Deploy

Back on **Overview**, press **Deploy**. The dialog asks for confirmation and
offers one option:

> Push configuration after deploy (adds minutes)

Check it. Without it you get running containers with no routing configuration —
useful when you want to configure them yourself, and not what you want now.

Press **Deploy**. The lab starts deploying and the dialog reports progress.

### What happens next, and how to watch it

Deploy is a **job**. Submitting it returns at once and the work continues on the
server, so closing the dialog or the browser changes nothing. The dialog even
says so: its close button reads "Close (keeps running)".

The job reports its own steps as it goes — `topology_generated`,
`image_preflight`, `host_prep`, `clab_deploy_started`, `nodes_deployed`,
`nodes_ready`, `config_push_started`, `config_pushed`. Three places show them:

- the deploy dialog, while it is open,
- the jobs drawer, from the row on `/jobs` or the lab's own job list,
- the same list afterwards, because Twinlab stores the steps rather than
  streaming them.

The quiet stretches are real. Config push runs Ansible against every node and
takes minutes.

### The two badges, which is the part that confuses people

The lab wears **two** badges, and they answer different questions.

- The **lifecycle badge** beside the lab name flips to `deployed` as soon as the
  containers are up.
- The **Last operation** badge reaches `succeeded` only when the whole job
  finishes, config push and all.

So `deployed` does not mean finished. If you act on the lab while the job runs,
Twinlab refuses with `job_in_flight` — one operation per lab at a time. Wait for
the last-operation badge.

## 4. Check that it worked

**Nodes tab.** Both nodes show `running`, their container name
(`clab-demo-vyos1`), their image, and a management address in the pool the lab
reserved. The address has a copy button.

**Overview.** The Definition card's Visual view draws the topology, now with
live node state on it.

**A terminal.** On the Nodes tab, open a node's **Connect** drawer. It carries
the management address, launchers for a web console and container logs, and the
SSH recipe for reaching the node from your own machine. [Page 7](07-access.md)
covers SSH properly.

Open the web terminal and confirm the two routers see each other. On VyOS:

```
show interfaces
ping <the other node's address>
```

If you checked config push, the interfaces carry the addresses netlab assigned,
and the peer answers.

## 5. Tear it down

Both live in the lab header's `⋯` menu.

- **Destroy** removes the containers. The record, its definition, its layout and
  its management subnet all survive, and `deploy` rebuilds the same lab from the
  same definition.
- **Delete** removes the record too, and releases the subnet.

Destroy is the one you want between experiments. A destroyed lab is a lab you
can bring back.

## Where to go next

| You want to | Read |
| --- | --- |
| Know what every builder control does | [Page 3](03-build-tab.md) |
| Operate a running lab | [Page 4](04-operating.md) |
| Assert that the lab actually works | [Page 5](05-test-suites.md) |
| Build a lab from real device configurations | [Page 6](06-config-import.md) |
| Reach nodes over SSH, or share the lab | [Page 7](07-access.md) |
| Work out an error | [Page 8](08-troubleshooting.md) |

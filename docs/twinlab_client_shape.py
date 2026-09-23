"""Shape sketch of the Twinlab Python client (`TwinlabClient`) — FOR REVIEW.

A contract sketch, not an implementation. The sketch shows the **target
contract**: approved/agreed proposals are APPLIED to the shapes and methods,
with the current wire (commit bc89daa) noted inline where it differs — those
notes are the backend-rework checklist. Markers:

- ``QUIRK:``    — current behavior the client/tests must handle.
- ``PROPOSAL:`` — a change for the backend rework. ``(APPROVED)`` = agreed and
  applied here; ``(DISCUSS)`` = agreed in principle, shape drafted for review.
- ``TODO:``     — reviewer notes, pending decision.

Deltas from today's wire, applied below (= the backend rework checklist):

1. Unified error envelope (`TwinlabApiError`).
2. Lifecycle split: ``POST /labs`` = create-only record; ``POST
   /labs/{name}/deploy`` (today's redeploy, renamed) is the only deploy verb,
   guarded by the deploying-status mutex (409); `LabStatus` gains "created".
3. Status vocabularies pinned as Literals; container state normalized.
4. New endpoints: users get/delete/password-reset/activate-toggle, self
   password change, groups get, API keys (create/list/revoke) + Bearer auth.
5. DELETE /users refuses removing the last admin (409).
6. ``GET /labs/{name}/interfaces`` keys nodes by SHORT node name (backend
   translates from the container name).
7. Netem: durations are structured ``{value, unit}`` pairs (not "50ms"
   strings); ``set`` has REPLACE semantics (omitted dimension = cleared, empty
   call = clear all), subsuming the dropped ``/netem/reset`` endpoint.
8. ``PUT /labs/{name}/owner`` returns its own ``LabOwner`` model, not a fake
   Grant.
9. A config push that ran but failed on >=1 node is a 2xx
   ``status="config_failed"`` with per-node results — no longer an HTTP 502.
10. Per-lab ``permissions`` (LabSummary/LabDetail) is MASKED to the seven
    lab-scoped permissions — global-only perms (lab:create, user:manage,
    group:manage) never appear there (they ride on ``/auth/me``).
11. ``DELETE /labs/{name}`` with remove=false on a not-running lab is a 409
    (wire today: 404) — 404 stays reserved for existence-hiding; and
    remove=true RELEASES the lab's mgmt-subnet reservation (a plain
    "destroyed" record keeps its subnet, so a redeploy reproduces the same
    environment).
12. Async job model (APPROVED 2026-07-29; shapes drafted for review): the
    four long operations — deploy, configure, destroy, suite run — return
    **202 + a running ``Job``** and do the work server-side; callers poll
    ``GET /labs/{name}/jobs/{id}`` (wire today: synchronous long calls that
    return the result body directly). Pre-accept checks stay synchronous
    (existence-hiding 404, 409 no_definition / lab_not_running, suite 404).
    ONE running job per lab, any kind — a concurrent submit is 409
    ``job_in_flight`` (subsumes delta 2's deploy mutex; configure/destroy/
    suite runs, unguarded today, gain it too). Finished jobs persist as
    recent history. Completion is discovered by POLLING only; job events on
    the SSE stream are deferred (recorded in ROADMAP).
13. External SSH access (APPROVED 2026-07-29; shapes drafted for review):
    users register SSH PUBLIC keys (``/auth/ssh-keys``, self-service like
    API keys), and a stack-owned OpenSSH jump host lets a key's owner tunnel
    — plain ``ssh -J``, Ansible-ready — to ALL TCP ports of nodes in labs
    where they hold ``lab:terminal``, authorization re-evaluated from live
    RBAC on every new connection. ``lab:terminal`` now means "interactive
    node access" (web terminal AND SSH jump — no catalog change). ``GET
    /ssh-access`` advertises the jump address. Besides bring-your-own-key,
    ``POST /auth/ssh-keys/generate`` creates an ed25519 pair server-side,
    registers the public half, and returns the private key ONCE (never
    stored — the api-key pattern). (wire today: no ssh-key surface, no jump
    service.)
14. Link table (APPROVED 2026-07-30): ``GET
    /labs/{name}/links`` serves the lab's LOGICAL link table, derived from
    the netlab-expanded topology (a LAN is one link with N endpoints, not
    clab.yml's per-member fan-out): per link the netlab ``linkindex``,
    type, prefix, and per-endpoint ``node``/``interface``/IPs — plus a
    DERIVED per-link oper state rolled up from the live interface
    inventory and each endpoint's ACTIVE netem impairment (one read serves
    the whole link view; per-node ``show_netem`` remains for the node
    view). The table is produced by the same dry ``netlab create`` that
    validates a PUT and persisted on the lab record, so reads never pay the
    subprocess cost; it works on any AUTHORED lab (undeployed = full table,
    states unknown). 409 ``no_definition`` on a bare created record. (wire
    today: no link surface — the frontend guesses links from the raw
    definition and the netem tests guess interface names.)
15. Cross-lab job listing (APPROVED 2026-07-30): ``GET /jobs`` serves recent
    jobs across every lab the caller may read, newest first — the view the
    per-lab ``GET /labs/{name}/jobs`` cannot give. Any authenticated user,
    filtered per lab like ``/events`` (a global ``lab:read`` sees all);
    ``?limit=`` (default 20, max 200). Same ``Job`` shape, which already
    carries ``lab_name``. Jobs of SOFT-DELETED labs are EXCLUDED, so a
    destroy-with-remove job leaves the fleet list when its lab does — its
    terminal state is read by id through the per-lab route, which stays
    readable on a removed lab (delta 12). (wire today: no cross-lab route —
    the frontend fans one query out per lab and merges client-side.)
16. Job events on the SSE stream (APPROVED 2026-07-30): ``GET /events`` gains
    job lifecycle events, so job completion no longer has to be discovered by
    polling (this LIFTS the deferral recorded in delta 12). Events become
    NAMED: ``event: lab`` for today's container-lifecycle payload,
    ``event: job`` for the new ``JobEvent`` — a poke carrying
    ``{lab, job_id, kind, status, timestamp}`` and NOT the job's
    result/error, which the caller reads with ``get_job``. One event when a
    job is submitted (status "running") and one when it reaches a terminal
    state. Filtered by the same readable-lab set as lab events. There is no
    replay (no Last-Event-ID), so a reconnect can miss events and consumers
    keep a slow fallback poll. (wire today: every event is unnamed — a
    default-``message`` container event; naming them is the breaking part of
    this delta.)
17. Test-suites v2 (APPROVED 2026-08-03): the validation pipeline becomes
    **render → execute → parse → assert**, all still declarative data — no
    user code. Commands and expected values may carry Jinja2 templates
    rendered per node against facts from the netlab-expanded topology
    (``{{ nodes.pe4.loopback.ipv4 | address }}``), replacing the
    hardcoded-IP suites that broke on every re-address; rendering is
    sandboxed with strict undefined. The fact namespace starts as netlab's
    RAW node data — PROVISIONAL, deliberately unpinned; a pinned subset is
    a decision to make before v1.0 — and is discoverable via the new ``GET
    /labs/{name}/facts`` endpoint (which also insulates consumers from the
    future pinning). A test's action becomes a per-device CASE (``run`` =
    one ``TestCase`` or a device-keyed dict; case-level keying chosen over
    netlab-style field-level — one atomic recipe per device, no
    key-consistency rules) so one suite serves VyOS and IOL; a node whose
    device has no case reports "skip" (the reserved status, now used). A
    case may declare ``parse`` ("json" | "textfsm") turning stdout into
    structured data asserted with ``compare`` — napalm-validate's grammar
    (nested partial match, strict mode, numeric operators, ranges) — while
    the raw matchers (contains/not_contains/matches) remain for unparsed
    output; json_path/equals are RETIRED (a dotted path is the degenerate
    compare spec; NO stored-suite migration — dev-phase, no real-world
    data; the repo examples are rewritten to v2). ``interactive: true``
    routes a case through a persistent CLI channel where the node's
    transport is SSH — IOS truncates timed commands (``ping … repeat``,
    ``traceroute``) on a one-shot exec channel — and is a deliberate no-op
    over docker exec, which already captures everything. (wire today: one
    command string per test, raw + json_path matchers only, no rendering,
    no parse stage, no interactive mode, no facts endpoint.)
18. Device/image catalog (APPROVED 2026-08-03): ``GET /catalog`` serves what THIS
    deployment can actually run — the server-curated supported device set
    (whatever CLAUDE.md's Current State names as the tested platforms; that
    list is POLICY and moves in both directions — Cisco IOL was admitted and
    then withdrawn 2026-08-05 on licensing). Per device: a display label, its
    ``role`` (router | host), the netlab config modules it supports (the
    FULL netlab matrix, mirrored with a drift-guard test — consumers
    intersect it with whatever module set they can author), netlab's
    default clab container image, and whether that image is PRESENT on the
    host Docker daemon right now (best-effort via the netlab-runner, the
    component that owns the Docker socket; ``live`` is the honesty flag —
    the link-table pattern). Replaces the frontend builder's hardcoded
    device list. Any authenticated user. The device SET is policy: the NOS
    sweep (ROADMAP item 17) widens it by testing, never by a catalog edit;
    a definition naming an uncataloged device stays accepted-but-unpromised
    (text authoring is the escape hatch). Image presence is ADVISORY —
    deploy does not pre-flight it (a separate parked decision). (wire
    today: no catalog surface — `frontend/src/lib/device-catalog.ts`
    hardcodes the list.)
19. Deployed-definition snapshot + shared topology layout (APPROVED
    2026-08-03): two small lab-record additions.
    (a) A successful deploy SNAPSHOTS the definition it deployed.
    ``LabDetail`` serves it (``deployed_definition``) and both the list row
    and the detail carry a derived ``definition_drifted`` flag — the stored
    definition no longer matches what is running. A HINT, never a gate:
    deploy and configure stay allowed on a drifted lab (configuring from a
    drifted definition is exactly when the hint matters — surface it, don't
    block it). The snapshot describes the RUNNING environment, so destroy
    clears it and a redeploy replaces it; a FAILED deploy leaves the
    previous snapshot in place (partial wreckage is not describable).
    Comparison is exact text equality of stored vs snapshot — and since PUT
    normalizes the stored text (YAML re-dump), cosmetic edits (comments,
    formatting) do not flag drift, only changes that survive normalization.
    (wire today: deploy keeps no record of what it deployed — the only
    drift signal is the canvas's definition-vs-live-containers view, which
    sees node add/remove but never an edited link or module.)
    (b) ``GET/PUT /labs/{name}/layout`` stores ONE manual topology
    arrangement per lab on the record, shared across users and browsers
    (wire today: per-browser localStorage — `topology/layout-store.ts`,
    which this retires). Positions are keyed by canvas element id, OPAQUE
    to the server (node names plus frontend pseudo-nodes like LAN hubs — a
    presentation artifact; validation is shape-only). PUT is a full
    REPLACE (house test-suites/netem semantics; ``{}`` clears). Read rides
    ``lab:read``, write rides ``lab:edit``: arranging the shared layout is
    AUTHORING — only the Build tab edits topology or arrangement, every
    other canvas is read/operate-only (maintainer's call 2026-08-03).
20. Group canvas styling (APPROVED 2026-08-04): the layout resource
    gains a ``groups`` map — per-group presentation styling (today one field:
    ``color``, pinned to "#rrggbb"), keyed by group name, shared across users
    like the positions and carried by the SAME ``GET/PUT /labs/{name}/layout``
    full-replace pair (lab:read / lab:edit unchanged). Lives on the layout,
    NOT the definition: netlab's attribute validation rejects unknown group
    keys (and would broadcast them as node data if it didn't), and the
    definition is the deployable source of truth — presentation does not
    belong in it. Additive and wire-compatible: pre-existing rows serve
    ``groups: {}``. Groups without an entry render with a deterministic
    client-side default (name-hashed palette); the map records explicit
    choices only. (wire today: layout is positions-only, delta 19.)
21. Template library (APPROVED 2026-08-04; revised at review — per-KIND
    collections instead of one flat catalog): definition input methods,
    part one — reusable starting points, all CLONE-AND-EDIT (an
    instantiated template is copied, never linked; parameterized templates
    are a recorded future consideration, as is builder support for
    netlab's native ``components``; config-file import is deferred until
    after this ships). TWO sibling collections under one prefix — nothing
    ever consumes "a template of either kind" (the create-lab flow reads
    network entries, the builder palette reads node entries), so they
    share NO namespace: ``/templates/network`` (complete netlab
    definitions — a new lab's starting point) and ``/templates/node``
    (single-node attribute fragments the builder's Add menu stamps into
    an open doc). TWO tiers each: ``builtin`` (shipped read-only, seeded
    from the repo ``examples/``) and ``user`` (authored at runtime,
    deployment-wide). Reads are any authenticated user (the library names
    no lab); user-tier authoring rides a NEW global-only permission
    ``template:manage``. User-tier NETWORK templates are not standalone
    records: a lab is PUBLISHED into the collection via a toggle (``PUT
    /labs/{name}/template``) and the entry is a LIVE VIEW of that lab's
    stored definition — the lab is the authoring surface (validation, the
    builder, even test deploys come free), unpublish = flip off,
    soft-deleting the lab withdraws the entry; the network collection
    therefore has NO delete route (builtins are fixed, the toggle is the
    user tier's whole lifecycle). Publishing EXPOSES the definition to
    every authenticated user — deliberate, and why the gate is
    template:manage. Node templates are snapshots (POST/PUT/DELETE), a
    YAML mapping that MUST name ``device`` (a node's device is intentful);
    validation is STRUCTURAL only — a fragment may lean on lab-level
    constructs (vrfs, groups) no standalone dry netlab run could see, so
    the receiving lab's PUT stays the real validator. Instantiation has NO
    verb: clients compose get_network_template → create_lab →
    update_definition, or stamp the fragment client-side. Names are
    unique PER COLLECTION — 409 ``name_taken`` within a kind only, a node
    template can never block publishing a lab. (wire today: no template
    surface — the create-lab flow starts blank and the builder's Add menu
    offers bare catalog devices only.)
22. Config import (APPROVED 2026-08-04 — design record + plan: docs/config-import.md):
    definition input methods, part two — a deployable lab from DUMPED
    RUNNING CONFIGS. Import is a pure DEFINITION FACTORY (no lab side
    effects; the client composes create_lab → update_definition →
    put_custom_config — delta 21's no-instantiate principle): ``POST
    /import/network`` turns one config file per node into a netlab
    definition plus per-node carried config; ``POST /import/node`` turns
    one config into a node-template-style fragment for the builder's Add
    menu. NOTHING IS DROPPED — every source line lands in exactly ONE of
    three buckets (the builder's typed-vs-extras philosophy applied to
    import): MODELED (consumed into a deliberately THIN skeleton — nodes,
    subnet-inferred links, PINNED addressing, NO protocol modules; netlab
    regenerates modeled config natively, so it must never also ride the
    carry), CARRIED (verbatim per-node custom-config templates that
    ``netlab initial`` applies — OSPF/BGP/MPLS/ACLs/everything; untouched
    except INTERFACE RENAMING, source names rewritten to the
    netlab-assigned lab ifnames via the dry create's expanded topology,
    with the map returned), or QUARANTINED (kept but unattached by
    default: config referencing the PRODUCTION environment that would
    break the lab — mgmt / auth / telemetry / hardware classes). modeled
    ∪ carried ∪ quarantined = source is a factory invariant. Fidelity is
    PROVEN, not trusted: ``POST /labs/{name}/config-diff`` collects the
    running configs over the exec transport and classifies every source
    line against them — stateless (sources ride the request; a lab never
    remembers its import origin), the interface map recomputed by joining
    the sources' pinned addresses against the lab's facts. Scope is the set of
    devices with a PARSER (vyos + iol — linux has no config-dump concept);
    ``CatalogDevice.config_import`` is its queryable form, so a device with a
    parser but no catalog entry is simply unadvertised — which is the state
    iol landed in when it was withdrawn 2026-08-05 (the parser stayed on
    purpose: it parses a config format, not a supported platform). A
    raw-containerlab
    SECOND DEPLOYMENT MODEL was considered and REJECTED — interface
    renaming and link inference are needed either way, and a second lab
    species forks the whole downstream stack (docs/config-import.md).
    (wire today: no import surface.)
23. Explicit wiring (APPROVED 2026-08-04 — revises delta 22's import surface; decided at
    the aux-input analysis, docs/config-import.md): **`wiring` becomes a
    REQUIRED input of ``POST /import/network`` and inferred adjacency is
    REMOVED** — topology is intent, and the import stops guessing it. Each
    wiring entry is a list of ``"node:interface"`` endpoints (SOURCE
    hostnames + SOURCE interface names, split on the FIRST colon so
    channelized names keep theirs); endpoint count decides, mirroring
    netlab's own model: 2 = p2p, 3+ = LAN; ``[]`` is a legal linkless
    network. The subnet join is DEMOTED to a suggestion generator —
    ``POST /import/wiring-suggestion`` proposes a wiring list from the
    sources' addressing, the wizard prefills its editor with it, and import
    consumes ONLY the explicit list (a suggestion is never acted on).
    Per-interface realization is NOT inference and stays: an addressed
    interface in no entry still becomes a stub link (the twin's boundary —
    nothing-dropped), an unwired unnumbered interface stays a warning, and
    loopback pinning + mgmt quarantine are untouched. CONTRADICTIONS ARE
    FACTORY ERRORS now (asserted wiring makes them broken intent, not
    findings): 422 ``wiring_invalid`` (unknown node/interface, an interface
    in two entries, an entry with fewer than two endpoints, a wired
    mgmt-quarantined interface, malformed spelling) and 422
    ``wiring_conflict`` (a wire whose endpoint addresses sit in different
    subnets — catches mask typos harder than the old overlap warning);
    extras name the entry. A wire whose endpoints are ALL unnumbered emits
    a ``prefix: false`` L2 link (real veth, unaddressed — the ISIS-core /
    trunk / LAG-member case addressing could never see; LAG needs no
    special handling: wire the members, the bundle + its address ride the
    carry). MIXED wires (some endpoints addressed, some not) are legal:
    each unaddressed endpoint emits ``ipv4: false``, which suppresses
    netlab's assignment — left bare it INVENTS an address (live-proven),
    the one thing the importer must never do silently. NO wiring_report: accepted entries are visible in the
    definition itself. ``DiffSource`` gains an optional ``interface_map``
    override — L2 interfaces carry no address on either side, so the
    address-join recompute cannot map them; the client feeds back the map
    the import returned (config-diff stays stateless). CDP/LLDP neighbor
    dumps are PARKED as a later input form (they would normalize into the
    same wiring entries; ntc-templates already parses the IOS output).
    (wire today: delta 22 — optional-nothing, adjacency inferred.)
24. Batch runtime actions (APPROVED 2026-08-04 — the v1.0 remnant of the
    SHELVED scenario item, maintainer's call same day; scenario groundwork in
    ROADMAP 16.5): ``POST /labs/{name}/actions`` applies MANY netem
    impairments and node power events in ONE request, so a caller (the
    frontend, or an external orchestrator) can stage a whole degraded
    condition — impair N links, stop a node — without round-trip
    choreography. The body is an ORDERED list of items in TWO kinds, each
    mirroring its single-verb route EXACTLY (same fields, same semantics,
    same failure modes — a batch item teaches a caller nothing new):
    ``netem`` = set_netem's REPLACE on node+interface (the item states the
    interface's COMPLETE desired impairment; no dimensions = clear it) and
    ``power`` = node_power's verb on one node. Items execute SEQUENTIALLY
    IN REQUEST ORDER (ordering is the caller's to compose — impair before
    stop; clab-api serializes netem per lab anyway) and execution
    CONTINUES past a failed item: a 2xx means the batch RAN, and the
    response is an INDEX-ALIGNED per-item report (ok + clab-api's verbatim
    message, or the error slug + message the standalone verb would have
    raised) — the config-push philosophy: HTTP errors mean could-not-run
    (a malformed item, unknown kind, jitter without delay, an over-bound
    list → 422 up front, NOTHING executed; per-item errors are LIVE
    failures only). EXPLICITLY NOT a transaction: no rollback of earlier
    items, no isolation (a concurrent caller's single verb may interleave
    between items) — the orchestrator that needs more is exactly what got
    shelved. Bounded: ≤64 items. Sync, deliberately NOT a job: the member
    verbs are sync, and a job would trip the per-lab job mutex — runtime
    control must stay available while a long op runs, exactly as the
    single verbs are today. Permission ``lab:configure`` — what BOTH
    member verbs already ride; 404 existence-hiding unchanged. Route
    note (CORRECTED at implementation): ``actions`` is just another
    STATIC segment beside the other static lab POSTs (deploy, configure,
    save, start/stop/restart) — the capture hazard the sketch warned of
    does not exist at lab level, where the power routes use explicit
    segments rather than an ``{action}`` path param; only the NODE routes
    have that param (hence the netem-before-{action} ordering there).
    Node-level only — no whole-lab
    power items (the caller enumerates; the lab verbs' fan-out semantics
    stay theirs). TYPE-UNIFIED with the single verbs, not route-merged
    (review resolution 2026-08-04): a batch ``netem`` item IS the single
    netem route's body plus its address (``node``) plus the ``kind`` tag,
    and a ``power`` item IS the single route's path pair materialized as
    fields — ONE vocabulary, no second spelling of an impairment
    anywhere, and ONE executor in the implementation (a standalone verb
    runs a batch of one internally). The client unifies harder:
    ``set_netem`` now TAKES a NetemAction — the same object applies
    standalone or batched (pre-PyPI, so the signature change is free;
    the single route's wire is UNCHANGED — the client puts ``node`` in
    the path and the rest in the body). ``node_power`` keeps its two
    scalars: they ARE the shared vocabulary already, and a wrapper for
    the single call is ceremony (``PowerAction`` exists to put the pair
    in a list). The single ROUTES stay, deliberately: their failure
    semantics differ by design — a standalone verb fails via the HTTP
    error envelope (fail-loudly), a batch item's failure is DATA in the
    report — and a route merge would either kill fail-loudly for simple
    callers or leave ``ok`` a dead always-true field. (wire today: no
    batch — one round trip per interface/node.)
25. Definition-time `tc:` REJECTED for v1.0 (DECIDED 2026-08-05, SHIPPED
    same day). Up-parity gap 1: netlab's link/interface `tc:` impairment
    is applied by `netlab up` — the step Twinlab replaces — so a
    definition carrying it deployed with no impairment and no signal. It
    now joins the `unsupported_directive` list at PUT: 422, one entry per
    placement, the key naming the link entry it came from
    (`links[0].h1.tc`). `defaults.tc.enable` is NOT rejected (netlab's
    switch for a step we never run), nor is a `tc:` that carries none of
    netlab's seven knobs (a node may be NAMED tc, which makes `tc:` on a
    link entry an endpoint).

    This REVERSES the honor-it sketch of 2026-08-04 (never implemented;
    the parked design is recorded in docs/nos-sweep/netlab-up-gaps.md
    and ROADMAP 17.2 for the post-v1.0 revisit). What the re-analysis
    found, kept here because it is what a revisit starts from: the
    mapping is exact except `tc.rate`, which is bit/s to our netem's
    kbit/s (probed: `tc … netem rate 1000` reads back `rate 1Kbit`), and
    `tc.duplicate`/`tc.reorder` have no clab-api netem expression at all;
    honoring `tc:` therefore forces the baseline-vs-runtime question —
    reapply-on-restart, and whether "clear" reverts to the baseline,
    which would change delta 7's shipped REPLACE semantics. Rejecting
    settles that question for post-v1.0 scenarios too (ROADMAP 16.5):
    there is NO baseline tier — the live qdisc is the only impairment
    state, and a scenario restores by re-submitting a delta-24 batch.
    (wire before: `tc:` validated and was silently dropped.)
26. The fact namespace pinned (APPROVED 2026-08-05, SHIPPED same day — the
    pre-v1.0 decision reserved by delta 17's resolution (a); analysis,
    evidence and live verification: docs/fact-namespace.md). Each node's facts become a PARTITION: a
    **promised core** stays in place with pinned shapes, and EVERY other
    key — netlab-internal `_`-prefixed bookkeeping included — moves
    verbatim under **`_extras`**, for which NO promises are made. Nothing
    is ever dropped; the stability signal travels in the template path
    itself (`{{ node.ospf.router_id }}` is contract,
    `{{ node._extras.mtu }}` is visibly unstable ground). The partition
    is PER-OBJECT, not top-level-only: every dict the pin recognizes as
    an object (node, mgmt, loopback, interface entry, interface
    neighbor, per-interface ospf overlay, ospf, bgp, bgp neighbor, ldp,
    vrf entry, vrf loopback_address) carries its own `_extras` (omitted
    when empty), so unpinned members inside pinned subtrees are marked
    too — `ospf.areas` lands at `ospf._extras.areas`; lists are never
    index-mirrored. Invariants: every raw key lands in exactly one
    place (reassembly reproduces netlab's raw dict — tested); a
    netlab-supplied `_extras` key would itself be unpinned and land at
    `_extras._extras`, so ours always wins the position; jinja2's
    sandbox resolves `node._extras.x` fine (dict-key lookup, probed).
    The promised core is the compatibility promise: Twinlab adapts —
    shim or errata — if a netlab upgrade moves a source key, enforced
    by a drift-guard test over the examples' real netlab output. Member
    lists: the appendix below. Both example suites already resolve
    entirely inside the core, and internal consumers of the raw facts
    (config-import, device-keyed dispatch) read only core paths — the
    cache stays raw, partition applies at the serve boundaries (render
    context, PUT dry-render, GET facts), which stay IDENTICAL. LabFacts
    keeps its untyped `dict` shape: a fully typed facts model would
    freeze netlab's entire node schema — the opposite of insulation.
    (Shipped 2026-08-05; the previous wire — delta 17's raw
    unpartitioned dict — is gone.)

27. Custom-config templates remodeled as STRUCTURED RECORDS (APPROVED
    2026-08-07 — design record docs/custom-config-templates.md; a breaking
    rework of this surface, done while the contract has no external
    consumers). The raw ``{relpath: content}`` fileset — where the path did
    double duty as storage key AND the whole metadata model — is replaced
    by records: ``{name, description, tier, variants}``, each variant
    ``{source}`` scoped by exactly one of ``node`` / ``device`` (a catalog
    slug) / neither (universal) — mirroring netlab's own lookup precedence
    (node > device > universal), so the picker can finally answer "does
    this template apply HERE?" (`mpls_te` on a VyOS lab was offered and
    failed two steps later in netlab's voice). The netlab-facing fileset is
    MATERIALIZED from the records at the config-push/create boundary
    (``name/<node>.j2`` | ``name/<slug>.j2`` | ``name.j2``); the runner
    contract and the PUT's dry ``netlab create`` are unchanged. GET returns
    ONE merged list (builtins first); PUT full-replaces the user tier only.
    409 ``builtin_template_shadowed`` becomes plain NAME equality; user
    ``device`` variants must name a catalog device (422). Config import
    emits records (``imported`` + ``imported_quarantine``, node variants) —
    carry paths materialize byte-identical to the old scheme, so existing
    definitions' direct-path ``config:`` references keep resolving.
    Deliberately NOT absorbed: the delta-21 template library (authoring
    seeds the client composes — different concept, no shared defect).

28. Test commands gain a LANGUAGE, and `interactive` stops lying (APPROVED
    2026-08-10; design record docs/validation-transport.md). `TestCase`
    gains ``mode: shell | cli``. "shell" is the default and means today's
    behavior — the words go verbatim to whatever the transport lands in,
    which for a docker-connection device is the CONTAINER'S SHELL, not the
    NOS CLI. "cli" declares the device's own CLI and the backend rewrites
    the command to reach it (per-device policy in
    ``services/cli_adapters.py``: VyOS's op-mode wrapper, ``vtysh -c``,
    ``birdc``, identity where the transport already lands in the CLI), with
    a 422 when the device has no CLI of its own. This closes a whole class
    of silent failure: ``ping X vrf Y count 5`` on VyOS reached Linux's
    ping — no ``vrf`` flag — and the suite saw an empty stdout instead of
    an explanation. ``TestResult.command`` now reports the ADAPTED command,
    since that is what actually ran. Same delta: ``interactive: true`` on a
    docker-transport node was a SILENT NO-OP and now opens a PTY-backed
    ``docker exec -it`` session — which is also why `mode` and `interactive`
    interact (VyOS op-mode comes from interactive shell init, so an
    interactive `cli` command needs no wrapper). Deliberately NOT included:
    a per-test TRANSPORT selector (exec vs ssh). It was considered and
    deferred — "prove SSH works" is already expressible from a peer node
    with `mode: shell`, the operator-terminal experience is the web
    terminal's job, and the one thing it uniquely buys (asserting the
    OUT-OF-LAB management path: source-based ACLs, AAA as seen from
    outside) has no test asking for it yet. netlab keeps choosing the
    transport per device, as it does today.
29. Jobs carry a STEP LOG (APPROVED 2026-08-10; design record
    docs/job-steps.md). A running job was visible but opaque: the phases
    that decide whether a deploy is healthy — the image pre-flight, host
    preparation, netlab's output, Ansible's per-node push, the config-time
    suites — all run inside the job task and never left the backend, so the
    only progress a UI could show was clab-api's container churn, live-only
    and gone on reload. ``GET /labs/{name}/jobs/{id}`` now returns a
    ``JobDetail`` = ``Job`` + ``steps: list[JobStep]``, each
    ``{at, code, level, message}``, appended by the operation as it runs and
    kept with the row afterwards. The two LISTINGS keep serving ``Job``
    (kind/status/timing is what they render; the narrative would be waste in
    a fleet-wide poll) — the same summary/detail split as
    LabSummary/LabDetail. Steps are a narrative, NOT the record: nothing is
    derivable only from a step, so an unknown ``code`` is displayable rather
    than an error and the vocabulary may grow. Deliberately NOT included: a
    step event on the SSE stream (delta 16 pinned ``job`` events as a poke
    over a lossy broker, and steps are durable data — a poller sees them
    within one interval), and server-side capture of clab-api container
    events per job (considered, parked: it is an SSE fan-out refactor, and
    the step log is what answers the complaint).
(Deltas 30–32 are recorded inline at their shapes and methods, marked
PROPOSED (delta 30/31/32).)
33. Sign-in through OIDC providers, and users gain an email and a display
    name (APPROVED and implemented 2026-09-23; design record docs/oidc.md,
    whose review log records how its questions were settled). Admins (``user:manage``) configure any
    number of OIDC providers (``/oidc-providers``). Each provider has two
    switches, both off by default: CREATE an account for an unknown person,
    and TIE a sign-in to the existing account holding the same email. Both
    require ``email_verified`` to be exactly true. A third switch,
    ``trust_email``, also off by default, lets an ABSENT claim count as
    verified, for issuers such as Entra ID that never send it; an explicit
    false is still refused. Client secrets are encrypted at rest (Fernet,
    ``OIDC_SECRET_KEY``). Each provider may carry an admin-uploaded icon,
    served inline as a ``data:`` URI, and Twinlab ships no brand logos. The durable identity is
    (provider, ``sub``); email is used once, to find the account to link.
    The backend runs the authorization-code + PKCE flow itself, on browser
    navigations (``/auth/oidc/{name}/login`` and ``.../callback``), and ends
    it by issuing the ORDINARY Twinlab session cookie. Provider tokens are
    discarded, so nothing downstream (API keys, SSH keys, /events, the
    terminal) learns OIDC exists. Sign out stays local: the provider's own
    session is left alone. There is NO group mapping from claims; a
    provider's optional default group is joined at account creation only.
    Password login stays. The callback URL is ``PUBLIC_ORIGIN`` (optional;
    unset = OIDC off) + ``FRONTEND_BASE_PATH``, which becomes a REQUIRED
    deployment setting shared by the frontend and backend (empty = the
    origin root). On the user side, ``email`` becomes REQUIRED and
    unique case-insensitively and ``display_name`` is new and required;
    ``POST /users`` takes an optional password, generates one when it is
    omitted and returns it ONCE (``UserCreated``, the api-key pattern). A
    provider-created user gets a random password nobody sees. Only an admin
    edits an email, their own included: self-service email change would let
    a user capture a colleague's first provider sign-in through tying.
    Existing users are backfilled (``<username>@users.invalid``, which no
    provider can verify), and ``BOOTSTRAP_ADMIN_EMAIL`` becomes required. The Python client
    gets the admin and profile methods but no OIDC login, because the flow
    needs a browser and a person; automation keeps using API keys. (wire
    today: no OIDC surface; ``users.email`` is an unused optional column
    and there is no display name.)

Conventions:

- Base path ``/api/v1``; OpenAPI at ``openapi.json`` (schema-check the real
  client against it in CI).
- Auth: opaque HttpOnly session cookie from ``login`` (the client carries a
  cookie jar), OR an API key passed at construction — the desired client shape;
  server-side API-key support is PROPOSED (not served yet, see the Auth
  section). Everything except login/health needs one of the two. PROPOSED
  (delta 33): a session may also be minted by signing in through an OIDC
  provider in a browser. It is the same cookie, so there is no third
  credential. The unauthenticated routes gain ``GET /auth/oidc/providers``
  and the two OIDC browser navigations.
- Lab-guarded routes: **404** when the caller can't read the lab (existence
  hidden), **403** when readable but lacking the specific permission.
- Names (lab/node/suite): ``^[A-Za-z0-9][A-Za-z0-9_.-]*$``, max 64.
- **Async client**: every method is a coroutine (httpx2.AsyncClient +
  `websockets`); the client is an async context manager.
- Ids are UUIDs — **UUIDv7** (decided 2026-07-28: the backend bumps to
  Python 3.14 and uses stdlib `uuid.uuid7`; wire today: v4). Applies to every
  id field below.
- Unordered unique collections (roles, permissions, scopes) are `set` in the
  client; the wire is a JSON array either way.

PROPOSAL (APPROVED — shape at `TwinlabApiError`): unify the error envelope.
Today `detail` has four shapes (labs/grants {stage, message, ...},
users/groups {reason, detail}, login a bare string, FastAPI's 422 list).

PROPOSAL (APPROVED — shapes in the Auth/Users/Groups sections, marked
PROPOSED): missing endpoints — get/delete user, admin password reset,
activate toggle, self password change, get group, API keys.
"""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


# Not frozen (implementation finding): re-raising through a context manager
# assigns `exc.__traceback__` at Python level (contextlib), which a frozen
# dataclass's __setattr__ rejects — exceptions must stay mutable.
@dataclass(slots=True)
class TwinlabApiError(Exception):
    """Any non-2xx response.

    PROPOSED SHAPE (APPROVED): the rework serves ONE envelope for every error,
    via a single exception handler:

        {"code": "<machine slug>", "message": "<human>", "extras": {...}}

    - `code`: stable slug for programmatic matching — e.g. "lab_not_found",
      "netlab_invalid", "config_push_failed", "username_taken",
      "mgmt_subnet_exhausted", "upstream_error", "not_authenticated",
      "permission_denied", "validation_error".
    - `extras`: endpoint-specific payload (netlab `stderr`, per-node config
      results, FastAPI field errors under "errors", ...).

    Until the backend lands it, the client fills these fields best-effort from
    the four current shapes (`code` from `stage`/`reason` when present, else
    "unknown"; raw body kept in `extras["raw"]`).
    """

    status_code: int
    code: str
    message: str
    extras: dict[str, object]


# --------------------------------------------------------------------------- #
# Auth / identity shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class UserInfo:
    """`GET /auth/me` / login response. GLOBAL roles/permissions only —
    per-lab permissions ride on each lab payload."""

    username: str
    # PROPOSED (delta 33): both required on every user from now on.
    email: str
    display_name: str
    roles: set[str]
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class LinkedIdentity:
    """PROPOSED (delta 33): one provider identity linked to a user.

    The link, not the email, is what a later sign-in resolves through:
    (provider, `subject`) is OIDC's stable, per-issuer-unique identity.
    At most one per (user, provider)."""

    id: UUID
    provider: str  # OidcProvider.name
    subject: str  # the provider's `sub` claim, opaque
    email_at_link: str  # the claim's email when the link was made (audit only)
    created_at: datetime
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class UserSummary:
    """One user (`/users`). `roles` = global roles."""

    id: UUID
    username: str
    # PROPOSED (delta 33): `email` is required and unique case-insensitively
    # (stored as entered); `display_name` is what the UI shows, while
    # `username` stays the password-login name and the RBAC principal name.
    email: str
    display_name: str
    is_active: bool
    roles: set[str]
    identities: list[LinkedIdentity]  # PROPOSED (delta 33)


@dataclass(frozen=True, slots=True)
class UserCreated:
    """PROPOSED (delta 33): `POST /users` response.

    `generated_password` is set only when the request OMITTED the password.
    It is the only time the server-generated password is returned, the same
    pattern as `ApiKeyCreated`. When the caller supplied a password it is None,
    because they already know it."""

    user: UserSummary
    generated_password: str | None


@dataclass(frozen=True, slots=True)
class LoginProvider:
    """PROPOSED (delta 33): one entry on the login page. `GET
    /auth/oidc/providers` is UNAUTHENTICATED (the page needs it before sign-in),
    so it carries only what a button needs: enabled providers, nothing else."""

    name: str  # the slug in /auth/oidc/{name}/login
    display_name: str  # the button reads "Sign in with {display_name}"
    # The admin-uploaded icon as a `data:` URI (svg/png/webp, <=32 KiB), or
    # None; a client then renders a monogram of display_name's first letter.
    # Inline, never a URL of its own: an SVG served from Twinlab's origin
    # could run script if opened directly, and a data: URI rendered through
    # <img> cannot.
    icon: str | None


@dataclass(frozen=True, slots=True)
class OidcProvider:
    """PROPOSED (delta 33): an admin-configured OIDC provider (`/oidc-providers`,
    `user:manage`). Design record: docs/oidc.md.

    `name` and `issuer` are IMMUTABLE. The name is part of the callback URL
    registered at the provider, and the links are keyed by the provider, so
    re-pointing a provider at another issuer would map one issuer's subjects
    onto another's people. The client secret is WRITE-ONLY: a read says only
    whether one is set."""

    name: str  # ^[a-z0-9][a-z0-9-]{0,31}$, unique
    display_name: str
    issuer: str  # unique across providers; must equal the discovery doc's
    client_id: str
    has_client_secret: bool  # False = a public client (PKCE alone)
    # False when a stored secret no longer decrypts (OIDC_SECRET_KEY changed or
    # lost). Sign-in through the provider then fails with oidc_unavailable;
    # the fix is re-entering the secret. Always True when there is no secret.
    client_secret_readable: bool
    scopes: list[str]  # "openid" always present
    allow_create_users: bool  # an unknown person with a verified email gets an account
    allow_email_tying: bool  # a verified email signs into the account holding it
    # An ABSENT email_verified counts as verified (an explicit false never
    # does). Safe only for an issuer whose tenant controls every address it
    # can put in `email`. Built for Entra ID, which never sends the claim.
    trust_email: bool
    default_group: Principal | None  # joined at CREATION only; None if deleted
    enabled: bool  # False hides it from the login page and refuses sign-in
    icon: str | None  # as on LoginProvider: a data: URI, set via its own route
    # The exact redirect URI to register at the provider:
    # {PUBLIC_ORIGIN}{FRONTEND_BASE_PATH}/api/v1/auth/oidc/{name}/callback.
    # None while PUBLIC_ORIGIN is unset, which also means OIDC sign-in is off
    # for the whole deployment.
    callback_url: str | None
    linked_users: int  # users linked through it: what a delete would unlink
    created_at: datetime
    updated_at: datetime


class Unchanged(Enum):
    """PROPOSED (delta 33): the "leave it as stored" value of a WRITE-ONLY
    field on a replace (today only `OidcProvider`'s client secret), which
    None cannot express because None already means "remove it". On the wire
    it is the field OMITTED."""

    UNCHANGED = "unchanged"


UNCHANGED = Unchanged.UNCHANGED


@dataclass(frozen=True, slots=True)
class GroupMember:
    id: UUID
    username: str


@dataclass(frozen=True, slots=True)
class GroupSummary:
    """Admin-defined user group; members inherit its global roles and lab grants."""

    id: UUID
    name: str
    description: str
    members: list[GroupMember]
    roles: set[str]  # global roles bound to the group


@dataclass(frozen=True, slots=True)
class Role:
    """One catalog role (`GET /roles`) — never hardcode the role list."""

    name: str
    scopes: set[Literal["global", "lab"]]
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class ApiKey:
    """PROPOSED (APPROVED, not served yet): one API key, as listings show
    it — never the secret."""

    id: UUID
    name: str  # caller-chosen label, e.g. "ci"
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApiKeyCreated:
    """PROPOSED (APPROVED): create response — the only time the secret is returned."""

    key: str  # the bearer secret, e.g. "tl_<random>"; shown once, stored hashed
    info: ApiKey


@dataclass(frozen=True, slots=True)
class SshKey:
    """One registered SSH public key (`/auth/ssh-keys`) — delta 13.

    Registering a key unlocks the stack's SSH jump host for its owner (see
    the SSH-keys client section for the connection semantics). Nothing here
    is secret — the user keeps the private key — so create returns this same
    shape (no `SshKeyCreated` analogue)."""

    id: UUID
    name: str  # caller-chosen label, unique per user, e.g. "laptop"
    algorithm: str  # e.g. "ssh-ed25519"
    fingerprint: str  # "SHA256:<43 base64 chars>" — what `ssh-keygen -lf` prints
    comment: str | None  # trailing comment of the registered line, display only
    created_at: datetime
    last_used_at: datetime | None  # last OFFERED at the jump, not last node login


@dataclass(frozen=True, slots=True)
class SshKeyGenerated:
    """`POST /auth/ssh-keys/generate` response — the only time the private
    key exists outside the caller's hands. The server registers the public
    half and DISCARDS the private half (no escrow); losing it means
    generating a new key."""

    private_key: str  # OpenSSH PEM text; write to a file with mode 0600
    info: SshKey


@dataclass(frozen=True, slots=True)
class SshAccess:
    """`GET /ssh-access` — the jump-host coordinates (delta 13).

    `enabled` False (deployment has no jump configured) leaves the rest None.
    Usage: ``ssh -o ProxyJump={user}@{host}:{port} <node-user>@<node-mgmt-ip>``
    — node mgmt IPs ride on `LabNodeState.mgmt_ip`; the node's own login is
    unchanged (the tunnel only grants reachability)."""

    enabled: bool
    host: str | None
    port: int | None
    user: str | None  # the jump account name, e.g. "jump"


@dataclass(frozen=True, slots=True)
class Principal:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class LabOwner:
    """`PUT /labs/{name}/owner` response (APPROVED — wire today reuses the
    grant shape with the LAB's UUID as `id` and the non-catalog role "owner")."""

    lab: str
    owner: Principal


@dataclass(frozen=True, slots=True)
class Principals:
    """`GET /principals`: id+name of all users/groups, for grantors lacking
    user:manage / group:manage."""

    users: list[Principal]
    groups: list[Principal]


@dataclass(frozen=True, slots=True)
class Grant:
    """One lab-scoped role binding. `principal_name` is None if the principal
    no longer exists.

    (answered: "why does it survive?") It isn't a designed lifecycle: deleting
    a GROUP does cascade its bindings, and users can't be deleted through the
    API at all today — so a dangling principal only occurs via out-of-band DB
    edits, and the None branch is defensive. Once `delete_user` (PROPOSED
    below) lands with binding cascade, `principal_name` can become required.
    """

    id: UUID
    principal_type: Literal["user", "group"]
    principal_id: UUID
    principal_name: str | None
    role: str


# --------------------------------------------------------------------------- #
# Device catalog shapes (delta 18, APPROVED 2026-08-03)
# --------------------------------------------------------------------------- #


# Pinned because WE derive it (netlab's own vocabulary for linux devices is
# `role: host`; everything configurable is a router here).
DEVICE_ROLES = ("router", "host")
DeviceRole = Literal["router", "host"]


@dataclass(frozen=True, slots=True)
class CatalogDevice:
    """One deployable device this deployment supports (delta 18, APPROVED).

    The set is server-curated POLICY — the tested platforms (CLAUDE.md's
    Current State) plus the linux host device, NOT everything netlab could
    name. A definition naming an uncataloged device is not rejected; it is
    simply unpromised (text authoring stays the escape hatch)."""

    device: str  # netlab device slug ("vyos", "frr", "linux") — the value a
    #              definition's `device:` takes. Deliberately NOT a Literal:
    #              the set widens as platforms get tested (the NOS sweep).
    label: str  # display name, e.g. "FRRouting"
    role: DeviceRole  # "router" = configurable NOS; "host" = plain container
    modules: list[str]  # netlab config modules the device can run — the FULL
    #                     netlab support matrix ("ospf", "bgp", …; passthrough,
    #                     netlab owns the vocabulary). Consumers intersect it
    #                     with whatever module set THEY can author (the visual
    #                     builder's representable set is a frontend concern).
    image: str  # netlab's default clab image for the device (an untagged name
    #             means ":latest"); a definition may override per node, which
    #             the catalog does not see.
    image_present: bool | None  # default image exists on the host Docker
    #                             daemon — best-effort; None = could not check
    #                             (see DeviceCatalog.live)
    # PROPOSED (delta 22, APPROVED): this device's dumped running configs can
    # be imported (POST /import/*). Import capability is NARROWER than
    # deployability — linux has no config-dump concept — and widens only with
    # a per-device parser (a NOS-sweep-adjacent decision, never implicit).
    config_import: bool
    # PROPOSED (delta 31): the two per-device capabilities a test CASE depends
    # on. Both are DERIVED server-side from the tables that actually decide —
    # cli_adapters.CLI_ENTRIES and validation.TEXTFSM_PLATFORMS — exactly as
    # config_import is derived from the importer's parser set, so neither can
    # drift from behaviour. They exist because a client authoring a case
    # otherwise has to keep its own copy of both tables, and would go stale the
    # first time a platform is admitted (admitting one already touches up to
    # six files; this makes it zero more).
    cli_mode: bool  # `mode: "cli"` is meaningful here — the device has a CLI
    #                 of its own to reach. False for shell-only devices (linux,
    #                 dnsmasq), where a `cli` case is a 422 at run time.
    textfsm: bool  # `parse: "textfsm"` resolves a platform for this device.
    #                False means a textfsm case errors — there is no template
    #                set to parse with, and Twinlab never silently falls back
    #                to raw output.


@dataclass(frozen=True, slots=True)
class DeviceCatalog:
    """`GET /catalog` — what this deployment can actually run (delta 18)."""

    devices: list[CatalogDevice]
    live: bool  # False = image presence could not be resolved (the runner —
    #             the Docker-socket holder — was unreachable); every
    #             image_present is then None. Same honesty flag as LabLinks.


# --------------------------------------------------------------------------- #
# Host resource shapes (delta 30, PROPOSED 2026-08-11)
# --------------------------------------------------------------------------- #

# WHY: a lab is a claim on a finite machine, and nothing in the API said what
# was left. "Is there room for this?" and "what is this lab costing?" were
# answerable only by ssh-ing to the host. The ROADMAP's Phase 6 item 9 parked
# a metrics stack with an explicit open question — full observability stack vs
# lightweight Docker-API stats — and this is the second answer, deliberately:
# an honest INSTANTANEOUS reading, no time series, no retention, no new
# service, no dependency beyond psutil (BSD-3). History, alerting and a
# Prometheus exposition stay parked; if they are ever picked up, this is the
# collector they would read from.
#
# THREE resources, split by where the data lives and what it costs:
#   GET /host         — the machine, sampled locally by the backend on a timer
#                       (instant, always available)
#   GET /host/docker  — the daemon's footprint, via the runner (~1s+, gone if
#                       the sidecar is down)
#   GET /labs/{name}/usage — per-node attribution (live-only, best-effort)
#
# The first two are ungated beyond authentication, like GET /catalog: they name
# no lab and reveal nothing about who owns what, and every user deciding
# whether to deploy needs them. Per-lab usage rides `lab:read`.


@dataclass(frozen=True, slots=True)
class HostCpu:
    cores: int
    utilization_percent: float  # host-wide, over the server's sample window
    load1: float
    load5: float
    load15: float


@dataclass(frozen=True, slots=True)
class HostMemory:
    total_bytes: int
    used_bytes: int
    # What a new lab could actually claim. NOT total minus used: that counts
    # reclaimable page cache as spent, and on a host that has deployed a few
    # labs the difference is tens of gigabytes.
    available_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class HostSwap:
    total_bytes: int
    used_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class HostDisk:
    path: str  # the path asked about; the figures describe its FILESYSTEM
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class HostResources:
    """`GET /host` — what the machine running the labs is spending (delta 30).

    Read from /proc via psutil. The backend runs in a container, but
    /proc/stat, /proc/meminfo and /proc/loadavg are NOT namespaced by Docker,
    so a container reads the HOST's values there — no privilege, no mount, no
    sidecar. Disk is the exception: statvfs needs the filesystem in the
    backend's own mount namespace, so `disks` covers only what it has (today
    the host-shared LAB_FILES_DIR, bind-mounted same-path)."""

    # The reading's real age. The server samples on a timer and serves the
    # last snapshot, so a timestamp older than a few seconds means sampling is
    # FAILING — the snapshot is deliberately not silently refreshed on read.
    sampled_at: datetime
    cpu: HostCpu
    memory: HostMemory
    swap: HostSwap
    disks: list[HostDisk]


@dataclass(frozen=True, slots=True)
class DockerDiskUsage:
    """One row of `docker system df`, in raw bytes."""

    kind: str  # "images" | "containers" | "volumes" | "build_cache".
    #            Deliberately NOT a Literal: the daemon owns this vocabulary
    #            and may grow a kind, which must not break a client.
    total: int
    active: int  # in use by something — an image with containers, a volume
    #              with references, a build-cache record in use
    size_bytes: int  # for images this is the DEDUPLICATED layer total, not
    #                  the sum of per-image sizes (which double-counts shared
    #                  layers) — the same number the docker CLI prints
    reclaimable_bytes: int  # what a prune could return; an unused image counts
    #                         only its UNSHARED layers, so this is smaller than
    #                         size for anything shared


@dataclass(frozen=True, slots=True)
class DockerUsage:
    """`GET /host/docker` — the Docker daemon's counts and disk footprint
    (delta 30).

    Read through the netlab-runner, the only component holding the Docker
    socket. The runner reads the Engine API rather than the `docker` CLI on
    purpose: the CLI emits only human-formatted sizes ("41.2MiB"), and a byte
    count parsed back out of those would be invented precision.

    Unreachable runner = 503 `docker_usage_unavailable`, NOT zeros. This is
    the one place the "degrade, never 5xx" rule does not apply, because there
    is no second source to fall back to — unlike the link table, which still
    has the definition."""

    root_dir: str  # the daemon's data root. Its filesystem is NOT necessarily
    #                one of HostResources.disks — the backend can only measure
    #                what it mounts, and /var/lib/docker is not mounted.
    containers_running: int
    containers_paused: int
    containers_stopped: int
    containers_total: int
    images_total: int
    disk: list[DockerDiskUsage]


@dataclass(frozen=True, slots=True)
class NodeUsage:
    """One node's live cost (delta 30).

    Every measure is nullable and a node that is not running carries NONE of
    them. The daemon answers for a stopped container with an empty payload,
    and reporting 0% would claim an idle node where there is no running one —
    the same distinction `image_present: None` draws in the catalog. `state`
    says which case a reader is looking at."""

    node: str  # short netlab name
    container: str  # clab-<lab>-<node>
    state: str  # docker vocabulary, as elsewhere in the API
    cpu_percent: float | None  # a share of the WHOLE host (Docker's own
    #                            formula), so a node pinning two cores reads
    #                            200% — it is NOT normalized to one core
    memory_bytes: int | None  # page cache excluded, matching `docker stats`
    memory_limit_bytes: int | None  # the cgroup limit; the host's total where
    #                                 the node sets none
    net_rx_bytes: int | None  # summed over the node's interfaces
    net_tx_bytes: int | None
    pids: int | None


@dataclass(frozen=True, slots=True)
class LabUsage:
    """`GET /labs/{name}/usage` — what a lab's nodes cost right now
    (`lab:read`). Live-only, like the link table's live half."""

    lab: str
    sampled_at: datetime
    nodes: list[NodeUsage]
    live: bool  # False = the MEASURES could not be collected (undeployed lab,
    #             or clab-api / the runner unreachable). The node rows survive
    #             a runner outage — they come from clab — so this reads as
    #             unmeasured rather than idle. Never an error: an undeployed
    #             lab legitimately costs nothing.


# --------------------------------------------------------------------------- #
# Template library shapes (delta 21, APPROVED)
# --------------------------------------------------------------------------- #


TEMPLATE_TIERS = ("builtin", "user")
TemplateTier = Literal["builtin", "user"]


@dataclass(frozen=True, slots=True)
class NetworkTemplateSummary:
    """APPROVED (delta 21): one network-collection entry, content omitted
    (the definition is fetched on selection). Names are unique within the
    NETWORK collection only — the review replaced the flat cross-kind
    namespace with per-kind collections (nothing consumes "a template of
    either kind", so a shared namespace only manufactured collisions)."""

    name: str
    tier: TemplateTier
    description: str  # the library-card text. builtin: shipped; published
    #                   lab: set on the publish toggle
    source_lab: str | None  # user tier: the published lab this entry mirrors
    #                         (LIVE — the entry always serves the lab's
    #                         CURRENT stored definition). None on builtins.


@dataclass(frozen=True, slots=True)
class NetworkTemplate:
    """APPROVED (delta 21): `GET /templates/network/{name}` — the entry
    plus its content: a complete netlab definition. Any `name:`/mgmt
    pinning inside it is irrelevant — instantiation goes through the
    normal lifecycle, where PUT re-pins both."""

    name: str
    tier: TemplateTier
    description: str
    source_lab: str | None
    content: str


@dataclass(frozen=True, slots=True)
class NodeTemplate:
    """APPROVED (delta 21): one node-collection entry. No summary/detail
    split: `content` — a YAML node-ATTRIBUTE mapping carrying no node name
    (the name is chosen at stamp time) — is small and bounded, and the
    builder palette stamps straight from the list, so the list serves
    full entries."""

    name: str
    tier: TemplateTier
    description: str
    device: str  # the fragment's `device`, REQUIRED in the fragment (a
    #              node's device is intentful — house rule; 422 without it),
    #              surfaced so the palette renders the entry like a
    #              CatalogDevice (icon, image-missing warning)
    content: str


# --------------------------------------------------------------------------- #
# Config-import shapes (delta 22, APPROVED)
# --------------------------------------------------------------------------- #


# Pinned because WE derive it: the quarantine classes — source config that
# references the PRODUCTION environment rather than the network's own
# behavior, kept but not applied by default (a lab that locks out its own
# access is not "configured correctly"). Routing policy / ACLs / QoS / VRFs
# are NEVER quarantined — they carry and apply.
QUARANTINE_CLASSES = ("mgmt", "auth", "telemetry", "hardware")
QuarantineClass = Literal["mgmt", "auth", "telemetry", "hardware"]
# mgmt      — the source mgmt interface + its addressing (mgmt is Twinlab's:
#             the receiving lab's PUT pins its own subnet)
# auth      — AAA / TACACS / RADIUS / local-user auth (would lock the lab's
#             own config push + terminal access out)
# telemetry — prod-pointing NTP / SNMP / syslog / flow exporters
# hardware  — transceivers / stacking / licensing / boot lines a container
#             image cannot hold


@dataclass(frozen=True, slots=True)
class ImportSource:
    """One dumped running config. `device` must be import-capable
    (CatalogDevice.config_import — 422 ``unsupported_device``). VyOS accepts
    both the brace format (`show configuration`) and the flat set form
    (`show configuration commands`); IOS/IOL the plain running-config text.
    `name` overrides the node name; default is the config's hostname,
    sanitized to the name charset (the applied renames land in
    NetworkImport.name_map). Bounds, shape-only: ≤ 64 sources per call,
    ≤ 512 KiB each (422)."""

    device: str
    content: str
    name: str | None = None


# PROPOSED (delta 23, APPROVED): a wiring entry is a list of "node:interface"
# endpoints (SOURCE hostnames + SOURCE interface names; split on the FIRST
# colon — channelized names like "Serial0/1/0:0" keep theirs). Endpoint count
# decides, mirroring netlab's own link model: 2 = p2p, 3+ = LAN. A wire whose
# endpoints are ALL unnumbered becomes a `prefix: false` L2 link.
type WiringEntry = list[str]


@dataclass(frozen=True, slots=True)
class WiringSuggestion:
    """PROPOSED (delta 23, APPROVED): `POST /import/wiring-suggestion` — the
    subnet join, demoted to advice: a proposed wiring list derived from the
    sources' addressing (interfaces sharing a subnet), for the client to
    prefill a wiring editor with. NEVER acted on by the import itself —
    import_network consumes only the explicit list the caller sends. Pure
    parse, no netlab run; same lab:create as the factory."""

    wiring: list[WiringEntry]
    warnings: list[ImportWarning]  # e.g. unnumbered interfaces the join
    #                                cannot place — the human's cue to wire
    #                                them by hand


@dataclass(frozen=True, slots=True)
class QuarantineEntry:
    """One quarantined block of a node's source config, with why."""

    reason: QuarantineClass
    content: str  # verbatim source lines, hierarchy preserved


@dataclass(frozen=True, slots=True)
class ImportWarning:
    """A named, non-fatal fidelity hazard — never silent: an interface-like
    token in carried config that matched no map entry, an interface with no
    subnet peer (emitted as a stub link), an exotic stanza carried untouched
    but unrecognized, a sanitized hostname collision suffix, …"""

    node: str | None  # None = network-level
    message: str


@dataclass(frozen=True, slots=True)
class NetworkImport:
    """`POST /import/network` — the definition factory's output. PURE: no
    lab is touched; the client composes create_lab → put_custom_config →
    update_definition — custom config FIRST, because the definition PUT's
    dry `netlab create` validates its `config:` references against the
    lab's STORED templates. The definition carries no `name:` and no mgmt
    addressing — the receiving lab's PUT pins both.

    `custom_config` is ready for put_custom_config verbatim (delta 27:
    template RECORDS): the carries land as node variants of ONE template
    named `imported` (referenced by each carry node's `config:` list in the
    definition; sources are `{% raw %}`-wrapped so device config containing
    brace sequences survives netlab's Jinja render byte-exact) and non-empty
    quarantines as node variants of `imported_quarantine` — UNREFERENCED but
    visible and deliberately attachable per node, never silently lost;
    `quarantine` carries the classified breakdown."""

    definition: str
    custom_config: list[ConfigTemplateSpec]
    interface_map: dict[str, dict[str, str]]  # node → {source-if: lab-if}.
    #   The rename applied to the carry, from the dry create's expanded
    #   topology; the identity map for same-platform imports.
    name_map: dict[str, str]  # source hostname → sanitized node name
    quarantine: dict[str, list[QuarantineEntry]]  # node → entries
    warnings: list[ImportWarning]


@dataclass(frozen=True, slots=True)
class NodeImport:
    """`POST /import/node` — one config into a node-template-style fragment
    (a YAML node-attribute mapping naming `device`, stampable exactly like
    a NodeTemplate) plus its carry. QUIRK, flagged for review: a single
    config has no peers to subnet-join, so NO links are inferred and the
    carry keeps SOURCE interface names — renaming needs links that don't
    exist until the receiving doc wires them. `interfaces` lists what was
    found so the client can wire and warn; the NETWORK flow is the
    fidelity-complete path."""

    fragment: str
    config: str  # the carried config — un-rewritten, `{% raw %}`-wrapped
    interfaces: dict[str, str | None]  # source ifname → ipv4 CIDR (None =
    #                                    unnumbered/L2-only)
    quarantine: list[QuarantineEntry]
    warnings: list[ImportWarning]


@dataclass(frozen=True, slots=True)
class DiffSource:
    """One node's source config for config_diff. No `device`: a diff source
    names a LAB node, and the device comes from the lab's definition."""

    node: str
    content: str
    # PROPOSED (delta 23, APPROVED): explicit source-if -> lab-if entries that
    # OVERRIDE/extend the address-join recompute. L2-linked interfaces carry
    # no address on either side, so the join cannot map them — feed back the
    # map import_network returned (the diff stays stateless).
    interface_map: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class NodeConfigDiff:
    """One node's fidelity classification — every source line accounted for."""

    node: str
    matched: int  # source lines present in the running config (post-map)
    missing: list[str]  # source lines ABSENT from the running config — the
    #                     lines to look at
    extra: list[str]  # running-config lines with no source counterpart.
    #                    Expected noise, informational: the lab's own
    #                    mgmt/user baseline, defaults the NOS materializes.
    quarantined: int  # source lines excluded from comparison by class


@dataclass(frozen=True, slots=True)
class ConfigDiffReport:
    """`POST /labs/{name}/config-diff` — the import-fidelity proof.
    Informational, NEVER a gate (the drift-badge philosophy)."""

    nodes: list[NodeConfigDiff]


# --------------------------------------------------------------------------- #
# Health shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Liveness:
    status: Literal["ok"]


@dataclass(frozen=True, slots=True)
class Readiness:
    """`GET /health/ready` — same body on 200 and 503 (degraded is data)."""

    status: Literal["ready", "degraded"]
    # Value is "ok" or the failure message — `Literal["ok"] | str` collapses to
    # `str`, so the union isn't expressible as a type. PROPOSAL: per-check
    # {ok: bool, detail: str} so health is typed, not sentinel-string.
    checks: dict[str, str]


# --------------------------------------------------------------------------- #
# Lab shapes
# --------------------------------------------------------------------------- #

# PROPOSAL (APPROVED): pin these as Literals in the backend response models so
# OpenAPI carries them. "created" is new with the lifecycle split (a record
# that has never been deployed); the rest exist on the wire today.
LabStatus = Literal["created", "deploying", "deployed", "destroyed"]
DeployStatus = Literal["deployed", "configured", "config_failed", "validation_failed"]
ConfigureStatus = Literal["configured", "config_failed", "validation_failed"]
# APPROVED (replaces `config_time_ok: bool | None` on the wire). No "skipped"
# state on purpose: a skipped gate RETAINS the previous result (skipping a
# configure must not erase a known-red gate); "no config-time suites" = "not_run".
ConfigTimeStatus = Literal["not_run", "passed", "failed"]

# Configure failure layers (APPROVED — layer 2 changes from today's wire):
#   1. The push could not run at all (runner down, definition rejected)
#      -> HTTP 422/502, no per-node data. An HTTP error: nothing ran.
#   2. The push ran but >=1 node failed its Ansible play -> 2xx
#      status="config_failed" with `configuration` carrying the per-node
#      results (validation is None — the gate doesn't run on a failed push).
#      Wire today: HTTP 502 with the results buried in the error detail.
#   3. The push succeeded everywhere but the config-time gate failed -> 2xx
#      status="validation_failed".
# Rule of thumb: HTTP errors mean "could not run"; if it ran, the outcome —
# good or bad — is data.

# TODO(state) -> PROPOSAL: pin to docker-engine's vocabulary. Today the value
# is a clab-api passthrough, so the backend must normalize/validate it as part
# of the same rework; until then the client should tolerate unknown strings.
ContainerState = Literal[
    "created", "running", "paused", "restarting", "removing", "exited", "dead"
]


@dataclass(frozen=True, slots=True)
class LabNodeState:
    """Live per-node state from clab-api (best-effort)."""

    name: str  # short node name, e.g. "r1"
    container: str  # "clab-<lab>-<node>"
    image: str
    state: ContainerState  # requires the backend pin above
    mgmt_ip: str  # bare IP (CIDR stripped); "" when none


# (decided 2026-07-28: NO Summary/Detail split for v1.0 — Detail is already
# Summary + definition + node list; revisit with the frontend rework if a
# leaner shape proves wanted.)
@dataclass(frozen=True, slots=True)
class LabSummary:
    """One row of `GET /labs`. `status` is the durable record. `nodes` counts
    the containers PRESENT in live state (any state; 0 when down or clab-api
    unreachable) and `nodes_running` the subset actually running (APPROVED
    2026-07-29: both data points — after a host reboot a lab can be
    present-but-exited, e.g. 7/0). `permissions` = caller's effective set on
    THIS lab (global ∪ grants ∪ owner-implicit), MASKED to the lab-scoped
    permission set (APPROVED — global-only perms never appear here; see
    /auth/me for those)."""

    name: str
    status: LabStatus
    owner: Principal | None  # APPROVED — wire today: bare username string
    created_at: datetime
    updated_at: datetime
    nodes: int
    nodes_running: int
    config_time_status: (
        ConfigTimeStatus  # APPROVED — wire today: config_time_ok: bool | None
    )
    # PROPOSAL (delta 19, APPROVED): True when the stored definition differs
    # from the deployed snapshot (see LabDetail.deployed_definition). None
    # when status != "deployed" — nothing is running, so there is nothing to
    # drift from (a mid-redeploy "deploying" lab reads None too; the flag
    # settles when the job does).
    definition_drifted: bool | None
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class LabDetail:  # No Summary/Detail split for v1.0 (see LabSummary note).
    """`GET /labs/{name}`: stored record + live nodes. `definition` is the
    lab's source of truth — None until authored (a "created" lab)."""

    name: str
    status: LabStatus
    definition: str | None  # None only while status="created" (lifecycle split)
    # PROPOSAL (delta 19, APPROVED): the definition of the last SUCCESSFUL
    # deploy, exactly as deployed (post name/subnet pinning) — what the
    # RUNNING lab was built from. None until first deployed and after
    # destroy (the snapshot describes a running environment). Served on the
    # detail — not just the derived flag — so a client can render WHAT
    # changed since deploy, not merely that something did. Drift is exact
    # text comparison against `definition` — and because PUT NORMALIZES the
    # stored text (YAML parse + re-dump with name/subnet re-pinned), a
    # comment- or formatting-only edit normalizes away and does NOT flag
    # drift: drift means a change that survives normalization (implementation
    # finding 2026-08-03, live-verified).
    deployed_definition: str | None
    definition_drifted: bool | None  # delta 19 — see LabSummary
    # PROPOSAL (delta 21, APPROVED): True while this lab is published as a
    # network template (the set_lab_template toggle) — the lab page renders
    # the toggle's state from here. Detail-only: the labs LIST doesn't carry
    # it (the library view is GET /templates/network).
    template_published: bool
    # The definition's top-level `message:` — the author's "how to use this
    # lab" note `netlab up` would print after configuring. Surfaced instead
    # of silently dropped (up-parity gap 7 decision 2026-08-04,
    # docs/nos-sweep/). None when absent or unauthored.
    message: str | None
    owner: Principal | None  # APPROVED — wire today: bare username string
    created_at: datetime
    updated_at: datetime
    nodes: list[LabNodeState]
    config_time_status: ConfigTimeStatus  # APPROVED — wire today: config_time_ok
    permissions: set[str]


@dataclass(frozen=True, slots=True)
class NodeConfigResult:
    """Per-node outcome of a config push (from Ansible's PLAY RECAP)."""

    node: str
    status: Literal["configured", "failed"]  # PROPOSAL (APPROVED): pinned
    changed: int
    failed: int


@dataclass(frozen=True, slots=True)
class DeployResponse:
    """Terminal `result` of a deploy Job (delta 12 — wire today: the body of
    the synchronous `POST /labs/{name}/deploy`).

    - bare deploy:               status="deployed", configuration/validation None
    - +configure, gate ok:       status="configured" (validation None if skipped
      or no config-time suites)
    - +configure, push failed:   status="config_failed" — configuration carries
      the per-node results, validation None (gate not run)
    - +configure, gate failed:   status="validation_failed"
    All four are job SUCCESSES: a *failed* job means the operation could not
    run at all (`Job.error` carries the envelope).
    """

    status: DeployStatus
    lab_name: str
    nodes: list[str]  # short node names
    configuration: list[NodeConfigResult] | None
    validation: list["SuiteReport"] | None
    # Non-fatal image pre-flight findings (up-parity gap 3, 2026-08-04): a
    # missing-but-pullable image, or the check skipped (runner unreachable).
    # A missing image of a local-only device fails the JOB instead — error
    # `image_missing`, before anything touches the host.
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class ConfigureResponse:
    """Terminal `result` of a configure Job. Like DeployResponse, but
    `configuration` is always present (a push that couldn't run FAILS the
    job instead)."""

    status: ConfigureStatus
    lab_name: str
    configuration: list[NodeConfigResult]
    validation: list["SuiteReport"] | None


@dataclass(frozen=True, slots=True)
class DestroyResponse:
    """Terminal `result` of a destroy Job. "destroyed" = record kept,
    redeployable; "deleted" = remove=true, record soft-deleted."""

    status: Literal["destroyed", "deleted"]  # PROPOSAL (APPROVED): pinned
    detail: str  # containerlab teardown output, or "lab was not running"


@dataclass(frozen=True, slots=True)
class LabActionResponse:
    """Power/netem action result: clab-api's message, verbatim. A 2xx IS the
    outcome; the message is decoration."""

    message: str


@dataclass(frozen=True, slots=True)
class SaveConfigResponse:
    message: str
    output: str  # per-node save output from containerlab


@dataclass(frozen=True, slots=True)
class NodeLogsResponse:
    node: str  # short node name (echoed from the path)
    container: str
    logs: str


@dataclass(frozen=True, slots=True)
class NodeInterface:
    name: str
    alias: str
    ifindex: int
    mac: str
    mtu: int
    state: str
    kind: str  # clab-api's interface `type`


@dataclass(frozen=True, slots=True)
class NodeInterfaces:
    """One node's interface inventory.

    APPROVED: `node` is the SHORT node name (backend translates) — wire today:
    the container name ("clab-<lab>-<node>"), a clab-api passthrough."""

    node: str
    interfaces: list[NodeInterface]


@dataclass(frozen=True, slots=True)
class Duration:
    """A netem duration as a structured {value, unit} pair (APPROVED — wire
    today: strings like "50ms"). The author's unit choice is preserved."""

    value: float
    unit: Literal["us", "ms", "s"]


@dataclass(frozen=True, slots=True)
class NetemImpairment:
    """Current netem shaping on one interface. None / 0 = that dimension
    unshaped."""

    interface: str
    delay: Duration | None
    jitter: Duration | None
    loss: float  # percent
    rate: int  # kbit/s
    corruption: float  # percent


# Delta 14 (APPROVED 2026-07-30). Pinned as a Literal — unlike the interface `state`
# passthrough — because Twinlab DERIVES this value itself.
#
# Derivation is TWO stages (wording AMENDED 2026-08-05; no shape change):
#
# 1. Classify each endpoint into up / down / unknown. "up" is "up". **Down is a
#    CLOSED set** of positively-not-forwarding values from the Linux/RFC 2863
#    IF_OPER_* vocabulary — down, lowerlayerdown, notpresent — and everything
#    else, including a value we have never seen, classifies **"unknown", not
#    "down"**. An endpoint Twinlab could not resolve at all (lab not deployed,
#    inventory unavailable, interface absent from it) is unknown too.
#    One refinement needs data that is not on this wire: operstate is
#    MEANINGLESS on an interface with no carrier, so an endpoint whose live
#    interface kind is carrier-less (a `dummy`) and whose state is the string
#    "unknown" classifies **up**. That is not a special case for its own sake —
#    netlab realizes every stub link as a dummy interface, so without it every
#    stub in every lab reported "down" while forwarding perfectly.
# 2. Roll the classes up: any unknown endpoint -> "unknown" (we cannot speak for
#    the link); then all up -> "up"; all down -> "down"; a mix -> "degraded" (a
#    p2p with one side down reads degraded — the per-endpoint states
#    disambiguate; in practice a veth pair drops both sides).
#
# The original wording said "all known-not-up -> down", whose parenthetical
# listed only resolution failures as "unknown" — so it never contemplated a
# device REPORTING the literal string "unknown", and classified that as down.
# Twinlab is now conservative on purpose: claiming a link is down is a strong
# statement, and a wrong one teaches users to ignore the signal.
LinkOperState = Literal["up", "degraded", "down", "unknown"]


@dataclass(frozen=True, slots=True)
class LinkEndpoint:
    """One attachment point of a logical link (delta 14)."""

    node: str  # SHORT node name — matches /interfaces keys and the netem routes
    # The container-side interface name: what /interfaces reports and netem
    # accepts. QUIRK: resolved against the live inventory (name-or-alias
    # match) when the lab is deployed; undeployed it is the generated
    # clab-side name — identical for every non-renaming kind, but a renaming
    # kind (cisco IOL: "Ethernet0/1" vs "eth1") only settles once deployed.
    interface: str
    ifname: (
        str  # netlab/NOS-side name (e.g. "Ethernet0/1"); == interface when they agree
    )
    ifindex: int  # netlab interface index
    ipv4: str | None  # netlab-assigned CIDR; None on unnumbered/L2-only links
    ipv6: str | None
    # Live oper state passthrough for this interface ("up"/"down"/... — the
    # same unpinned vocabulary QUIRK as NodeInterface.state); None = unknown.
    # CONSUMER OBLIGATION (2026-08-05): because the vocabulary is unpinned, code
    # deriving anything from this must treat only a KNOWN not-forwarding value as
    # down and default everything else to unknown — never `state != "up"` means
    # down. Note the values are not self-describing: an interface with no
    # carrier reports the string "unknown" while being perfectly healthy, and
    # this wire carries no interface `kind` to tell you which those are. Prefer
    # the server's `oper_state`, which already accounts for it.
    state: str | None
    # Active netem impairment on this interface (reuses NetemImpairment — its
    # `interface` field is redundant here but keeps one shape). None = not
    # impaired OR unknown: only meaningful on a live read (`LabLinks.live`).
    # Deliberately NOT folded into oper_state — an impairment is requested
    # behavior, not degraded health; the UI renders them as distinct signals.
    impairment: NetemImpairment | None


@dataclass(frozen=True, slots=True)
class LabLink:
    """One LOGICAL link from the netlab-expanded topology (delta 14):
    a LAN is ONE link with N endpoints, stubs/loopbacks have one — not
    clab.yml's physical per-member fan-out."""

    index: int  # netlab linkindex — stable within a definition version
    name: str | None  # user-set link name only (netlab's _linkname is internal)
    # netlab's link type ("p2p" | "lan" | "stub" | "loopback" observed) — a
    # passthrough str, not pinned: netlab owns the vocabulary. QUIRK: not a
    # rendering signal — a linux-host p2p comes out "lan" (bridge-backed);
    # discriminate on len(endpoints) instead.
    type: str
    prefix_ipv4: str | None  # the link subnet; the only IP surface we have
    prefix_ipv6: str | None  # (/interfaces is L2-only)
    bandwidth: int | None  # netlab passthrough, as authored
    mtu: int | None
    oper_state: LinkOperState
    endpoints: list[LinkEndpoint]


@dataclass(frozen=True, slots=True)
class LabLinks:
    """The lab's link table (delta 14).

    `live` is the honesty flag: False means oper state could not be resolved
    (lab not deployed, or the interface inventory was unavailable) and every
    state is "unknown" — distinguishable from a deployed lab reporting real
    unknowns."""

    links: list[LabLink]
    live: bool


# --------------------------------------------------------------------------- #
# Topology layout shapes (delta 19, APPROVED)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LayoutPosition:
    """One canvas element's manual position (delta 19)."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class LayoutGroupStyle:
    """PROPOSAL (delta 20, APPROVED): one group's canvas styling.

    Lives on the LAYOUT resource, not the definition: netlab's attribute
    validation would reject a `color:` group key (and broadcast it as node
    data if it didn't), and the definition is the deployable source of truth
    — a stylesheet does not belong in it. Shared across users like the
    positions."""

    # "#rrggbb" (lowercase or upper accepted, served as sent) — pinned to hex
    # so the value is portable and can't smuggle arbitrary CSS; 422 otherwise.
    color: str


@dataclass(frozen=True, slots=True)
class LabLayout:
    """The lab's ONE shared manual topology arrangement (delta 19).

    Keys are canvas element ids, OPAQUE to the server: node names plus the
    frontend's pseudo-node ids (LAN hubs, e.g. "link:3"). A presentation
    artifact, deliberately NOT validated against the definition — stale keys
    (a renamed node, a reindexed link) are harmless because readers ignore
    unknown ids and auto-layout covers unplaced elements, and PUT's replace
    semantics prune naturally (the writer always writes the full current
    arrangement). Empty = no manual layout saved (auto-layout applies).
    Server validation is shape-only: bounded key count and length, finite
    floats — 422 beyond."""

    positions: dict[str, LayoutPosition]
    # PROPOSAL (delta 20, APPROVED): per-group canvas styling, keyed by GROUP
    # NAME (the definition's `groups:` keys — same opaque-key rule as
    # positions: a renamed/deleted group leaves a harmless stale entry that
    # the next full-replace PUT prunes). Groups without an entry get a
    # deterministic default color client-side (name-hashed palette), so this
    # map only carries explicit choices. Absent on pre-delta-20 rows — GET
    # serves {} (additive change, wire-compatible).
    groups: dict[str, LayoutGroupStyle]


@dataclass(frozen=True, slots=True)
class LabEvent:
    """One container-lifecycle payload from `GET /events`.

    PROPOSAL (delta 16, APPROVED): carried by the NAMED SSE event ``lab``
    (wire today: the unnamed default event)."""

    lab: str
    node: str | None
    action: str  # "create" | "start" | "stop" | "kill" | "die" | "destroy" | ...
    timestamp: str


# The other `GET /events` payload, `JobEvent`, is PROPOSED in the Job shapes
# section below (it is typed by JobKind/JobStatus, defined there).


# --------------------------------------------------------------------------- #
# Test-suite shapes (v2 — delta 17, APPROVED 2026-08-03)
# --------------------------------------------------------------------------- #

# PROPOSED (delta 28, APPROVED 2026-08-10): which interpreter a command's
# words are for. The transport lands somewhere — a container shell for
# docker-connection devices, the NOS CLI for SSH ones — and until now the
# contract never said which, so a CLI-shaped command silently hit the shell.
CommandMode = Literal["shell", "cli"]

ParseMode = Literal["json", "textfsm"]
# How a case turns stdout into data `compare` can assert on:
# - "json": stdout must parse as JSON. On VyOS this costs nothing — FRR's
#   `vtysh -c "show ... json"` emits it natively (verified live on OSPF
#   neighbor / LDP neighbor / BGP VPNv4 summary), so routing-state gates
#   need no template layer at all.
# - "textfsm": stdout is parsed into a list of records via TextFSM — the
#   template resolved from the node's DEVICE plus the rendered command,
#   out of ntc-templates' library (cisco_ios: 143 templates) overlaid by
#   Twinlab-packaged templates (e.g. our own `show mpls ldp neighbor` for
#   cisco_ios, which ntc lacks).
# A missing template or a failed parse is an "error" result — NEVER a
# silent raw-string fallback (netmiko's use_textfsm footgun, deliberately
# excluded).


@dataclass(frozen=True, slots=True)
class TestExpectation:
    """Exactly ONE of contains/not_contains/matches/compare (server-checked).

    The raw matchers pair with unparsed stdout; `compare` REQUIRES the case
    to declare `parse` — and vice versa (server-checked both ways). It
    asserts over the parsed data with napalm-validate's grammar (Apache-2.0,
    `napalm.base.validate.compare`): nested partial match by default,
    ``_mode: strict`` for exhaustiveness, numeric operators (``"<15"``,
    ranges ``"10<->20"``, percent tolerance), list semantics. A compare spec
    is DATA — still no expression eval anywhere.

    APPROVED (delta 17): json_path/equals RETIRED — a dotted path is the
    degenerate nested compare spec. No stored-suite migration (dev-phase,
    no real-world data); the repo's example suites are rewritten to v2."""

    contains: str | None = None
    not_contains: str | None = None
    matches: str | None = None  # regex, re.search on stdout
    compare: dict[str, object] | None = None  # napalm-validate spec, see above


@dataclass(frozen=True, slots=True)
class TestCase:
    """What actually runs on a node: one command and how to judge its output.

    `command` — and every string inside `expect` — may carry Jinja2
    ``{{ ... }}`` rendered per executing node against the fact namespace:
    ``node`` (the executing node) and ``nodes.<name>`` (any node), each
    exposing that node's data from the netlab-expanded topology (the same
    artifact behind the link table) — e.g. ``loopback.ipv4``, ``mgmt.ipv4``,
    ``interfaces[].{ifname, ipv4, neighbors}``, ``vrfs.<vrf>.loopback`` —
    plus one filter ``address`` stripping a CIDR's prefix length
    ("10.0.0.5/32" → "10.0.0.5"). APPROVED (delta 26 — supersedes
    delta 17's PROVISIONAL namespace): the namespace is
    PARTITIONED — promised-core paths (appendix: "Pinned fact
    namespace") are stable contract; everything else sits under
    per-object ``_extras`` and carries NO promises, so a template
    spelling ``node._extras.…`` is visibly leaning on netlab-shaped
    data that may drift across netlab versions. Inspect it with
    `facts()`.
    Rendering is SANDBOXED (jinja2 SandboxedEnvironment, no attribute
    escapes) with StrictUndefined: at PUT, templates are always
    syntax-checked and — when the lab has a definition, so facts exist —
    dry-rendered, either failure a 422 ``template_invalid``; a render
    failure at run time (suite authored before the definition, later
    drifted) is that check's "error" result, never a crashed job.

    `mode` (delta 28) names the LANGUAGE the command's words are in.
    "shell" (default, and what every pre-delta-28 suite means) sends them
    verbatim to whatever the transport lands in — for a docker-transport
    device that is the CONTAINER'S SHELL, Debian userland, NOT the NOS CLI.
    "cli" declares the device's own CLI and the server rewrites the command
    to reach it (VyOS op-mode wrapper, ``vtysh -c`` on FRR, ``birdc``,
    identity where the transport already lands in the CLI). 422
    ``template_invalid`` when the device has no CLI of its own (linux,
    dnsmasq: the shell IS the interface). Without this a CLI-shaped command
    reached the wrong interpreter silently — ``ping X vrf Y count 5`` on
    VyOS hit Linux's ping, which has no ``vrf`` flag.

    `interactive` runs the command through a REAL interactive session
    instead of a one-shot. On SSH transports that is a persistent netmiko
    channel: IOS closes a one-shot exec channel on timed commands
    (``ping ... repeat``, ``traceroute``), truncating output after the first
    packet. On docker transports it is a PTY-backed ``docker exec -it``
    (delta 28 — previously a silent no-op there), which also matters for
    semantics: VyOS installs op-mode from interactive shell init, so a
    ``mode: cli`` command needs NO wrapper on that path. Off by default:
    gates should assert programmed state, not live traffic."""

    command: str
    expect: TestExpectation
    parse: ParseMode | None = None
    mode: CommandMode = "shell"
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class ValidationTest:
    """Run a case on each node; poll until it passes.

    `run` is ONE case for every node, or a DEVICE-KEYED dict (netlab device
    names: "vyos", "frr", "linux", ...) — the multi-vendor mechanism, so a
    single suite serves several NOS flavors of one topology: each node
    picks its device's case, and a node whose device has none reports
    "skip", not an error. APPROVED (delta 17): keying is CASE-level (one
    atomic command/parse/expect recipe per device), not netlab's
    field-level parallel dicts — no key-consistency rules, one union in
    the types; the accepted cost is repeating a shared matcher across
    cases (a `default`-case merge is a possible ADDITIVE later extension).
    `wait` (0-600 s) polls until the expectation holds — the convergence
    knob.

    PROPOSED (delta 32): the target is THREE selectors, unioned, because a
    node list is not edit-proof — add a router to the lab and every test
    silently keeps testing the old set, which is the failure mode where a
    suite quietly stops covering what it was written to cover.

      all_nodes=True                    every node in the lab
      groups=["core"]                   every member of those groups
      nodes=["x", "y"]                  exactly these
      groups=["core"], nodes=["x"]      the group's members plus x

    At least one must select something (the empty test is a 422, as an
    empty `nodes` was). Groups are the DEFINITION's groups, resolved to
    node names — nested groups flattened; see LabFacts.groups for what a
    name resolves to. Resolution order is first
    appearance: all_nodes in topology order, then each group's members,
    then the explicit nodes — which leaves a nodes-only test running in
    exactly the order it always did."""

    run: TestCase | dict[str, TestCase]
    # PROPOSED (delta 32): was required and the only selector. Still the
    # precise one; now optional because a test may select purely by group
    # or by "everything".
    nodes: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    all_nodes: bool = False
    wait: int = 0
    description: str = ""


@dataclass(frozen=True, slots=True)
class TestSuite:
    """Named test group. `stage` controls only *automatic* runs: config-time
    suites run after every configure and gate "config done". Any suite can be
    run manually."""

    tests: dict[str, ValidationTest]
    stage: Literal["config-time", "runtime"] = "runtime"
    description: str = ""


@dataclass(frozen=True, slots=True)
class TestResult:
    """One (test, node) outcome. "fail" = expectation never held (after
    `wait`); "error" = command couldn't run, render, or parse; "skip" = the
    node's device has no case in a device-keyed test. `command` is the
    RENDERED command (what actually ran — the debugging artifact); `diff`
    is napalm-validate's structured complies/present/missing/extra report,
    populated only when a `compare` decided the outcome."""

    test: str
    node: str
    status: Literal["pass", "fail", "skip", "error"]
    command: str
    output: str
    detail: str
    diff: dict[str, object] | None
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class SuiteReport:
    suite: str
    stage: str
    passed: int
    failed: int
    skipped: int
    errored: int
    ran_at: datetime
    results: list[TestResult]


@dataclass(frozen=True, slots=True)
class TestSuitesResponse:
    """Declared suites + last run per suite (empty if never run) + the
    config-time gate from the most recent configure."""

    test_suites: dict[str, TestSuite]
    last_validation: dict[str, SuiteReport]
    config_time_status: ConfigTimeStatus  # APPROVED — wire today: config_time_ok


# --------------------------------------------------------------------------- #
# Test-case dry run (delta 31, PROPOSED 2026-08-11)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TestCaseDraft:
    """One case being AUTHORED — a TestCase whose `expect` is optional
    (delta 31). That is the whole difference: a saved case must assert
    something, a case you are still writing need not, because the first
    question is "what does this command print on this node?"."""

    command: str
    expect: TestExpectation | None = None
    parse: ParseMode | None = None
    mode: CommandMode = "shell"
    interactive: bool = False
    # NOTE the coupling relaxes with the expectation: a stored TestCase must
    # pair `compare` with `parse` in BOTH directions, but a draft declaring
    # `parse` and no `expect` is legal — asking to SEE the parsed structure is
    # precisely how a compare gets written. With an `expect` present the full
    # rule applies again.


@dataclass(frozen=True, slots=True)
class TestCaseDryRunResult:
    """What one unsaved case did on one node (delta 31).

    `parsed` is the piece no existing response carries: `_run_check`
    computes the parsed structure to assert against and then discards it,
    so a `compare` — which asserts over PARSED data — has always had to be
    predicted rather than read. Here it is returned, which is what makes a
    compare writable without guessing at TextFSM's or `vtysh … json`'s
    output shape.

    The last three are present ONLY when the draft supplied an `expect`:
    with no expectation there is no outcome to report, and saying "pass"
    would be a lie about a question nobody asked."""

    node: str
    device: str  # the node's netlab device — which CLI adapter and TextFSM
    #              platform applied, and why a `cli`/`textfsm` case may 422
    command: str  # the RENDERED and ADAPTED command — what actually ran
    output: str  # captured stdout (bounded like TestResult.output)
    parsed: object | None  # the parse result when `parse` was set; None
    #                        otherwise, or when parsing failed. `object`
    #                        because its shape is the device's, not Twinlab's.
    # A parse failure is an ANSWER here rather than an error: this is set, the
    # raw `output` survives, and the response is a 200 — seeing what the parser
    # choked on is exactly how the case gets fixed. In a SAVED run the same
    # failure is a TestResult with status "error", because there the parse
    # feeds an assertion that can then no longer be made.
    parse_error: str | None
    elapsed_ms: int
    status: Literal["pass", "fail"] | None = None
    detail: str = ""
    diff: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class LabFacts:
    """The per-node fact namespace test-suite templates render against —
    netlab's node data from the expanded topology, keyed by SHORT node
    name. `nodes[n]` is exactly what `nodes.<n>` (and `node`, for the
    executing node) resolves to in a template.

    APPROVED (delta 26): each node's dict is a PARTITION —
    the promised-core members (appendix: "Pinned fact namespace") sit in
    place with pinned shapes and are stable contract; EVERY other key
    rides verbatim under `_extras` (per recognized object, omitted when
    empty), netlab-shaped, NO promises — may change or vanish with any
    netlab release, netlab-internal `_`-prefixed keys included. Nothing
    is dropped: reassembling `_extras` in place reproduces netlab's raw
    dict. The type stays untyped-dict on purpose: typing the core would
    freeze netlab's node schema into the client — the appendix, not the
    type system, is the contract surface. Inspect a real lab's namespace
    with `facts()`."""

    nodes: dict[str, dict[str, object]]
    # PROPOSED (delta 32): the definition's groups, each resolved to the
    # NODE names it selects — nested groups flattened, so a consumer never
    # reimplements that. Only the groups the definition itself declares:
    # netlab's expanded topology also carries internal bookkeeping groups
    # (`netlab_no_collect`, `netlab_no_reload`) which are never targetable.
    # Empty when the definition declares none. Served here rather than as a
    # resource of its own because the two are asked for together: a suite
    # builder needs the namespace to template against AND the groups to
    # target by.
    groups: dict[str, list[str]]


# --------------------------------------------------------------------------- #
# Jobs (async lab operations — delta 12)
# --------------------------------------------------------------------------- #

JobKind = Literal["deploy", "configure", "destroy", "suite_run"]
JobStatus = Literal["running", "succeeded", "failed"]
# How a STEP reads (delta 29), not how the job ended.
JobStepLevel = Literal["info", "warning", "error"]
# No "pending"/"queued" status: there is no queue — a job starts the moment
# its submit returns 202 (the one-running-job-per-lab mutex REJECTS a
# concurrent submit with 409 job_in_flight rather than queueing it).


@dataclass(frozen=True, slots=True)
class JobError:
    """Why a job FAILED — the error envelope, with TwinlabApiError's fields.
    `status_code` classifies the failure in HTTP vocabulary (422
    netlab_invalid, 502 upstream_error, ...) so error handling can match on
    the same codes everywhere; it is never an actual response status (job
    reads are 200)."""

    status_code: int
    code: str
    message: str
    extras: dict[str, object]


@dataclass(frozen=True, slots=True)
class Job:
    """One async lab operation, submitted by deploy/configure/destroy/suite
    run and read back via `get_job`/`list_jobs`.

    **failed = the operation could not run** (netlab rejected the stored
    definition, clab-api/runner unreachable, ...) with the envelope in
    `error`; an operation that RAN but produced a bad outcome — a config
    push failing on nodes, a red config-time gate — is a **succeeded** job
    whose `result.status` says so ("config_failed" / "validation_failed").

    `result` is populated only on "succeeded", typed by `kind` (APPROVED:
    the union, no per-kind accessors — the caller knows what it submitted):
      deploy -> DeployResponse        configure -> ConfigureResponse
      destroy -> DestroyResponse      suite_run -> SuiteReport

    `request` echoes the submitted parameters verbatim (APPROVED: a raw
    dict — history/display data, not a typed surface).

    A backend restart fails any then-running job (code "backend_restart" —
    the in-process task cannot survive; the record does). Finished jobs are
    pruned beyond the newest ~20 per lab."""

    id: UUID
    lab_name: str
    kind: JobKind
    status: JobStatus
    request: dict[str, object]
    result: DeployResponse | ConfigureResponse | DestroyResponse | SuiteReport | None
    error: JobError | None
    created_at: datetime
    finished_at: datetime | None  # None while running


# PROPOSED (delta 29, APPROVED 2026-08-10): what an operation DID, recorded
# as it happened. A running job was visible but opaque — the phases that
# decide whether a deploy is healthy (the image pre-flight, host prep,
# netlab's output, Ansible's per-node push, the config-time suites) all run
# inside the job task and never left the backend, which is why the deploy
# dialog had to apologise in prose for its own quiet stretches. Design record:
# docs/job-steps.md.
@dataclass(frozen=True, slots=True)
class JobStep:
    """One thing the operation did.

    `code` names the phase from the vocabulary pinned below; `message` carries
    the detail no vocabulary can anticipate ("7/7 nodes ok"). The split is the
    error envelope's: a slug a client can branch on, plus prose for a human.

    Steps are a NARRATIVE, not the record. The operation's typed payload stays
    on `Job.result`/`Job.error` and nothing is derivable ONLY from a step, so a
    client that ignores them loses readability and nothing else. That is
    exactly what lets the vocabulary GAIN entries without a contract change —
    so an unknown `code` is displayable, never an error. `level` IS closed
    (a client renders on it).

    THE VOCABULARY, per job kind:
      deploy    host_resources, topology_generated, image_preflight,
                host_prep, clab_deploy_started, nodes_deployed, nodes_ready,
                config_push_started, config_pushed, validation
      configure config_push_started, config_pushed, validation
      destroy   clab_destroy, files_removed, bridges_released,
                record_removed | record_kept
      suite_run suite_started, suite_finished
      any       steps_truncated (the 64-step cap; recorded, never silent)

    A `_started` code exists only where the phase is long enough that its
    absence reads as a stall — the two long waits in a deploy are clab-api
    standing the containers up and Ansible pushing config. Fast phases get one
    step, at their outcome.

    A warning or error LEVEL says nothing about how the job ended: an image
    that has to be pulled, or a config push that failed on 2 of 7 nodes, both
    sit inside a SUCCEEDED job (failed still means could-not-run)."""

    at: datetime
    code: str
    level: JobStepLevel
    message: str


@dataclass(frozen=True, slots=True)
class JobDetail(Job):
    """A job read on its own — `get_job` — which is the ONLY place the step log
    is served. `list_jobs` and `list_all_jobs` keep returning `Job`: they
    render kind/status/timing, and carrying every job's narrative through a
    fleet-wide `limit=50` poll would be waste. Same summary/detail split as
    LabSummary/LabDetail.

    Steps arrive OLDEST first and GROW while the job runs, so polling a running
    job is how a caller follows an operation's progress — there is deliberately
    no step event on the SSE stream (delta 16 pinned `job` events as a poke,
    never the record, and the broker under them is lossy by design).

    Steps live and die with the job row: finished jobs are pruned beyond the
    newest ~20 per lab, so this is recent history, never an audit log."""

    steps: list[JobStep]


@dataclass(frozen=True, slots=True)
class JobEvent:
    """PROPOSED (delta 16, APPROVED, not served yet) one job-lifecycle
    payload from `GET /events`, carried by the NAMED SSE event ``job``.

    A POKE, not a report: it says which job changed and to what, never the
    job's `result`/`error` — read those with `get_job` (they are typed by
    kind and would fork the shape if duplicated here).

    Emitted twice per job: at submit (status "running") and when it reaches a
    terminal state. `timestamp` is the job's `created_at` / `finished_at`
    respectively, so the event carries the same instant the record does.

    NOT a durable log: there is no replay on reconnect (see `events`)."""

    lab: str
    job_id: UUID
    kind: JobKind
    status: JobStatus
    timestamp: str


# --------------------------------------------------------------------------- #
# Custom-config shapes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TemplateVariant:
    """One source of a config template, scoped by exactly one of: ``node``
    (that one node), ``device`` (any node of that catalog device slug), or
    neither (universal). Delta 27: the scopes mirror netlab's own lookup
    precedence — node beats device beats universal — enforced by the
    filenames the backend materializes, not by any code. Setting both is
    422; a user variant's ``device`` must be a catalog slug (422) — builtin
    variants may carry a non-catalog label (``ios``), which simply applies
    to no node."""

    source: str  # Jinja2, rendered by netlab over the node model; ≤64KB
    device: str | None = None
    node: str | None = None


ConfigTemplateTier = Literal["builtin", "user"]


@dataclass(frozen=True, slots=True)
class ConfigTemplate:
    """A custom-config template record (delta 27): the ``config:`` name a
    definition references (``[A-Za-z_][A-Za-z0-9_-]*``, ≤64), a description
    (may be empty), its tier, and ≥1 scoped variants. APPLICABILITY is one
    rule everywhere: the template applies to a node if some variant matches
    it (node name, else device, else universal); to a group iff it applies
    to every member. Builtins are code-shipped and read-only."""

    name: str
    description: str
    tier: ConfigTemplateTier
    variants: list[TemplateVariant]


@dataclass(frozen=True, slots=True)
class ConfigTemplateSpec:
    """PUT's input shape: a user-tier template — ``ConfigTemplate`` minus
    ``tier`` (everything a caller PUTs is user tier)."""

    name: str
    description: str
    variants: list[TemplateVariant]


@dataclass(frozen=True, slots=True)
class CustomConfigResponse:
    """The lab's whole template library, ONE merged list — builtins first
    (identical for every lab), then the lab's user records. Delta 27: the
    netlab-facing fileset is derived server-side (``name/<node>.j2`` |
    ``name/<slug>.j2`` | ``name.j2``) and never travels the wire."""

    templates: list[ConfigTemplate]


# --------------------------------------------------------------------------- #
# Action vocabularies
# --------------------------------------------------------------------------- #

LabPowerAction = Literal["start", "stop", "restart", "pause", "unpause"]
NodePowerAction = Literal["start", "stop", "restart", "pause", "unpause"]
# QUIRK: lab pause/unpause fan out per node (clab-api has no lab pause);
# non-atomic — partial failure = 502 listing failed nodes; 409 if none running.


# PROPOSED (delta 24, APPROVED): batch runtime actions. The client discriminates items
# by dataclass; the wire carries a ``kind`` tag ("netem" | "power").
@dataclass(frozen=True, slots=True)
class NetemAction:
    """PROPOSED (delta 24, APPROVED): THE impairment spelling — the single netem
    route's body plus its address. ``set_netem`` takes one standalone,
    ``apply_actions`` takes a list; the same object serves both (the wire
    identity: the batch item is these fields + ``kind``; the single route
    puts ``node`` in the path and the rest in the body — unchanged). States
    the interface's COMPLETE desired impairment (REPLACE); all dimensions
    None = clear the interface. Validation (jitter requires delay,
    loss/corruption 0-100 %, rate kbit/s) is identical standalone or
    batched — in a batch it runs up front for EVERY item before anything
    executes."""

    node: str  # SHORT node name, as everywhere
    interface: str  # container-side name — what /interfaces and links() report
    delay: Duration | None = None
    jitter: Duration | None = None
    loss: float | None = None
    rate: int | None = None
    corruption: float | None = None


@dataclass(frozen=True, slots=True)
class PowerAction:
    """PROPOSED (delta 24, APPROVED): one batch item — node_power's PATH PAIR
    materialized as fields (same NodePowerAction vocabulary). Exists to put
    the pair in a list; the standalone ``node_power`` keeps its two scalars
    — a wrapper there would be ceremony."""

    node: str
    action: NodePowerAction


@dataclass(frozen=True, slots=True)
class RuntimeActionResult:
    """PROPOSED (delta 24, APPROVED): one batch item's outcome, INDEX-ALIGNED with the
    submitted list. ok=True → ``message`` is clab-api's verbatim response
    (the LabActionResponse precedent) and ``code`` is None; ok=False →
    ``code`` + ``message`` are what the standalone verb's error envelope
    would have carried (``node_not_found``, ``netem_failed``, ...) — the
    slugs are identical to the single routes'."""

    ok: bool
    code: str | None
    message: str


@dataclass(frozen=True, slots=True)
class RuntimeActionsReport:
    """PROPOSED (delta 24, APPROVED): the batch outcome. A 2xx means the batch RAN;
    each item's success or failure lives here, never in the HTTP status."""

    results: list[RuntimeActionResult]  # index-aligned with the request


# --------------------------------------------------------------------------- #
# Terminal
# --------------------------------------------------------------------------- #


class TerminalSession(AbstractAsyncContextManager["TerminalSession"]):
    """Node terminal: ``WS /api/v1/labs/{name}/nodes/{node}/terminal``
    (lab:terminal). Auth from the handshake cookie BEFORE accept; rejection
    closes 1008 with no reason. Upstream failure after accept closes 1011.

    Frames (clab-api's protocol, relayed verbatim):
      client -> {"type": "input"|"resize"|"close", ...}
      server -> {"type": "ready"} | {"type": "output", "data": <base64>}
              | {"type": "exit", ...}
    The client library owns the base64 decode and exposes bytes.

    QUIRK: path params are `name`/`node` vs `lab_name`/`node_name` elsewhere
    (OpenAPI-visible). PROPOSAL: rename during the rework.
    """

    async def send(self, data: bytes) -> None:
        raise NotImplementedError

    async def recv(self, timeout: float | None = None) -> bytes:
        """Decoded output. Raises on exit/close."""
        raise NotImplementedError

    async def resize(self, cols: int, rows: int) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #


class TwinlabClient(AbstractAsyncContextManager["TwinlabClient"]):
    """Async Twinlab API client. One instance = one session (cookie jar on the
    instance); use as ``async with TwinlabClient(...) as client``. Non-2xx
    raises ``TwinlabApiError``.

    The four long operations (deploy/configure/destroy/suite run) are ASYNC
    JOBS (delta 12): submit returns 202 + a running `Job`; the caller polls
    `get_job` (or `wait_job`) for the terminal state. Every HTTP call is
    short — `action_timeout` is the default `wait_job` deadline, i.e. how
    long a submitted operation may take end to end.
    """

    def __init__(
        self,
        base_url: str,
        *,
        subpath: str = "/api/v1",
        api_key: str | None = None,
        timeout: float = 30.0,
        action_timeout: float = 1800.0,
        verify_tls: bool = True,
    ) -> None:
        """`base_url` = backend origin (e.g. "http://localhost:8000");
        `subpath` is appended to it. `api_key` authenticates every request as
        `Authorization: Bearer <key>` instead of a login session (PROPOSED —
        no backend support yet; `login` still works on a keyed client but is
        pointless). `action_timeout` is the default `wait_job` deadline —
        submits themselves are fast 202s (delta 12)."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Close the underlying HTTP client (also done by `async with`)."""
        raise NotImplementedError

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # Health (unauthenticated)
    # ------------------------------------------------------------------ #

    async def health(self) -> Liveness:
        """GET /health — dependency-free liveness."""
        raise NotImplementedError

    async def ready(self) -> Readiness:
        """GET /health/ready — parses both 200 and 503 (degraded is data, not
        an error). Gate the black-box suite on this."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #

    async def login(self, username: str, password: str) -> UserInfo:
        """POST /auth/login — sets the session cookie. 401 "invalid
        credentials" for both unknown-user and wrong-password (deliberately
        opaque)."""
        raise NotImplementedError

    async def logout(self) -> None:
        """POST /auth/logout — 204; idempotent."""
        raise NotImplementedError

    async def me(self) -> UserInfo:
        """GET /auth/me — identity + GLOBAL roles/permissions."""
        raise NotImplementedError

    async def change_password(self, current: str, new: str) -> None:
        """PROPOSED (APPROVED, not served yet) PUT /auth/password —
        self-service change, requires the current password. 204; revokes the
        user's OTHER sessions, keeps this one."""
        raise NotImplementedError

    async def update_own_profile(self, display_name: str) -> UserInfo:
        """PROPOSED (delta 33) PUT /auth/profile — the caller's own display
        name (1–128 chars). DELIBERATELY not the email: with email tying, a
        user who could set their own address to a colleague's would receive
        that colleague's first provider sign-in. Only an admin edits an email,
        their own included (`update_user_profile`)."""
        raise NotImplementedError

    # OIDC sign-in — PROPOSED (delta 33, design record docs/oidc.md). The
    # flow itself is BROWSER-ONLY and has no client method: `GET
    # /auth/oidc/{name}/login?next=<relative path>` 302s to the provider, and
    # `GET /auth/oidc/{name}/callback` finishes with a 302 to `next` carrying
    # the ordinary session cookie. On failure it 302s to
    # `/login?oidc_error=<code>`, with codes oidc_unavailable /
    # oidc_state_invalid / oidc_provider_error / oidc_token_invalid /
    # oidc_email_missing / oidc_email_unverified / oidc_email_in_use /
    # oidc_no_account / oidc_identity_conflict / account_disabled. A person has to be at the
    # provider's login form, so a headless client cannot drive it. An OIDC
    # user automates by creating an API key after signing in in the browser.

    async def login_providers(self) -> list[LoginProvider]:
        """PROPOSED (delta 33) GET /auth/oidc/providers — UNAUTHENTICATED;
        the ENABLED providers, for the login page. Empty when none are
        configured or when PUBLIC_URL is unset (sign-in through a provider is
        then off)."""
        raise NotImplementedError

    # API keys — PROPOSED (no backend support yet): self-service long-lived
    # credentials for automation (CI, the black-box suite), sent as
    # `Authorization: Bearer <key>`. A key acts as its creating user with that
    # user's permissions (no separate key scoping in v1); stored hashed;
    # deleting/deactivating the user kills its keys.

    async def create_api_key(self, name: str) -> ApiKeyCreated:
        """PROPOSED POST /auth/api-keys — 201. The secret is returned only
        here. 409 name_taken (per user)."""
        raise NotImplementedError

    async def list_api_keys(self) -> list[ApiKey]:
        """PROPOSED GET /auth/api-keys — the caller's own keys, no secrets."""
        raise NotImplementedError

    async def revoke_api_key(self, key_id: UUID) -> None:
        """PROPOSED DELETE /auth/api-keys/{key_id} — 204, immediate."""
        raise NotImplementedError

    # SSH keys (delta 13): registered PUBLIC keys unlock the stack's SSH jump
    # host. Through it a key's owner reaches ALL TCP ports of nodes in labs
    # where they hold lab:terminal (owner-implicit included) — TCP forwarding
    # only, no shell/PTY on the jump itself. Authorization is re-evaluated
    # from live RBAC at every NEW connection: deleting a key, revoking
    # lab:terminal, or deactivating the user takes effect on the next
    # connection (established tunnels survive until closed), and the
    # permitted node set is frozen per connection (reconnect after a
    # redeploy changes node IPs).

    async def create_ssh_key(self, name: str, public_key: str) -> SshKey:
        """POST /auth/ssh-keys — 201. `public_key` is one OpenSSH
        authorized_keys-format line ("<algorithm> <base64> [comment]", no
        options). 422 invalid_public_key / unsupported_key_type; 409
        name_taken (per user); 409 key_already_registered — fingerprints are
        GLOBALLY unique, a key identifies one person at the jump."""
        raise NotImplementedError

    async def generate_ssh_key(self, name: str) -> SshKeyGenerated:
        """POST /auth/ssh-keys/generate — 201. Server-side ed25519 pair for
        users without their own key: the public half is registered under
        `name` (equivalent to create_ssh_key from then on), the private half
        is returned only here and never stored. 409 name_taken (per user);
        a fingerprint conflict cannot occur (the key is freshly random)."""
        raise NotImplementedError

    async def list_ssh_keys(self) -> list[SshKey]:
        """GET /auth/ssh-keys — the caller's own keys."""
        raise NotImplementedError

    async def delete_ssh_key(self, key_id: UUID) -> None:
        """DELETE /auth/ssh-keys/{key_id} — 204. 404 ssh_key_not_found (own
        keys only; someone else's id is indistinguishable from absent)."""
        raise NotImplementedError

    async def get_ssh_access(self) -> SshAccess:
        """GET /ssh-access — jump-host coordinates; any authenticated user."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Users (global user:manage)
    # ------------------------------------------------------------------ #
    # PROPOSED endpoints below (approved) are marked in their docstrings.

    async def create_user(
        self,
        username: str,
        email: str,
        display_name: str,
        *,
        password: str | None = None,
        roles: set[str] | None = None,
    ) -> UserCreated:
        """POST /users — 201. `roles` = GLOBAL roles; omitted/empty = the
        baseline "user" role (authenticated, no access). 409 username_taken;
        422 unknown_roles; password min 8.

        PROPOSED (delta 33): `email` and `display_name` are required. The email
        is checked structurally only (one @, non-empty parts, no whitespace)
        and must be unused case-insensitively, else 409 email_taken.
        `password` became optional: when omitted, the server generates one (24
        URL-safe chars) and returns it ONCE on `UserCreated.generated_password`.
        (wire today: returns `UserSummary`; password required; no email or
        display name.)"""
        raise NotImplementedError

    async def update_user_profile(
        self, user_id: UUID, *, email: str, display_name: str
    ) -> UserSummary:
        """PROPOSED (delta 33) PUT /users/{user_id}/profile — full replace of
        both fields, for ANY user including the caller, so an admin replaces
        their own backfilled `<username>@users.invalid` here. 404
        user_not_found; 409 email_taken. Changing an email
        does NOT touch the user's linked identities: the link, not the email,
        is what their provider sign-in resolves through."""
        raise NotImplementedError

    async def unlink_identity(self, user_id: UUID, identity_id: UUID) -> None:
        """PROPOSED (delta 33) DELETE /users/{user_id}/identities/{identity_id}
        — 204. 404 identity_not_found (also for an identity of ANOTHER user).
        The next sign-in through that provider goes through the tie/create
        rules again, which is how an admin repairs a tie that went to the wrong
        account."""
        raise NotImplementedError

    async def list_users(self) -> list[UserSummary]:
        """GET /users. No pagination anywhere (explicit v1.0 decision)."""
        raise NotImplementedError

    async def get_user(self, user_id: UUID) -> UserSummary:
        """PROPOSED (APPROVED, not served yet) GET /users/{user_id} — 404
        user_not_found."""
        raise NotImplementedError

    async def set_user_roles(self, user_id: UUID, roles: set[str]) -> UserSummary:
        """PUT /users/{user_id}/roles — full replace of global roles.
        404 user_not_found; 422 unknown/non-global role."""
        raise NotImplementedError

    async def set_user_password(self, user_id: UUID, password: str) -> None:
        """PROPOSED (APPROVED, not served yet) PUT /users/{user_id}/password —
        admin reset. 204; revokes ALL the user's sessions."""
        raise NotImplementedError

    async def set_user_active(self, user_id: UUID, is_active: bool) -> UserSummary:
        """PROPOSED (APPROVED, not served yet) PUT /users/{user_id}/active —
        deactivate/reactivate. Deactivation revokes the user's sessions and
        stops their API keys; record, bindings, and owned labs are untouched —
        the reversible soft alternative to delete_user. Refuses deactivating
        the last active admin (409, same rule as delete)."""
        raise NotImplementedError

    async def delete_user(self, user_id: UUID) -> None:
        """PROPOSED (APPROVED, not served yet) DELETE /users/{user_id} — 204.

        Semantics to pin: revoke the user's sessions; delete role bindings
        they RECEIVED (cascade); keep rows where they were the actor — owned
        labs -> owner NULL (FK is already SET NULL), grants they MADE keep
        granted_by NULL. Refusing to delete the last admin (409) — APPROVED."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Groups (global group:manage)
    # ------------------------------------------------------------------ #

    async def create_group(self, name: str, description: str = "") -> GroupSummary:
        """POST /groups — 201. 409 name_taken."""
        raise NotImplementedError

    async def list_groups(self) -> list[GroupSummary]:
        """GET /groups."""
        raise NotImplementedError

    async def get_group(self, group_id: UUID) -> GroupSummary:
        """PROPOSED (APPROVED, not served yet) GET /groups/{group_id} — 404
        group_not_found."""
        raise NotImplementedError

    async def delete_group(self, group_id: UUID) -> None:
        """DELETE /groups/{group_id} — 204. Also deletes the group's bindings;
        members untouched."""
        raise NotImplementedError

    async def set_group_members(
        self, group_id: UUID, user_ids: list[UUID]
    ) -> GroupSummary:
        """PUT /groups/{group_id}/members — full replace. 404 group_not_found;
        422 user_not_found."""
        raise NotImplementedError

    async def set_group_roles(self, group_id: UUID, roles: set[str]) -> GroupSummary:
        """PUT /groups/{group_id}/roles — full replace of GLOBAL roles (lab
        grants go through create_grant). 422 non-global-bindable role."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # OIDC providers (global user:manage) — PROPOSED (delta 33)
    # ------------------------------------------------------------------ #
    # Gated by user:manage, not a new permission, because a provider decides
    # who gets an account, which is user management by another route
    # (review item 5 in docs/oidc.md). CREATE fetches
    # {issuer}/.well-known/openid-configuration SYNCHRONOUSLY and requires its
    # `issuer` to equal the configured one, so a mistyped issuer is a 422 in
    # front of the admin who typed it, not a failed sign-in for the first user.
    # Update does not refetch it: the issuer is immutable, and a provider whose
    # discovery endpoint is down must still be editable, above all disableable.

    async def list_oidc_providers(self) -> list[OidcProvider]:
        """PROPOSED GET /oidc-providers — all of them, enabled or not."""
        raise NotImplementedError

    async def get_oidc_provider(self, name: str) -> OidcProvider:
        """PROPOSED GET /oidc-providers/{name} — 404 provider_not_found."""
        raise NotImplementedError

    async def create_oidc_provider(
        self,
        name: str,
        display_name: str,
        issuer: str,
        client_id: str,
        *,
        client_secret: str | None,
        # Why this default: `email` feeds tying and creation, `profile` the
        # display name and derived username — what the resolution rules read.
        scopes: list[str] | None = None,  # None = ["openid", "email", "profile"]
        allow_create_users: bool = False,  # safe default: sign-in for linked users only
        allow_email_tying: bool = False,  # same
        trust_email: bool = False,  # same: vouching for an issuer is a deliberate act
        default_group_id: UUID | None = None,
        enabled: bool = True,
    ) -> OidcProvider:
        """PROPOSED POST /oidc-providers — 201. `client_secret` None = a public
        client (PKCE alone); it is required as a keyword so a confidential
        client is never created without its secret by omission. 409
        provider_name_taken / issuer_taken; 409 oidc_secret_key_unset (a
        secret was given but the deployment has no OIDC_SECRET_KEY to encrypt
        it with); 422 oidc_discovery_failed (with the fetch or mismatch reason
        in extras), 422 validation_error (bad name slug, scopes without
        "openid"), 422 group_not_found. The icon is set separately
        (`set_oidc_provider_icon`)."""
        raise NotImplementedError

    async def update_oidc_provider(
        self,
        name: str,
        *,
        display_name: str,
        issuer: str,
        client_id: str,
        scopes: list[str],
        allow_create_users: bool,
        allow_email_tying: bool,
        trust_email: bool,
        default_group_id: UUID | None,
        enabled: bool,
        client_secret: str | None | Unchanged = UNCHANGED,
    ) -> OidcProvider:
        """PROPOSED PUT /oidc-providers/{name} — full replace, EXCEPT:

        - `issuer` must equal the stored one (422 issuer_immutable). It rides
          the body so a replace stays a complete statement of the record and
          a client cannot mistake which issuer it is editing.
        - `client_secret` is write-only: UNCHANGED (the field omitted on the
          wire) keeps the stored secret, a string replaces it, and None
          removes it (the provider becomes a public client). A new secret
          without OIDC_SECRET_KEY is 409 oidc_secret_key_unset.
        - The icon is not part of the replace. It has its own route, so
          editing the form never needs to resend the image.

        `name` is immutable by construction: it is the path. Disabling
        (`enabled=False`) keeps the provider's links; deleting drops them."""
        raise NotImplementedError

    async def delete_oidc_provider(self, name: str) -> None:
        """PROPOSED DELETE /oidc-providers/{name} — 204. Deletes the
        provider's LINKS and keeps its users. A user created through it then
        holds only a random password nobody knows, and cannot sign in until an
        admin resets the password (`OidcProvider.linked_users` is the count to
        warn with). Deliberately NOT blocked on that: removing a compromised
        provider must be possible."""
        raise NotImplementedError

    async def set_oidc_provider_icon(
        self,
        name: str,
        content: bytes,
        content_type: Literal["image/svg+xml", "image/png", "image/webp"],
    ) -> OidcProvider:
        """PROPOSED PUT /oidc-providers/{name}/icon — the raw image as the
        body, `content_type` as its Content-Type; replaces any current icon.
        At most 32 KiB, which is plenty for a button glyph. 422 invalid_icon
        when the bytes are not the declared type (PNG/WebP by magic bytes; SVG
        must parse as XML with an <svg> root) or exceed the size. 404
        provider_not_found."""
        raise NotImplementedError

    async def clear_oidc_provider_icon(self, name: str) -> OidcProvider:
        """PROPOSED DELETE /oidc-providers/{name}/icon — back to the
        monogram. Idempotent: clearing an absent icon is still a 200."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Catalog / directory (any authenticated user)
    # ------------------------------------------------------------------ #

    async def list_roles(self) -> list[Role]:
        """GET /roles — the code-defined role catalog."""
        raise NotImplementedError

    async def list_principals(self) -> Principals:
        """GET /principals. QUIRK (recorded in ROADMAP): exposes all
        user/group names to any authenticated user — accepted for now; revisit
        if enumeration becomes a concern."""
        raise NotImplementedError

    async def device_catalog(self) -> DeviceCatalog:
        """PROPOSED (delta 18, APPROVED, not served yet) GET /catalog — the
        deployable-device catalog: the supported device set with per-device
        module support, the default clab image, and best-effort image
        presence. Any authenticated user (it names no lab, and a deploy
        error would reveal a missing image anyway). Image presence is
        advisory — deploy does NOT pre-flight it; that check is a separate
        parked decision."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Host resources (delta 30, PROPOSED 2026-08-11)
    # ------------------------------------------------------------------ #

    async def host_resources(self) -> HostResources:
        """PROPOSED (delta 30) GET /host — what the machine running the labs
        is spending: CPU, load, memory, swap, and the filesystems the backend
        can see. Any authenticated user, for the same reason as the catalog.
        Cheap: the backend samples on a timer and serves the last snapshot, so
        polling it costs nothing and `sampled_at` is the reading's real age."""
        raise NotImplementedError

    async def docker_usage(self) -> DockerUsage:
        """PROPOSED (delta 30) GET /host/docker — the container daemon's
        counts and disk footprint, mirroring `docker system df`. Any
        authenticated user. NOT cheap (the daemon walks every image, volume
        and build-cache record — about a second on a modest host), which is
        why it is a separate resource from `host_resources` rather than a
        field on it. 503 `docker_usage_unavailable` when the runner is
        unreachable."""
        raise NotImplementedError

    async def lab_usage(self, name: str) -> LabUsage:
        """PROPOSED (delta 30) GET /labs/{name}/usage — per-node CPU, memory
        and network for one lab (`lab:read`). Live-only and best-effort: an
        undeployed lab or an unreachable upstream comes back `live=False`
        rather than an error, and a node that is not running carries no
        measures at all."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Template library (delta 21, APPROVED)
    # ------------------------------------------------------------------ #

    # Two sibling collections under /templates — per-kind, per the review
    # (no consumer wants the union; namespaces are independent). The
    # lab-publication toggle (set_lab_template) is a /labs route but is
    # grouped here so the whole delta reads in one place.

    async def list_network_templates(self) -> list[NetworkTemplateSummary]:
        """PROPOSED (delta 21, APPROVED, not served yet) GET
        /templates/network — both tiers, content omitted. Any
        authenticated user (the library names no lab; a published lab's
        definition is deliberately deployment-public — see
        set_lab_template)."""
        raise NotImplementedError

    async def get_network_template(self, name: str) -> NetworkTemplate:
        """PROPOSED (delta 21, APPROVED, not served yet) GET
        /templates/network/{name} — the entry with its content. For a
        published-lab entry the content is that lab's CURRENT stored
        definition (a live view, never a stale copy). 404
        ``template_not_found``."""
        raise NotImplementedError

    async def list_node_templates(self) -> list[NodeTemplate]:
        """PROPOSED (delta 21, APPROVED, not served yet) GET
        /templates/node — both tiers, FULL entries (fragments are small
        and bounded; the builder palette stamps straight from the list,
        no per-click fetch). Any authenticated user."""
        raise NotImplementedError

    async def get_node_template(self, name: str) -> NodeTemplate:
        """PROPOSED (delta 21, APPROVED, not served yet) GET
        /templates/node/{name}. 404 ``template_not_found``."""
        raise NotImplementedError

    async def create_node_template(
        self, name: str, *, description: str, content: str
    ) -> NodeTemplate:
        """PROPOSED (delta 21, APPROVED, not served yet) POST
        /templates/node — global template:manage; 201 (the builder's
        inspector offers "save node as template" over this). The NETWORK
        collection has no POST: network templates enter the library by
        publishing a lab, because authoring one IS authoring a lab.
        `content` is a YAML node-attribute mapping that MUST name
        `device`. Validation is STRUCTURAL only (parseable mapping, device
        present, bounded size — the definition bounds): a fragment may
        lean on lab-level constructs (vrfs, groups) that no standalone dry
        netlab run could see, so the receiving lab's PUT stays the real
        validator. 409 ``name_taken`` (within the node collection); 422
        ``invalid_template``."""
        raise NotImplementedError

    async def update_node_template(
        self, name: str, *, description: str, content: str
    ) -> NodeTemplate:
        """PROPOSED (delta 21, APPROVED, not served yet) PUT
        /templates/node/{name} — global template:manage. Full REPLACE
        (description AND content, house semantics) of a USER-tier entry.
        409 ``template_readonly`` on a builtin."""
        raise NotImplementedError

    async def delete_node_template(self, name: str) -> None:
        """PROPOSED (delta 21, APPROVED, not served yet) DELETE
        /templates/node/{name} — global template:manage; 204. USER tier
        only: 409 ``template_readonly`` on a builtin. (The NETWORK
        collection has no DELETE: builtins are fixed, and the user tier's
        whole lifecycle is the set_lab_template toggle.)"""
        raise NotImplementedError

    async def set_lab_template(
        self, name: str, *, published: bool, description: str | None = None
    ) -> NetworkTemplateSummary | None:
        """PROPOSED (delta 21, APPROVED, not served yet) PUT
        /labs/{name}/template — the lab page's "use as a template" toggle:
        publishes this lab's stored definition into the NETWORK collection
        as a LIVE template, or withdraws it. Global template:manage PLUS
        lab:read (404 existence-hiding as usual; read suffices because
        publishing changes the LIBRARY, not the lab — template:manage is
        what makes it a deliberate act). `description` is the library-card
        text, stored on the publication: REQUIRED when publishing (422),
        ignored when withdrawing; re-publishing an already-published lab
        just updates it. Returns the resulting entry, None once withdrawn.

        Pinned consequences: while published the definition is readable by
        EVERY authenticated user; 409 ``no_definition`` on an unauthored
        lab; the entry's name is the lab's durable name (labs cannot be
        renamed, so it is stable); soft-deleting the lab withdraws the
        entry; instantiation COPIES — a lab created from the template
        never tracks it. 409 ``name_taken`` only against the NETWORK
        collection (a builtin's name; a node template can never collide)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Definition import (delta 22, APPROVED)
    # ------------------------------------------------------------------ #

    async def import_network(
        self, sources: list[ImportSource], wiring: list[WiringEntry]
    ) -> NetworkImport:
        """PROPOSED (delta 22, APPROVED; REVISED by delta 23, APPROVED) POST
        /import/network — the definition factory: dumped running configs +
        the EXPLICIT wiring in; netlab definition + carry + quarantine +
        maps out. `wiring` is REQUIRED (delta 23): adjacency is never
        inferred — links come from the entries (2 endpoints = p2p, 3+ =
        LAN, all-unnumbered = a `prefix: false` L2 link), addressed
        interfaces in no entry become stubs, and suggest_wiring exists to
        prefill an editor, never to feed this call implicitly. GLOBAL
        lab:create; SYNCHRONOUS (cost ≈ a PUT's dry validate). 422
        ``unsupported_device`` / ``config_unparseable`` / ``duplicate_node``
        / ``wiring_invalid`` (unknown node/interface, an interface in two
        entries, <2 endpoints, a wired mgmt-quarantined interface, bad
        spelling) / ``wiring_conflict`` (endpoint addresses in different
        subnets — asserted wiring makes contradictions errors, not
        findings); extras name the offending source or entry."""
        raise NotImplementedError

    async def suggest_wiring(self, sources: list[ImportSource]) -> WiringSuggestion:
        """PROPOSED (delta 23, APPROVED) POST /import/wiring-suggestion — the
        subnet join as ADVICE: a proposed wiring list from the sources'
        addressing, plus warnings for what it cannot place (unnumbered
        interfaces). Pure parse, no netlab run; GLOBAL lab:create (the
        factory's gate — this is its prefill). The import never consumes a
        suggestion implicitly: the caller reviews, edits, and passes the
        result to import_network explicitly."""
        raise NotImplementedError

    async def import_node(self, device: str, content: str) -> NodeImport:
        """PROPOSED (delta 22, APPROVED) POST /import/node — the single-node
        granularity for the builder's Add menu. Any authenticated user
        (proposed: a pure parse, no subprocess — the same class as reading
        the template library). Same 422 slugs as import_network."""
        raise NotImplementedError

    async def config_diff(
        self, name: str, sources: list[DiffSource]
    ) -> ConfigDiffReport:
        """PROPOSED (delta 22, APPROVED) POST /labs/{name}/config-diff — the
        fidelity proof: collect each named node's RUNNING config over the
        exec transport and classify every source line (matched / missing /
        extra, modulo quarantine and the interface map — recomputed
        STATELESSLY by joining the sources' pinned addresses against the
        lab's facts, because a lab never remembers its import origin;
        DiffSource.interface_map overrides/extends the join for the
        L2-linked interfaces addressing cannot map — delta 23).
        lab:validate (proposed — it execs on nodes, the suite-run class).
        Requires a deployed lab (409 ``lab_not_running``); every
        DiffSource.node must be a lab node (422). SYNCHRONOUS in v1
        (proposed, review item: N sequential execs — becomes a job if that
        proves slow). Informational, never a gate."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — lifecycle
    # ------------------------------------------------------------------ #

    # Lifecycle split (APPROVED, applied — wire today: one-shot POST /labs
    # carrying name+definition+suites+templates, and a separate /redeploy):
    # create (record only) -> author (the PUTs) -> deploy (from the stored
    # record). The mgmt-subnet reservation moves to the cheap create call,
    # killing the reserve/retry race machinery around the slow deploy.

    async def create_lab(self, name: str) -> LabDetail:
        """POST /labs {name} — 201. GLOBAL lab:create; caller becomes owner.

        Record only: allocates the lab's mgmt /24, status "created" — no
        definition yet, nothing deployed. `name` is the lab's durable identity
        and must be a netlab identifier — a leading letter then
        letters/digits/dash/underscore, at most 16 characters — because it is
        pinned into the stored definition as netlab's topology `name:`, which
        netlab validates as an identifier. A wider name would create a lab
        whose definition PUT can never succeed.
        409 name taken; 422 invalid name; 503 subnet pool exhausted."""
        raise NotImplementedError

    async def list_labs(self) -> list[LabSummary]:
        """GET /labs — filtered to labs with lab:read (owned, granted, group,
        global). No access = [] — never 403."""
        raise NotImplementedError

    async def get_lab(self, name: str) -> LabDetail:
        """GET /labs/{name} — lab:read. 404 if absent OR unreadable; 502 on
        clab-api failure other than lab-not-deployed."""
        raise NotImplementedError

    async def update_definition(self, name: str, definition: str) -> LabDetail:
        """PUT /labs/{name} — lab:edit. Replaces the STORED definition only
        (applies on next deploy). The definition must name each node's `device`
        and the `provider`; any `name:` in it is overridden by the record, and
        the mgmt subnet is re-pinned (explicit `addressing.mgmt.ipv4` wins).
        Validated by a dry `netlab create` (422). 409 subnet clash. Legal
        netlab keys Twinlab does not honor are 422 `unsupported_directive`
        rather than silently ignored (up-parity decisions, docs/nos-sweep/):
        `tools:`, `defaults.netlab.up/down` shell hooks,
        `defaults.providers.clab.bridge_type: ovs-bridge`, and link or
        interface `tc:` impairment; extras `directives` lists each
        `{key, reason}`."""
        raise NotImplementedError

    async def deploy_lab(
        self,
        name: str,
        *,
        configure: bool = False,
        skip_config_time_checks: bool = False,
    ) -> Job:
        """POST /labs/{name}/deploy — lab:edit. **202 + the running deploy
        Job**. The job's first step is an image pre-flight (up-parity gap 3,
        2026-08-04): a missing image whose device the catalog marks
        local-only fails the job `image_missing` before anything touches the
        host; missing-but-pullable images only warn (DeployResponse.warnings)
        and a runner outage skips the check. (delta 12 — wire today: a synchronous long call returning
        DeployResponse directly). Deploys from the stored definition + suites
        + custom config: fresh if "created"/"destroyed", overwrite-in-place
        if running. The terminal job's `result` is a DeployResponse.

        Pre-accept (synchronous) errors: 409 no stored definition yet; 409
        `job_in_flight` — ONE running job per lab, any kind. Post-accept
        failures — netlab rejecting the stored definition, clab-api/runner
        unreachable — fail the JOB (`error` carries the envelope); a push
        that ran but failed and a red gate stay job successes
        ("config_failed" / "validation_failed" result statuses)."""
        raise NotImplementedError

    # (create_and_deploy convenience removed per review: a client-side
    # composition cannot be atomic — a partway failure would strand a
    # "created" record — and the bar was "remove unless atomic". Callers
    # compose create_lab + PUTs + deploy_lab explicitly.)

    async def configure_lab(
        self, name: str, *, skip_config_time_checks: bool = False
    ) -> Job:
        """POST /labs/{name}/configure — lab:configure. **202 + the running
        configure Job** (result: ConfigureResponse). Pushes config from the
        stored definition, then runs config-time suites unless skipped (the
        automatic run rides lab:configure, not lab:validate — deliberate).
        Pre-accept: 409 no definition; 409 job_in_flight. A push that
        couldn't run fails the job; one that ran-but-failed succeeds with
        result.status="config_failed"."""
        raise NotImplementedError

    async def destroy_lab(self, name: str, *, remove: bool = False) -> Job:
        """DELETE /labs/{name} — lab:destroy. **202 + the running destroy
        Job** (result: DestroyResponse).

        remove=False: tear down; record -> "destroyed" (redeployable, KEEPS
        its mgmt-subnet reservation so a redeploy reproduces the same
        environment). Requires the lab to be RUNNING — a synchronous 409 at
        submit, via a fast live-state pre-check.
        remove=True: also soft-delete the record and RELEASE its mgmt-subnet
        reservation; teardown best-effort, so a down lab is fine. The job
        stays pollable AFTER the soft-delete — job reads see soft-deleted
        labs, so the terminal state is always reachable.
        Pre-accept: 409 lab_not_running (remove=False); 409 job_in_flight."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — jobs (async operations, delta 12)
    # ------------------------------------------------------------------ #

    async def get_job(self, lab_name: str, job_id: UUID) -> JobDetail:
        """GET /labs/{lab_name}/jobs/{job_id} — lab:read. 404 hides both an
        unreadable lab and an unknown job id. Works on a soft-deleted lab
        (a destroy-with-remove job must stay pollable to its terminal
        state).

        The single-job read is the one carrying `steps` (delta 29) — what the
        operation did, growing while it runs and kept after it finishes.
        Polling this is how a caller follows progress; the listings below
        return plain `Job`."""
        raise NotImplementedError

    async def list_jobs(self, lab_name: str, *, limit: int = 20) -> list[Job]:
        """GET /labs/{lab_name}/jobs?limit= — lab:read, newest first. Recent
        history, not an audit log: finished jobs beyond the newest ~20 per
        lab are pruned (and a re-created lab name starts with an empty
        history — jobs don't leak across incarnations)."""
        raise NotImplementedError

    async def list_all_jobs(self, *, limit: int = 20) -> list[Job]:
        """PROPOSED (delta 15, APPROVED, not served yet) GET /jobs?limit= —
        recent jobs across every lab the caller may read, newest first (each
        `Job` names its `lab_name`). Any authenticated user; the per-lab
        filter is the same readable set `events` uses, so this never leaks a
        lab's existence. `limit` is 1-200 (422 outside).

        Jobs of REMOVED labs are excluded: a destroy-with-remove job drops
        out of this list when its lab record does, and its terminal state is
        read with `get_job`, which stays readable on a removed lab."""
        raise NotImplementedError

    async def wait_job(
        self,
        lab_name: str,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_interval: float = 2.0,
    ) -> JobDetail:
        """Poll `get_job` until the job is terminal; return the terminal Job —
        a `JobDetail`, so the step log of what just happened comes with it.
        Pure client-side convenience — no wire surface beyond the polling.

        Does NOT raise on a failed job — the caller inspects
        status/result/error (APPROVED: no raise-on-failure flag). Raises
        stdlib TimeoutError (APPROVED) when `timeout` (default: the
        client's `action_timeout`) elapses with the job still running —
        the job keeps running server-side; the caller can resume waiting.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — test suites
    # ------------------------------------------------------------------ #

    async def get_test_suites(self, name: str) -> TestSuitesResponse:
        """GET /labs/{name}/test-suites — lab:read."""
        raise NotImplementedError

    async def facts(self, name: str) -> LabFacts:
        """GET /labs/{name}/facts — lab:read. The per-node fact namespace
        suite templates render against (see LabFacts; delta 26:
        partitioned into the promised core + per-object ``_extras``).
        409 ``no_definition`` on a bare created record — no definition,
        no facts. Derived from the same dry `netlab create` that
        validates a PUT and persisted like the link table, so reads
        never pay the subprocess cost."""
        raise NotImplementedError

    async def put_test_suites(
        self, name: str, suites: dict[str, TestSuite]
    ) -> TestSuitesResponse:
        """PUT /labs/{name}/test-suites — lab:edit. Full replace; takes effect
        on the next run.

        PROPOSAL (delta 17, APPROVED): schema violations (two matchers,
        compare without parse, bad regex) stay 422 as today; Jinja templates
        are syntax-checked always and dry-rendered against the lab's node
        facts when a definition exists — either failure is 422
        ``template_invalid`` naming the suite/test/field."""
        raise NotImplementedError

    async def run_test_suite(self, name: str, suite: str) -> Job:
        """POST /labs/{name}/test-suites/{suite}/run — lab:validate. **202 +
        the running suite_run Job** (result: SuiteReport — its worst case is
        the sum of every test's `wait`, hence a job). Runs one suite (any
        stage); persists as its last run but NEVER moves the config-time
        gate. Pre-accept: 404 unknown suite; 409 job_in_flight."""
        raise NotImplementedError

    async def dry_run_test_case(
        self, name: str, node: str, run: TestCaseDraft
    ) -> TestCaseDryRunResult:
        """PROPOSED (delta 31) POST /labs/{name}/test-suites/dry-run —
        lab:validate. Run ONE unsaved case on ONE node and report what it
        did, including the parsed structure a `compare` must be written
        against.

        **Synchronous**, unlike run_test_suite. A suite run is 202 + a job
        because its worst case is the sum of every test's `wait`; a dry run
        has no `wait` at all (one exec, no convergence polling — the
        question is "what does this print, now", and polling would only
        make a wrong command take a minute to say so). Staying sync also
        keeps it usable WHILE a job holds the per-lab mutex, which is
        exactly delta 24's reasoning for batch runtime actions: an
        authoring aid that 409s because someone is deploying is not an aid.

        Writes NOTHING — no last_validation, no config-time gate, no job
        row. It is a question, not an operation.

        Permission is lab:validate, not lab:edit: authoring is lab:edit,
        but this EXECUTES on a node, which is the suite-run class. It grants
        nothing new — run_test_suite already runs arbitrary commands under
        the same permission; this aims it at a case that is not stored yet.

        409 no_definition on a bare record, 409 lab_not_running unless
        deployed, 422 unknown_node, and the case's own 422s (a `cli` case on
        a device with CatalogDevice.cli_mode False, a `textfsm` case where
        textfsm is False, compare/parse mismatch)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — custom config
    # ------------------------------------------------------------------ #

    async def get_custom_config(self, name: str) -> CustomConfigResponse:
        """GET /labs/{name}/custom-config — lab:read."""
        raise NotImplementedError

    async def put_custom_config(
        self, name: str, templates: list[ConfigTemplateSpec]
    ) -> CustomConfigResponse:
        """PUT /labs/{name}/custom-config — lab:edit. Full replace of the USER
        tier (delta 27). 409 ``builtin_template_shadowed`` if a name equals a
        built-in's; 422 on shape violations (duplicate names, duplicate scope
        keys, both device+node set, non-catalog device, materialized-filename
        collision within a template). Applies on the next configure/deploy."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — topology layout (delta 19)
    # ------------------------------------------------------------------ #

    async def get_layout(self, name: str) -> LabLayout:
        """PROPOSED (delta 19, APPROVED, not served yet) GET
        /labs/{name}/layout — lab:read.
        The shared manual arrangement; empty positions when none was ever
        saved. Deliberately NOT 409-gated on a definition (unlike links/
        facts): an empty layout is honest, not a lie — the layout is an
        independent presentational sub-resource."""
        raise NotImplementedError

    async def put_layout(
        self,
        name: str,
        positions: dict[str, LayoutPosition],
        # PROPOSAL (delta 20, APPROVED): None = {} for wire-compat ergonomics,
        # but the PUT replaces the WHOLE resource — a caller updating only
        # positions must resend the styles it wants kept.
        groups: dict[str, LayoutGroupStyle] | None = None,
    ) -> LabLayout:
        """PROPOSED (delta 19, APPROVED, not served yet) PUT
        /labs/{name}/layout — lab:edit.
        Full REPLACE of the whole layout resource — positions AND group
        styles ({} clears; no separate DELETE). lab:edit — not a new
        permission and not lab:read — because the shared layout is authoring:
        only the Build tab edits topology or arrangement (maintainer's call
        2026-08-03), so the read/operate-only canvases never write this. A
        plain fast 200 — no job."""
        raise NotImplementedError

    # stopped here

    # ------------------------------------------------------------------ #
    # Labs — runtime control & observability (live clab-api state)
    # ------------------------------------------------------------------ #

    async def lab_power(self, name: str, action: LabPowerAction) -> LabActionResponse:
        """POST /labs/{name}/{action} — lab:configure. pause/unpause fan out
        per node (see LabPowerAction QUIRK)."""
        raise NotImplementedError

    async def node_power(
        self, name: str, node: str, action: NodePowerAction
    ) -> LabActionResponse:
        """POST /labs/{name}/nodes/{node}/{action} — lab:configure."""
        raise NotImplementedError

    async def save_config(self, name: str) -> SaveConfigResponse:
        """POST /labs/{name}/save — lab:configure. containerlab save."""
        raise NotImplementedError

    async def node_logs(
        self, name: str, node: str, *, tail: int = 200
    ) -> NodeLogsResponse:
        """GET /labs/{name}/nodes/{node}/logs?tail= — lab:read. Container
        logs, not NOS syslog."""
        raise NotImplementedError

    async def interfaces(
        self, name: str, *, node: str | None = None
    ) -> list[NodeInterfaces]:
        """GET /labs/{name}/interfaces[?node=] — lab:read. See NodeInterfaces
        QUIRK (container-name keys)."""
        raise NotImplementedError

    async def links(self, name: str) -> LabLinks:
        """PROPOSED (delta 14 APPROVED, not served yet) GET /labs/{name}/links — the lab's
        logical link table with derived oper state. lab:read (404
        existence-hiding). 409 ``no_definition`` on a bare created record —
        an empty table would be indistinguishable from a definition with no
        links. Works on ANY authored lab: undeployed labs return the full
        table with every ``oper_state`` "unknown" and ``live=False``. The
        live merge is best-effort: an interface-inventory failure degrades to
        unknown states, never a 5xx."""
        raise NotImplementedError

    async def show_netem(self, name: str, node: str) -> list[NetemImpairment]:
        """GET /labs/{name}/nodes/{node}/netem — lab:read. Lists only the
        interfaces with ACTIVE impairment (implementation finding: tc/clab
        omit unshaped interfaces) — a cleared interface is absent, not
        zeroed."""
        raise NotImplementedError

    async def set_netem(self, name: str, action: NetemAction) -> LabActionResponse:
        """POST /labs/{name}/nodes/{node}/netem — lab:configure. REPLACE
        semantics (APPROVED): the call states the interface's COMPLETE desired
        impairment — an omitted/None dimension is cleared, and a call with no
        impairments clears everything (subsuming the removed /netem/reset
        endpoint). jitter requires delay; loss/corruption 0-100 %, rate kbit/s.

        PROPOSED (delta 24, APPROVED) signature unification: takes THE impairment
        spelling (NetemAction) instead of five kwargs — the same object
        applies standalone here or batched in apply_actions. The wire is
        UNCHANGED: ``action.node`` becomes the path segment, the rest the
        body. Standalone failure stays an HTTP error (the envelope), NOT a
        report — the fail-loudly semantics a batch item deliberately trades
        away.

        Wire today: "50ms"-style duration strings, omitted = unchanged, an
        at-least-one-impairment rule, and a separate POST .../netem/reset."""
        raise NotImplementedError

    async def apply_actions(
        self, name: str, actions: list[NetemAction | PowerAction]
    ) -> RuntimeActionsReport:
        """PROPOSED (delta 24, APPROVED) POST /labs/{name}/actions — lab:configure.
        Many netem sets/clears + node power events in ONE request, executed
        SEQUENTIALLY in list order, continuing past failures; the report is
        index-aligned per-item outcomes. NOT a transaction: no rollback, no
        isolation against concurrent single-verb calls. ≤64 items. 422 up
        front (nothing executed) on any structurally invalid item; live
        failures (unknown node, netem on a stopped container) land on the
        item's result, never the HTTP status. Sync — a fast staging verb,
        usable while a job runs, exactly like the single verbs it mirrors."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Labs — grants & ownership (lab:grant on the lab)
    # ------------------------------------------------------------------ #

    async def list_grants(self, name: str) -> list[Grant]:
        """GET /labs/{name}/grants."""
        raise NotImplementedError

    async def create_grant(
        self,
        name: str,
        principal_type: Literal["user", "group"],
        principal_id: UUID,
        role: str,
    ) -> Grant:
        """POST /labs/{name}/grants — 201. 422 unless the role is lab-bindable;
        403 anti-escalation (role's permissions must be ⊆ the caller's on this
        lab). Duplicates are idempotent."""
        raise NotImplementedError

    async def delete_grant(self, name: str, binding_id: UUID) -> None:
        """DELETE /labs/{name}/grants/{binding_id} — 204. 404 if absent or on
        another lab."""
        raise NotImplementedError

    async def transfer_owner(self, name: str, user_id: UUID) -> LabOwner:
        """PUT /labs/{name}/owner. Requires owner-EQUIVALENCE (the full owner
        permission set on the lab), else 403. 404 unknown user.

        Returns `LabOwner` (APPROVED — wire today: a fake grant shape with the
        lab's UUID as `id` and the non-catalog role "owner")."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Streams
    # ------------------------------------------------------------------ #

    # AsyncGenerator, not AsyncIterator (implementation finding): callers that
    # abandon the stream early need a deterministic close (aclose /
    # contextlib.aclosing) so the underlying connection is released.
    def events(self) -> AsyncGenerator[LabEvent | JobEvent, None]:
        """GET /events (SSE) — any authenticated user; filtered to readable
        labs (set refreshes ~30 s, so a mid-stream grant lags up to that).
        Iterate with `async for`; keepalives are consumed, not yielded.

        PROPOSED (delta 16, APPROVED) two payloads, discriminated by the SSE
        event NAME and yielded as a union (match with `isinstance`):

          ``lab`` -> LabEvent   container lifecycle, relayed from
                                containerlab. A configure or suite-run job
                                touches no container, so it emits none.
          ``job`` -> JobEvent   a job was submitted or reached a terminal
                                state — the signal that replaces polling.

        NOT a durable log: the stream has no replay (no Last-Event-ID), so a
        reconnect silently misses whatever happened while it was down. A
        consumer that must not miss a completion still reads the record —
        `wait_job` polls for exactly this reason.

        (wire today: one unnamed event carrying the LabEvent payload;
        completion is discovered by polling only.)"""
        raise NotImplementedError

    def terminal(
        self,
        name: str,
        node: str,
        *,
        protocol: Literal["ssh", "shell"] = "ssh",
        cols: int = 80,
        rows: int = 24,
        ssh_username: str | None = None,
    ) -> AbstractAsyncContextManager[TerminalSession]:
        """Open the node terminal WS (lab:terminal; see TerminalSession) —
        `async with client.terminal(...) as term`. `ssh_username`: clab-api
        defaults to "admin" (wrong for e.g. VyOS); ignored for
        protocol="shell"."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Appendix — shipped catalogs (APPROVED: pinned as versioned contract facts)
# --------------------------------------------------------------------------- #
# The role catalog and builtin-template library are code-defined in the
# backend; third-party clients must still QUERY them (GET /roles, GET
# /labs/{name}/custom-config) rather than hardcode. They are enumerated here
# so a catalog change is, by definition, a contract change (and a black-box
# suite change) — not a silent drift.
#
# Permissions — lab-scoped (bindable per-lab or globally):
#   lab:read, lab:edit, lab:configure, lab:validate, lab:terminal,
#   lab:destroy, lab:grant
# Permissions — global-only:
#   lab:create, user:manage, group:manage,
#   template:manage  (delta 21, APPROVED — authors the library's user tier:
#                     the lab publish toggle + node-template CRUD; READS
#                     need no permission)
#
# Role catalog (scope — permissions):
#   admin           global — every permission
#   global_operator global — lab:create + all seven lab-scoped
#                            + template:manage (delta 21, APPROVED: operators
#                            author labs, so curating starting points fits)
#   global_viewer   global — lab:read
#   creator         global — lab:create
#   user            global — none (the baseline role every new user gets)
#   lab_owner       lab    — all seven lab-scoped (also the owner-implicit set)
#   lab_manager     lab    — all lab-scoped EXCEPT lab:destroy
#   lab_operator    lab    — lab:read, lab:configure, lab:validate, lab:terminal
#   lab_viewer      lab    — lab:read
#
# Shipped builtin custom-config templates: mpls_te, ip_sla. Both carry ONE
# device variant labeled `ios` (delta 27's record shape), so since IOL's
# withdrawal (2026-08-05) neither applies to any catalogued device — clients
# grey them with the reason rather than offering them; they remain because
# they ARE this library and the mechanism is device-agnostic (netlab picks
# the variant matching a node's declared device).
#
# Shipped builtin library templates (delta 21, APPROVED) — the repo examples,
# all in the NETWORK collection: example-mpls-l3vpn (VyOS),
# example-campus-lan. (example-mpls-l3vpn-iol was seeded with delta 21 and
# REMOVED 2026-08-05 with the platform — a builtin is a first-class "start
# from" offer, so keeping one for an unsupported device would keep promising
# it.) The `example-` prefix is
# deliberate (revised at first use, 2026-08-04): a builtin name reserves
# itself against lab publication, and the BARE example names are exactly what
# real labs deployed from these examples get called — unprefixed builtins
# made those labs unpublishable. The NODE collection's builtin tier starts
# EMPTY: bare devices are the catalog's job; a shipped preconfigured motif
# (e.g. a PE-router preset) must earn its way in later.
#
# Import-capable devices (delta 22, APPROVED): vyos, iol — the PARSER set,
# which since 2026-08-05 is no longer a subset of the catalog (iol kept its
# parser and lost its catalog entry, so `config_import` cannot advertise it).
# The catalog's config_import flag is the queryable form; widening requires a
# per-device parser, so it is a code change and therefore a contract change
# here.

# --------------------------------------------------------------------------- #
# Appendix — pinned fact namespace (delta 26, APPROVED)
# --------------------------------------------------------------------------- #
# The promised core of the per-node fact namespace (LabFacts / template
# rendering). A path listed here is stable Twinlab contract: it exists with
# this shape whenever its feature exists, across netlab upgrades (Twinlab
# adapts if netlab moves the source key; a drift-guard test over the examples'
# real netlab output enforces it). EVERY key not listed rides under the
# containing object's `_extras`, verbatim and netlab-shaped, with NO promises
# — including netlab-internal `_`-prefixed keys. `?` = present when the
# feature exists; ABSENCE IS MEANINGFUL (a role:host node with a router_id
# but no `loopback` is a fact about the lab, not a gap in the data).
# Evidence + worked example: docs/fact-namespace.md.
#
# Node (each value of LabFacts.nodes):
#   name: str          — short node name (the dict key, repeated)
#   id: int            — netlab node id
#   device: str        — the definition's device (device-keyed case dispatch)
#   hostname: str      — container name (clab-<lab>-<node>)
#   role: str?         — absent = router (netlab's default)
#   af: {ipv4?: bool, ipv6?: bool}
#   module: [str]      — enabled netlab modules
#   mgmt: {ifname: str, ipv4?: str, ipv6?: str, mac?: str}   — bare IPs
#   loopback?: {ifname: str, ipv4?: str, ipv6?: str}          — CIDR form
#   interfaces: [ ... ]                                       — see below
#   ospf? / bgp? / ldp? / vrfs?                               — see below
#   _extras?: { ... }  — everything else (observed on 26.07: box, clab, mtu,
#                        router_id, mpls, dhcp, routing, _daemon*,
#                        _node_config, netlab_ansible_skip_module)
#
# interfaces[i]:
#   ifname: str        — NOS-side name (CHR: ether2; the container-side name
#                        is the link table's `interface` — deliberately NOT
#                        duplicated here)
#   ifindex: int
#   type: str          — presence pinned, vocabulary netlab's (passthrough)
#   linkindex?: int    — joins the link table's `index`
#   name?: str         — the link's name
#   ipv4?: str / ipv6?: str                                   — CIDR form
#   neighbors: [{node: str, ifname: str, ipv4?: str, ipv6?: str, _extras?}]
#   ospf?: {area: str, _extras?}   — per-interface overlay
#   _extras?: { ... }  — observed: mtu, bridge, gateway, virtual_interface,
#                        clab
#
# Protocol subtrees (pinned for the proven module set; a subtree exists iff
# its module is on):
#   ospf: {router_id: str, area: str, _extras?}
#   bgp:  {as: int, router_id: str,
#          neighbors: [{name: str, as: int, type: str, ipv4?: str,
#                       vpnv4?: str, _extras?}],
#          _extras?}
#   ldp:  {router_id: str, _extras?}
#   vrfs: {<vrf>: {rd: str, import: [str], export: [str],
#                  loopback_address?: {ipv4?: str, ipv6?: str, _extras?},
#                  _extras?}}
#
# Template filter: `address` — CIDR → bare address ("10.0.0.5/32" →
# "10.0.0.5"). Part of the namespace contract since delta 17.
#
# Partition rules (contract, all tested): per-object `_extras`, omitted when
# empty; lists are never index-mirrored (a list entry is an object with its
# own `_extras`); below an unpinned key content is verbatim (the partition
# never descends into `_extras`); reassembly reproduces netlab's raw dict;
# a netlab-supplied `_extras` key lands at `_extras._extras` — ours wins the
# position.

# NOS platform sweep — analysis inputs (ROADMAP item 17)

Three analyses produced 2026-08-04 as the opening of item 17's three parallel strands. They are
decision *inputs*: options are enumerated, and each open point needs a maintainer call before
implementation.

- **`nos-availability.md`** (strand 17.1) — the acquisition matrix: which NOSes we can obtain,
  how, license terms for lab use, vrnetlab/KVM requirements, footprints, config-transport
  diversity, multi-version availability, and a three-wave acquisition order.
- **`netlab-up-gaps.md`** (strand 17.2) — the full `netlab up`/`netlab down` parity audit
  against netlab 26.7: seven gaps (the original three plus the widened inline-deploy bind loss,
  CLI/plugin hooks, OVS bridge type, topology `message`), each with options.
- **`builder-coverage-gaps.md`** (strand 17.3) — the complete tier-classified inventory of
  netlab topology syntax vs the Build tab's Visual mode: 17 structural gates (9 promotable),
  the typed surface, and per-gap promotion assessments.

## Decision log (maintainer, 2026-08-04)

- **Gap 1 (`tc:`)** — honor it, with ONE unified application method for baseline (deploy-time
  `tc:`) and runtime: the existing clab-api netem path — no second raw-`tc` channel, minimize
  hand-rolled code. Consequence: `tc.duplicate`/`tc.reorder` are rejected loudly at PUT (they
  don't exist on that path). Baseline semantics (reapply on node restart; clear reverts to
  baseline) to be designed as a contract delta before implementation; settle once with 16.5's
  schedules.
- **Gap 2 (`tools:`)** — reject at PUT; reconsider later. **SHIPPED 2026-08-04** (422
  `unsupported_directive`, per-key reasons in extras; dotted and nested spellings).
- **Gap 3 (image pre-flight)** — reject only when the deploy is impossible: first job step
  checks the runner's image list; absent + catalog-marked local-only → fail fast with a
  friendly `image_missing` error naming the image and how to obtain it; absent + pullable →
  proceed with a job warning; runner unreachable → proceed (check must never add a failure
  mode). Catalog gains per-device pullability from the sweep. **SHIPPED 2026-08-04**
  (`CatalogDeviceSpec.local_only`, `DeployResponse.warnings`; devices outside the catalog
  count as pullable).
- **Gap 4 (bind loss)** — host-shared directory + bind REWRITE (not strip): backend
  materializes `node_files/` on a host-shared dir and rewrites relative binds to absolute
  paths, preserving netlab semantics incl. boot-time files. Design rundown reviewed 2026-08-04;
  same-path invariant (host path == container path in backend and clab-api) is the key
  mechanism. **SHIPPED 2026-08-04** (`LAB_FILES_DIR`, required in compose, optional in code —
  unset falls back to stripping; a relative `startup-config` is rewritten by the same rule,
  closing that latent hole; destroy removes the regenerable tree). Verified live: blackbox
  ping-by-name on the linux lab (137/137 green — note: netlab's `/etc/hosts` maps names to
  LINK addresses, so name-based reachability needs config push) and FRR end-to-end (deploy,
  daemons file via bind, sh-mode config push, OSPF Full) — FRR stays outside the supported
  set until the sweep admits it.
- **Gap 5 (up/down shell hooks)** — reject the keys and document the security rationale.
  **SHIPPED 2026-08-04** (same `unsupported_directive` batch as gap 2).
- **Gap 6 (OVS bridge type)** — reject at PUT for now; REVISIT later if L2-heavy testing (the
  sweep's switch platforms) surfaces a real need — supporting it means host OVS daemons +
  ovs-vsctl in hostprep. **SHIPPED 2026-08-04** (same batch; only the `ovs-bridge` value
  rejects — an explicit `bridge` is what hostprep does anyway).
- **Gap 7 (topology `message`)** — surface it (LabDetail / deploy-job result). **SHIPPED
  2026-08-04** (`LabDetail.message` + an "About this lab" card on the frontend Overview).
- **Gap 1 (`tc:`) status** — contract **delta 25 SKETCHED 2026-08-04, then DEFERRED to the
  END of item 17** (maintainer wants to re-analyze before it proceeds; the sketch stands as
  a starting point, not an approved design):
  baseline applied via the one netem executor at deploy (fails loudly), reapplied by power
  verbs after restart, runtime sets override, clear reverts to baseline,
  `tc.duplicate`/`tc.reorder` reject at PUT; rate-unit mapping is a flagged probe item.
- **Builder coverage (17.3)** — Tier A batch AGREED: hyphenated names, nodes-as-dict-list,
  list-form dict members, dict-of-lists links (typed listName, lossless), link groups
  (expand-on-parse with notice), **self-links (SUPPORT — maintainer overrode the defer lean)**,
  components minimum step (endpoint prefix rule + device-blocker waiver), hierarchical group
  members, 16-char name cap. Tier B promotions (module presence ×14, subkey splits, field
  promotions, vlans, …) are DEFERRED to their own review after the sweep work, before v1.0.
  **SHIPPED 2026-08-04** — all nine, verified by a 36-check round-trip harness, the five
  stored definitions on the running stack, and netlab 26.07 itself (every emitted form
  creates cleanly; the builder's link-group expansion is byte-identical to netlab's own).
  Live finding recorded: both ends of a self-link draw the SAME pool address, so netlab
  refuses one unless the link is `prefix: false` or each end carries an `ipv4` — the link
  inspector warns, the server's dry create stays the judge.
- **Strand 17.1 acquisition waves** — agreed as proposed.

Gaps 2–7 verified live 2026-08-04: blackbox **140/140** with the `deploy` marker.

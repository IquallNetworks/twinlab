# Twinlab operator guide

How to run Twinlab: install it, build a lab, deploy it, operate it, and work out
what happened when something fails.

This guide assumes you know networking. It does not assume you know netlab or
containerlab. Where Twinlab exposes either of them, the page says so and links
out.

If you automate rather than click, the API has its own documentation.
`docs/twinlab_client_shape.py` is the contract, and `client/README.md` covers
the Python client.

## Pages

1. **[Install](01-install.md)** — host requirements, the stack, node images,
   first sign-in
2. **[Your first lab](02-first-lab.md)** — create, build, deploy and check,
   in the UI
3. **[The Build tab](03-build-tab.md)** — every canvas control and inspector
   setting, and the definition key each one writes
4. **[Operating a lab](04-operating.md)** — power, logs, terminals, links,
   impairment, drift, jobs
5. **[Test suites](05-test-suites.md)** — writing assertions that run against a
   deployed lab
6. **[Real configurations in](06-config-import.md)** — config import, templates,
   custom config
7. **[Access](07-access.md)** — users, roles, grants, API keys, SSH to nodes
8. **[When something fails](08-troubleshooting.md)** — indexed by the error code
   Twinlab gives you
9. **[Definition reference](09-definition-reference.md)** — what Twinlab
   accepts, refuses and writes into your YAML

Read 1 and 2 in order. The rest stand alone.

The design records under `docs/` in the repository go deeper than a guide
should, if you need to know why something works the way it does.

"""netlab config-push runner.

Regenerates a lab's inventory with `netlab create` (deterministic from the
definition, so it matches whatever clab-api deployed for the same stable name)
and then pushes device config with `netlab initial`. netlab drives Ansible over
the `docker` connection (docker exec into `clab-<lab>-<node>` by name), so this
runner owns netlab + ansible + the docker socket, and the backend stays clean.

The subprocess calls are the boundary — the one place `try`/`except` lives; every
outcome is returned as a typed value.
"""

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

_CLAB_OUTPUT = "clab.yml"
# Custom-config template paths the backend ships alongside a definition. netlab
# resolves a `config: [name]` attribute to `name.j2` (or `name/<device>.j2`) in
# its search path, which includes the workdir (`.`), so we drop these files there
# before `netlab create`. The contract mirrors the backend's _TemplatePath: a
# relative, traversal-free path ending in `.j2`.
_TEMPLATE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*\.j2$")
_CREATE_TIMEOUT_SECONDS = 120
# Ansible push execs into every node; a few nodes settle in well under a minute,
# but keep headroom for larger labs.
_INITIAL_TIMEOUT_SECONDS = 600
# One `netlab exec` (a single show command over ssh/docker) is quick; cap it so a
# hung connection can't stall a validation poll.
_EXEC_TIMEOUT_SECONDS = 60
# `netlab initial --ready` polls each node's SSH/console until the NOS has booted;
# netlab's default budget is 20 retries x 5s = 100s per node (concurrent), so give
# it headroom for a slow IOL boot.
_READY_TIMEOUT_SECONDS = 200
# Cached netlab inventories for validation execs, one workdir per lab name so a
# suite's many checks don't re-run `netlab create` each time.
_EXEC_CACHE_ROOT = Path("/tmp/netlab-exec-cache")
# netlab/ssh connection chatter to drop from captured command output so the pure
# matcher sees only the device's stdout.
_EXEC_NOISE = re.compile(
    r"^(Connecting to .*|Warning: Permanently added .*|Connection to .* closed by remote host\.)$"
)

# Ansible's PLAY RECAP is a stable, version-independent per-host summary:
#   r1  : ok=7  changed=5  unreachable=0  failed=0  skipped=1 ...
# inventory_hostname is netlab's short node name (r1), which is what we report.
_RECAP_LINE = re.compile(
    r"^(?P<host>\S+)\s*:\s*"
    r"ok=(?P<ok>\d+)\s+changed=(?P<changed>\d+)\s+"
    r"unreachable=(?P<unreachable>\d+)\s+failed=(?P<failed>\d+)"
)


@dataclass(frozen=True, slots=True)
class NodeResult:
    node: str
    ok: int
    changed: int
    unreachable: int
    failed: int

    @property
    def succeeded(self) -> bool:
        return self.failed == 0 and self.unreachable == 0


@dataclass(frozen=True, slots=True)
class ConfigureOutcome:
    lab_name: str
    succeeded: bool
    nodes: list[NodeResult]
    output: str


@dataclass(frozen=True, slots=True)
class RunnerError:
    stage: str  # "netlab-create" | "netlab-initial" | "internal"
    message: str
    output: str = ""


def parse_recap(output: str) -> list[NodeResult]:
    """Extract per-host results from Ansible's PLAY RECAP section."""
    results: list[NodeResult] = []
    in_recap = False
    for line in output.splitlines():
        if line.startswith("PLAY RECAP"):
            in_recap = True
            continue
        if not in_recap:
            continue
        match = _RECAP_LINE.match(line.strip())
        if match:
            results.append(
                NodeResult(
                    node=match["host"],
                    ok=int(match["ok"]),
                    changed=int(match["changed"]),
                    unreachable=int(match["unreachable"]),
                    failed=int(match["failed"]),
                )
            )
    return results


def aggregate(rows: list[NodeResult]) -> list[NodeResult]:
    """netlab runs several plays, so a node appears in multiple PLAY RECAPs;
    collapse them into one total per node (first-seen order preserved)."""
    totals: dict[str, NodeResult] = {}
    for row in rows:
        prev = totals.get(row.node)
        totals[row.node] = (
            row
            if prev is None
            else NodeResult(
                node=row.node,
                ok=prev.ok + row.ok,
                changed=prev.changed + row.changed,
                unreachable=prev.unreachable + row.unreachable,
                failed=prev.failed + row.failed,
            )
        )
    return list(totals.values())


def _lab_name(workdir: Path) -> str | None:
    try:
        parsed: Any = yaml.safe_load((workdir / _CLAB_OUTPUT).read_text())
    except (OSError, yaml.YAMLError):
        return None
    if isinstance(parsed, dict):
        name = cast("dict[str, object]", parsed).get("name")
        if isinstance(name, str):
            return name
    return None


def _run(argv: list[str], workdir: Path, timeout: int) -> subprocess.CompletedProcess[str] | str:
    """Run a netlab subcommand; return the completed process, or an error string
    if it could not be launched. HOME is left at the real user home: `netlab
    initial` drives Ansible, whose `community.docker` connection plugin lives under
    ~/.ansible — overriding HOME hides it. Concurrent runs are instead prevented by
    serializing configure at the HTTP layer (see app.py), so netlab's shared
    ~/.netlab state is never touched by two invocations at once."""
    try:
        return subprocess.run(
            argv, cwd=workdir, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run {' '.join(argv)}: {exc}"


def template_path_error(relpath: str) -> str | None:
    """Reject an unsafe custom-config template path, or None if it is safe. Safe
    means relative, traversal-free, `.j2`, and (once joined to the workdir) still
    inside it — the untrusted-input check for the fileset the backend ships."""
    if not _TEMPLATE_PATH.match(relpath) or ".." in Path(relpath).parts:
        return f"unsafe template path: {relpath!r}"
    root = Path("/__wd__")
    if not (root / relpath).resolve().is_relative_to(root):
        return f"template path escapes workdir: {relpath!r}"
    return None


def _write_templates(wd: Path, templates: dict[str, str]) -> RunnerError | None:
    """Write custom-config templates into the workdir so `netlab initial` can
    render whichever ones the definition's `config:` references. This is the
    untrusted-input boundary, so a bad path is a typed error, not an exception."""
    for relpath, content in templates.items():
        error = template_path_error(relpath)
        if error is not None:
            return RunnerError("internal", error)
        target = wd / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_text(content)
    return None


def configure(definition: str, templates: dict[str, str]) -> ConfigureOutcome | RunnerError:
    """Render the lab and push its config. `definition` must carry a stable
    `name:` so the regenerated inventory targets the deployed containers.
    `templates` is the custom-config fileset (built-in + user) — written into the
    workdir before create so `netlab initial` deploys the referenced ones."""
    with tempfile.TemporaryDirectory() as workdir:
        wd = Path(workdir)
        _ = (wd / "topology.yml").write_text(definition)
        written = _write_templates(wd, templates)
        if written is not None:
            return written

        created = _run(["netlab", "create", "topology.yml"], wd, _CREATE_TIMEOUT_SECONDS)
        if isinstance(created, str):
            return RunnerError("internal", created)
        if created.returncode != 0:
            return RunnerError("netlab-create", "netlab create failed", created.stderr)

        name = _lab_name(wd)
        if name is None:
            return RunnerError("netlab-create", f"no lab name in {_CLAB_OUTPUT}", created.stderr)

        initial = _run(["netlab", "initial"], wd, _INITIAL_TIMEOUT_SECONDS)
        if isinstance(initial, str):
            return RunnerError("internal", initial)

        combined = initial.stdout + initial.stderr
        nodes = aggregate(parse_recap(combined))
        succeeded = initial.returncode == 0 and all(node.succeeded for node in nodes)
        return ConfigureOutcome(lab_name=name, succeeded=succeeded, nodes=nodes, output=combined)


@dataclass(frozen=True, slots=True)
class ExecOutcome:
    node: str
    stdout: str


def _definition_name(definition: str) -> str | None:
    """The definition's stable `name:` (injected by the backend). Keys the exec
    inventory cache and must match the deployed lab."""
    try:
        parsed: Any = yaml.safe_load(definition)
    except yaml.YAMLError:
        return None
    if isinstance(parsed, dict):
        name = cast("dict[str, object]", parsed).get("name")
        if isinstance(name, str):
            return name
    return None


def _clean_exec_output(text: str) -> str:
    """Strip netlab/ssh connection chatter so only device stdout remains."""
    return "\n".join(line for line in text.splitlines() if not _EXEC_NOISE.match(line.strip()))


def _ensure_inventory(definition: str, name: str, templates: dict[str, str]) -> Path | RunnerError:
    """Return a workdir holding this lab's netlab inventory, regenerating it only
    when absent or when the definition or its templates changed (hash-stamped).
    Cached per lab so a suite's many validation execs don't each pay for `netlab
    create`. The custom-config `templates` must be written before create because
    netlab validates that every `config:` reference exists — a definition using
    custom config fails create without them. Callers serialize this (netlab create
    races on ~/.netlab); see app.py."""
    workdir = _EXEC_CACHE_ROOT / name
    # Templates are part of the cache key: a built-in/user template change must
    # regenerate the inventory (its create validation depends on them).
    keyed = definition + "\0" + json.dumps(templates, sort_keys=True)
    digest = hashlib.sha256(keyed.encode()).hexdigest()
    stamp = workdir / ".defhash"
    if stamp.is_file() and stamp.read_text() == digest and (workdir / _CLAB_OUTPUT).is_file():
        return workdir
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    _ = (workdir / "topology.yml").write_text(definition)
    written = _write_templates(workdir, templates)
    if written is not None:
        return written
    created = _run(["netlab", "create", "topology.yml"], workdir, _CREATE_TIMEOUT_SECONDS)
    if isinstance(created, str):
        return RunnerError("internal", created)
    if created.returncode != 0:
        return RunnerError("netlab-create", "netlab create failed", created.stderr)
    _ = stamp.write_text(digest)
    return workdir


@dataclass(frozen=True, slots=True)
class ReadyOutcome:
    ready: bool  # True on success; a failure is a RunnerError, not ready=False


def wait_ready(definition: str, templates: dict[str, str]) -> ReadyOutcome | RunnerError:
    """Wait for every node to become ready (its NOS booted and accepting SSH/
    console) via `netlab initial --ready` — a readiness poll, no config push. Used
    on the deploy path so a lab is reported done only once its devices actually
    respond (IOL/IOS keeps booting ~60-90s after the container is up). Needs the
    inventory, and the custom-config templates the definition's `config:` may
    reference (netlab create validates them). `definition` must carry the stable
    `name:`."""
    name = _definition_name(definition)
    if name is None:
        return RunnerError("internal", "definition has no name")
    workdir = _ensure_inventory(definition, name, templates)
    if isinstance(workdir, RunnerError):
        return workdir
    result = _run(["netlab", "initial", "--ready"], workdir, _READY_TIMEOUT_SECONDS)
    if isinstance(result, str):
        return RunnerError("internal", result)
    if result.returncode != 0:
        # netlab exhausted its retry budget: a node never came up.
        return RunnerError(
            "netlab-ready", "devices did not become ready", result.stdout + result.stderr
        )
    return ReadyOutcome(ready=True)


def exec_command(
    definition: str, node: str, command: str, templates: dict[str, str]
) -> ExecOutcome | RunnerError:
    """Run one operational `command` on `node` via `netlab exec`, which picks the
    per-NOS transport (docker exec for VyOS/FRR, ssh for Cisco/Nokia/…) from the
    netlab inventory — so this stays NOS-agnostic. `definition` must carry the
    stable `name:`; `templates` is the custom-config fileset the definition may
    reference (needed for the inventory's `netlab create`). Returns the command's
    stdout (connection chatter stripped)."""
    name = _definition_name(definition)
    if name is None:
        return RunnerError("internal", "definition has no name")
    workdir = _ensure_inventory(definition, name, templates)
    if isinstance(workdir, RunnerError):
        return workdir
    argv = ["netlab", "exec", node, *shlex.split(command)]
    result = _run(argv, workdir, _EXEC_TIMEOUT_SECONDS)
    if isinstance(result, str):
        return RunnerError("internal", result)
    if result.returncode != 0:
        # netlab exec couldn't reach or run on the node (e.g. node down).
        message = (result.stderr or result.stdout or "netlab exec failed").strip()
        return RunnerError("netlab-exec", message)
    return ExecOutcome(node=node, stdout=_clean_exec_output(result.stdout))

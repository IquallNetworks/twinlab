"""netlab config-push runner.

Regenerates a lab's inventory with `netlab create` (deterministic from the
definition, so it matches whatever clab-api deployed for the same stable name)
and then pushes device config with `netlab initial`. netlab drives Ansible over
the `docker` connection (docker exec into `clab-<lab>-<node>` by name), so this
runner owns netlab + ansible + the docker socket, and the backend stays clean.

The subprocess calls are the boundary — the one place `try`/`except` lives; every
outcome is returned as a typed value.
"""

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

_CLAB_OUTPUT = "clab.yml"
_CREATE_TIMEOUT_SECONDS = 120
# Ansible push execs into every node; a few nodes settle in well under a minute,
# but keep headroom for larger labs.
_INITIAL_TIMEOUT_SECONDS = 600

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


def configure(definition: str) -> ConfigureOutcome | RunnerError:
    """Render the lab and push its config. `definition` must carry a stable
    `name:` so the regenerated inventory targets the deployed containers."""
    with tempfile.TemporaryDirectory() as workdir:
        wd = Path(workdir)
        _ = (wd / "topology.yml").write_text(definition)

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

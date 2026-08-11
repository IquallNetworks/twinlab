"""netlab config-push runner.

Regenerates a lab's inventory with `netlab create` (deterministic from the
definition, so it matches whatever clab-api deployed for the same stable name)
and then pushes device config with `netlab initial`. netlab drives Ansible over
the `docker` connection (docker exec into `clab-<lab>-<node>` by name), so this
runner owns netlab + ansible + the docker socket, and the backend stays clean.

The subprocess calls are the boundary — the one place `try`/`except` lives; every
outcome is returned as a typed value.
"""

import contextlib
import hashlib
import json
import os
import pty
import re
import select
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoBaseException

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
# `docker image ls` is a local daemon query; generous headroom for a busy host.
_IMAGES_TIMEOUT_SECONDS = 30
# `netlab initial --ready` polls each node's SSH/console until the NOS has booted.
# netlab bounds that itself: each node gets `netlab_check_retries *
# netlab_check_delay` seconds of wall clock (default 20 x 5 = 100s) and the nodes
# are polled CONCURRENTLY, so the command's own runtime is the LARGEST per-node
# budget, not their sum. Devices declare their own: routeros7 250s, exos 200s,
# junos 300s, iosxr 600s — the biggest netlab 26.07 ships. This timeout is only a
# backstop against a hung subprocess and must stay well ABOVE those, or it
# silently truncates a wait netlab was willing to make (a 200s cap turned exos's
# 200s budget into a coin flip it always lost).
_READY_TIMEOUT_SECONDS = 900
# Cached netlab inventories for validation execs, one workdir per lab name so a
# suite's many checks don't re-run `netlab create` each time.
_EXEC_CACHE_ROOT = Path("/tmp/netlab-exec-cache")
# How long to let an interactive login shell settle before we type at it: long
# enough for a VyOS op-mode prompt, short enough not to pad every such exec.
_PTY_SETTLE_SECONDS = 1.5
# Grace for the login shell to act on our `exit` before the process is killed.
_PTY_EXIT_SECONDS = 3.0
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


@dataclass(frozen=True, slots=True)
class ImagesOutcome:
    images: list[str]


def parse_image_lines(text: str) -> list[str]:
    """`docker image ls --format '{{.Repository}}:{{.Tag}}'` output → repo:tag
    names. Dangling/untagged entries (`<none>` on either side) are dropped —
    nothing can deploy from them."""
    return [
        line for line in (raw.strip() for raw in text.splitlines()) if line and "<none>" not in line
    ]


def list_images() -> ImagesOutcome | RunnerError:
    """The repo:tag names present on the host Docker daemon (via the mounted
    socket). The runner only reports; matching a device's default image against
    this list is the backend's policy (delta 18)."""
    result = _run(
        ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
        Path("/"),
        _IMAGES_TIMEOUT_SECONDS,
    )
    if isinstance(result, str):
        return RunnerError(stage="docker-images", message=result)
    if result.returncode != 0:
        return RunnerError(
            stage="docker-images",
            message=f"docker image ls exited {result.returncode}",
            output=result.stdout + result.stderr,
        )
    return ImagesOutcome(images=parse_image_lines(result.stdout))


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


def _reset_known_hosts() -> None:
    """Re-point ~/.ssh/known_hosts at /dev/null before every config push.

    The Dockerfile establishes the symlink at build time, but Ansible's libssh
    connection plugin records accepted host keys via write-temp-then-RENAME —
    which silently replaces the symlink with a real file. Lab nodes get a new
    host key on every (re)deploy, and libssh hard-fails a MISMATCH ("host key
    mismatch for <ip>") even with host-key checking off, so a resurrected file
    breaks the next configure after any redeploy (found live 2026-08-03). A
    per-run reset makes the build-time fix self-healing. Best-effort: if the
    filesystem refuses, the push proceeds and fails with the explicit mismatch
    error instead."""
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    try:
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        if known_hosts.is_symlink():
            return
        known_hosts.unlink(missing_ok=True)
        known_hosts.symlink_to("/dev/null")
    except OSError:
        return


def configure(definition: str, templates: dict[str, str]) -> ConfigureOutcome | RunnerError:
    """Render the lab and push its config. `definition` must carry a stable
    `name:` so the regenerated inventory targets the deployed containers.
    `templates` is the custom-config fileset (built-in + user) — written into the
    workdir before create so `netlab initial` deploys the referenced ones."""
    _reset_known_hosts()
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
    respond (a VM-in-container NOS like CHR keeps booting long after the
    container itself is up). Needs the
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


# The Ansible connections that mean "this node is reached over SSH" — where a
# one-shot exec channel truncates timed commands and the interactive path
# applies. Everything else (docker, …) already streams complete output.
_SSH_CONNECTIONS = frozenset({"network_cli", "paramiko", "ssh"})
# ansible_network_os -> netmiko device_type, for the supported NOS set. An
# absent entry is a clean typed error below, never a wrong driver — so this
# tracks the catalog: `ios` left with Cisco IOL (2026-08-05, CML licensing),
# `routeros` arrived because CHR is a network_cli device and interactive cases
# therefore apply to it.
_NETMIKO_DEVICE_TYPES = {"routeros": "mikrotik_routeros", "vyos": "vyos"}


def _host_vars(workdir: Path, node: str) -> dict[str, object] | RunnerError:
    """The node's fully-resolved inventory vars (`ansible-inventory --host`) —
    connection kind, mgmt address, credentials — from the same inventory
    `netlab exec` uses, so both paths always agree on how to reach a node."""
    result = _run(["ansible-inventory", "--host", node], workdir, 30)
    if isinstance(result, str):
        return RunnerError("internal", result)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ansible-inventory failed").strip()
        return RunnerError("netlab-exec", f"unknown node {node!r}: {message}")
    try:
        parsed: Any = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return RunnerError("internal", f"unreadable inventory for {node!r}: {exc}")
    if not isinstance(parsed, dict):
        return RunnerError("internal", f"unexpected inventory shape for {node!r}")
    return cast("dict[str, object]", parsed)


# Terminal escapes a PTY-backed session carries: CSI sequences, OSC title
# strings (the shell setting the window title), and lone control chars. The
# interactive docker channel is a real terminal, so its output needs this
# before anything asserts on it.
_TERM_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[=>]")
# Lines a login shell contributes that are not the command's output.
_SHELL_ARTIFACTS = frozenset({"exit", "logout"})


def clean_pty_output(raw: str, command: str, prompt: str) -> str:
    """Reduce a PTY session's transcript to the command's own output.

    A container TTY echoes what we type and the login shell prints a prompt
    around it, so drop: terminal escapes, the echoed command and `exit`, the
    shell's farewell, and any line that is (or starts with) the prompt we saw
    before sending anything."""
    text = _TERM_ESCAPES.sub("", raw).replace("\r\n", "\n").replace("\r", "")
    kept: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped in _SHELL_ARTIFACTS or stripped == command.strip():
            continue
        if prompt and stripped.startswith(prompt):
            # The prompt line may carry the echoed command after it.
            remainder = stripped[len(prompt) :].strip()
            if remainder in _SHELL_ARTIFACTS or remainder == command.strip() or not remainder:
                continue
        kept.append(line)
    return "\n".join(kept).strip("\n")


def _docker_interactive_exec(
    host: dict[str, object], node: str, command: str
) -> ExecOutcome | RunnerError:
    """Run the command through a PTY-backed `docker exec -it` login shell.

    Delta 28: `interactive: true` used to be a silent no-op on docker-transport
    nodes. It now opens a real interactive session, which is what some CLIs
    require — VyOS installs its op-mode commands from INTERACTIVE SHELL
    INITIALIZATION, so `ping … vrf …` works here and not in the one-shot
    `<shell> -c` form netlab exec uses (verified live 2026-08-10).

    The command and an `exit` are written together and the transcript is read
    to EOF: deterministic framing with no prompt-regex per platform, and the
    shell's own exit closes the channel."""
    container = str(host.get("ansible_host") or node)
    # netlab spells `docker_shell` as a string ("su - vyos") or a list; both
    # mean the argv of the login shell to open.
    shell_spec = host.get("docker_shell") or "bash"
    shell: list[str] = (
        [str(part) for part in cast("list[object]", shell_spec)]
        if isinstance(shell_spec, list)
        else str(shell_spec).split(" ")
    )
    argv = ["docker", "exec", "-i", "-t", container, *shell]

    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    except OSError as exc:
        os.close(master)
        os.close(slave)
        return RunnerError("interactive", f"could not open a session on {node}: {exc}")
    os.close(slave)

    deadline = time.monotonic() + _EXEC_TIMEOUT_SECONDS
    banner = ""
    try:
        # Let the login shell finish printing its prompt, which is the only
        # per-session string we need in order to strip it back out.
        settle = time.monotonic() + _PTY_SETTLE_SECONDS
        while time.monotonic() < settle:
            if select.select([master], [], [], 0.2)[0]:
                banner += os.read(master, 65536).decode(errors="replace")
        prompt_lines = _TERM_ESCAPES.sub("", banner).replace("\r\n", "\n").strip().splitlines()
        prompt = prompt_lines[-1].strip() if prompt_lines else ""

        # ONE line at a time: readline DISCARDS type-ahead, so a command and a
        # trailing `exit` written together lose the `exit` — the command runs,
        # the session never closes, and the exec burns its whole timeout
        # (observed live 2026-08-10). The shell reprints its prompt when the
        # command returns, and that prompt — captured above, per session, so
        # no per-platform regex — is the end marker. With no prompt to match,
        # fall back to closing the session and reading to EOF.
        framed = bool(prompt)
        os.write(master, (command + "\n" if framed else command + "\nexit\n").encode())
        raw = ""
        finished = False
        while time.monotonic() < deadline:
            if not select.select([master], [], [], 0.3)[0]:
                if proc.poll() is not None:
                    finished = True
                    break
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:  # the pty closes when the shell exits
                finished = True
                break
            if not chunk:
                finished = True
                break
            raw += chunk.decode(errors="replace")
            # Match the prompt only at the END of the transcript: it is the
            # last thing on the wire when a command returns, so output that
            # merely mentions it cannot cut the read short.
            if framed and _TERM_ESCAPES.sub("", raw).rstrip().endswith(prompt):
                finished = True
                break
    finally:
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                os.write(master, b"exit\n")
            try:
                _ = proc.wait(timeout=_PTY_EXIT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
        _ = proc.wait()
        os.close(master)

    if not finished:
        return RunnerError("interactive", f"interactive exec timed out on {node}")
    return ExecOutcome(node=node, stdout=clean_pty_output(raw, command, prompt))


def _interactive_exec(
    host: dict[str, object], node: str, command: str
) -> ExecOutcome | RunnerError:
    """Run the command over a persistent netmiko CLI channel. IOS closes a
    one-shot SSH exec channel on timed commands (`ping … repeat`, traceroute),
    truncating output after the first packet; netmiko drives a real channel and
    reads until the prompt returns (delta 17's `interactive: true`)."""
    network_os = host.get("ansible_network_os")
    device_type = _NETMIKO_DEVICE_TYPES.get(str(network_os))
    if device_type is None:
        return RunnerError(
            "interactive", f"no interactive CLI driver for network_os {network_os!r}"
        )
    try:
        with ConnectHandler(
            device_type=device_type,
            host=str(host.get("ansible_host", "")),
            username=str(host.get("ansible_user", "")),
            password=str(host.get("ansible_ssh_pass", "")),
        ) as connection:
            # Leave netmiko ~5s to notice a hung command before the HTTP layer's
            # own exec timeout would kill the whole request.
            output = connection.send_command(command, read_timeout=float(_EXEC_TIMEOUT_SECONDS - 5))
    except (NetmikoBaseException, OSError, ValueError) as exc:
        return RunnerError("interactive", f"interactive exec failed on {node}: {exc}")
    return ExecOutcome(node=node, stdout=output if isinstance(output, str) else str(output))


def exec_command(
    definition: str,
    node: str,
    command: str,
    templates: dict[str, str],
    *,
    interactive: bool = False,
) -> ExecOutcome | RunnerError:
    """Run one operational `command` on `node` via `netlab exec`, which picks the
    per-NOS transport (docker exec for VyOS/FRR, ssh for Cisco/Nokia/…) from the
    netlab inventory — so this stays NOS-agnostic. `definition` must carry the
    stable `name:`; `templates` is the custom-config fileset the definition may
    reference (needed for the inventory's `netlab create`). `interactive` routes
    the command through a persistent netmiko channel when the node's transport
    is SSH — and is a deliberate no-op otherwise (docker exec streams complete
    output already). Returns the command's stdout (connection chatter
    stripped)."""
    name = _definition_name(definition)
    if name is None:
        return RunnerError("internal", "definition has no name")
    workdir = _ensure_inventory(definition, name, templates)
    if isinstance(workdir, RunnerError):
        return workdir
    if interactive:
        host = _host_vars(workdir, node)
        if isinstance(host, RunnerError):
            return host
        if str(host.get("ansible_connection")) in _SSH_CONNECTIONS:
            return _interactive_exec(host, node, command)
        # Docker-transport node: a PTY-backed `docker exec -it` session
        # (delta 28 — this used to fall through to the one-shot path, making
        # `interactive: true` a silent no-op here).
        return _docker_interactive_exec(host, node, command)
    argv = ["netlab", "exec", node, *shlex.split(command)]
    result = _run(argv, workdir, _EXEC_TIMEOUT_SECONDS)
    if isinstance(result, str):
        return RunnerError("internal", result)
    if result.returncode != 0:
        # netlab exec couldn't reach or run on the node (e.g. node down).
        message = (result.stderr or result.stdout or "netlab exec failed").strip()
        return RunnerError("netlab-exec", message)
    return ExecOutcome(node=node, stdout=_clean_exec_output(result.stdout))

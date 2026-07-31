"""The primitives, exercised with an injected runner and a fake sysfs tree —
every decision path, no host contact."""

from pathlib import Path

from hostprep.host import (
    CommandFailure,
    delete_bridge,
    ensure_bridge,
    interface_state,
    load_module,
    valid_bridge_name,
)


class Recorder:
    """A Run that records argv and returns queued failures (None = success)."""

    def __init__(self, failures: dict[str, CommandFailure] | None = None) -> None:
        self.commands: list[list[str]] = []
        # Keyed by the first differing token ("add"/"set"/"del"/module name).
        self._failures = failures or {}

    def __call__(self, argv: list[str]) -> CommandFailure | None:
        self.commands.append(argv)
        for key, failure in self._failures.items():
            if key in argv:
                return failure
        return None


def make_bridge(sysfs_net: Path, name: str, *, ports: list[str] | None = None) -> None:
    (sysfs_net / name / "bridge").mkdir(parents=True)
    brif = sysfs_net / name / "brif"
    brif.mkdir()
    for port in ports or []:
        (brif / port).mkdir()


def make_plain_interface(sysfs_net: Path, name: str) -> None:
    (sysfs_net / name).mkdir(parents=True)


# --- name validation ---------------------------------------------------------


def test_bridge_name_accepts_netlab_shapes() -> None:
    # name[0:10] + "_" + linkindex, lab-name charset (incl. upper/dot/underscore).
    for name in ("campus-lan_5", "bb-lab-3f9_1", "a_1", "My.Lab_10", "x_9999"):
        assert valid_bridge_name(name), name


def test_bridge_name_rejects_everything_else() -> None:
    for name in (
        "eth0",  # no _<index>
        "elevenchars_1",  # prefix longer than netlab's 10-char truncation
        "campus-lan_",  # no index
        "campus-lan_12345",  # index too wide (name would exceed IFNAMSIZ)
        "_1",  # empty prefix
        "-ab_1",  # prefix must start alphanumeric
        "a/b_1",  # path separator
        "a b_1",  # whitespace
        "",
    ):
        assert not valid_bridge_name(name), name


# --- interface_state ---------------------------------------------------------


def test_interface_state(tmp_path: Path) -> None:
    make_bridge(tmp_path, "lab_1")
    make_bridge(tmp_path, "lab_2", ports=["veth0"])
    make_plain_interface(tmp_path, "eth0")
    assert interface_state(tmp_path, "lab_1") == "bridge_empty"
    assert interface_state(tmp_path, "lab_2") == "bridge_ports"
    assert interface_state(tmp_path, "eth0") == "other"
    assert interface_state(tmp_path, "lab_9") == "absent"


# --- ensure_bridge -----------------------------------------------------------


def test_ensure_creates_ups_and_masks(tmp_path: Path) -> None:
    run = Recorder()
    outcome = ensure_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "created"
    assert run.commands == [
        ["ip", "link", "add", "name", "lab_1", "type", "bridge"],
        ["ip", "link", "set", "dev", "lab_1", "up"],
        ["ip", "link", "set", "dev", "lab_1", "type", "bridge", "group_fwd_mask", "65528"],
    ]


def test_ensure_existing_bridge_converges_without_add(tmp_path: Path) -> None:
    # Idempotent: up + fwd-mask re-applied (converges an interrupted run), the
    # add skipped. A bridge with ports (redeploy of a still-wired lab) is the
    # same case.
    make_bridge(tmp_path, "lab_1", ports=["veth0"])
    run = Recorder()
    outcome = ensure_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "existed"
    assert [argv[:3] for argv in run.commands] == [["ip", "link", "set"], ["ip", "link", "set"]]


def test_ensure_refuses_non_bridge(tmp_path: Path) -> None:
    make_plain_interface(tmp_path, "lab_1")
    run = Recorder()
    outcome = ensure_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "not_bridge"
    assert run.commands == []  # never touched


def test_ensure_reports_command_failure(tmp_path: Path) -> None:
    run = Recorder({"add": CommandFailure("RTNETLINK answers: operation not permitted")})
    outcome = ensure_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "error"
    assert "not permitted" in outcome.detail


# --- delete_bridge -----------------------------------------------------------


def test_delete_empty_bridge(tmp_path: Path) -> None:
    make_bridge(tmp_path, "lab_1")
    run = Recorder()
    outcome = delete_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "deleted"
    assert run.commands == [["ip", "link", "del", "dev", "lab_1"]]


def test_delete_absent_is_fine(tmp_path: Path) -> None:
    run = Recorder()
    outcome = delete_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "absent"
    assert run.commands == []


def test_delete_refuses_bridge_with_ports(tmp_path: Path) -> None:
    # Attached ports after a clean destroy mean something ELSE is wired to it
    # (e.g. a truncation-colliding lab) — refuse rather than cut it loose.
    make_bridge(tmp_path, "lab_1", ports=["veth0"])
    run = Recorder()
    outcome = delete_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "in_use"
    assert run.commands == []


def test_delete_refuses_non_bridge(tmp_path: Path) -> None:
    make_plain_interface(tmp_path, "lab_1")
    run = Recorder()
    outcome = delete_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "not_bridge"
    assert run.commands == []


def test_delete_reports_command_failure(tmp_path: Path) -> None:
    make_bridge(tmp_path, "lab_1")
    run = Recorder({"del": CommandFailure("boom")})
    outcome = delete_bridge("lab_1", sysfs_net=tmp_path, run=run)
    assert outcome.status == "error"
    assert outcome.detail == "boom"


# --- load_module -------------------------------------------------------------


def test_load_module_ok() -> None:
    run = Recorder()
    outcome = load_module("vrf", run=run)
    assert outcome.ok
    assert run.commands == [["modprobe", "vrf"]]


def test_load_module_failure_is_reported_not_raised() -> None:
    run = Recorder({"mpls-router": CommandFailure("module mpls_router not found")})
    outcome = load_module("mpls-router", run=run)
    assert not outcome.ok
    assert "not found" in outcome.detail

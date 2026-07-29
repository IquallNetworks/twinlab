"""End-to-end jump-host authorization over real ssh (marker: deploy).

The jump's contract is enforced by sshd itself, so these tests probe it with
the host's real OpenSSH client. Every probe failure exits 255 — the stderr
text is the discriminator (see _ssh.jump_probe).
"""

from pathlib import Path

import pytest
from twinlab_client import DeployResponse, TwinlabClient

from _config import LINUX_LAB_DEFINITION, LabFactory, UserClientFactory
from _ssh import generate_keypair, jump_probe

pytestmark = pytest.mark.deploy

# A linux-node deploy takes tens of seconds; leave slack for a loaded host.
JOB_WAIT = 600.0


async def test_jump_tunnels_are_scoped_to_permitted_nodes(
    admin: TwinlabClient,
    make_user_client: UserClientFactory,
    make_lab: LabFactory,
    tmp_path: Path,
) -> None:
    # A creator-role user owns the lab, so they hold lab:terminal implicitly.
    _, owner = await make_user_client({"creator"})
    lab = await make_lab(owner)
    _ = await owner.update_definition(lab.name, LINUX_LAB_DEFINITION)
    job = await owner.deploy_lab(lab.name)
    done = await owner.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error
    assert isinstance(done.result, DeployResponse)

    detail = await owner.get_lab(lab.name)
    node_ip = next(node.mgmt_ip for node in detail.nodes if node.mgmt_ip)

    access = await owner.get_ssh_access()
    assert access.enabled and access.host and access.port and access.user

    private, public = generate_keypair(tmp_path)
    key = await owner.create_ssh_key("bb-jump", public)

    # Permitted node: the channel must clear permitopen and reach the node's
    # TCP stack. The linux node runs no sshd, so "Connection refused" IS the
    # success signal — and proves the refusal came from the target, not from
    # sshd's authorization.
    probe = jump_probe(access.host, access.port, access.user, private, node_ip)
    assert "administratively prohibited" not in probe.stderr, probe.stderr
    assert probe.returncode == 0 or "Connection refused" in probe.stderr, probe.stderr

    # An address outside the permitted set (the lab's mgmt gateway): sshd
    # rejects the channel before any connection is attempted.
    gateway = node_ip.rsplit(".", 1)[0] + ".1"
    probe = jump_probe(access.host, access.port, access.user, private, gateway)
    assert "administratively prohibited" in probe.stderr, probe.stderr

    # The key was offered at the jump — last_used_at is stamped.
    listed = await owner.list_ssh_keys()
    assert listed[0].last_used_at is not None

    # Key deleted -> the next connection doesn't authenticate at all.
    await owner.delete_ssh_key(key.id)
    probe = jump_probe(access.host, access.port, access.user, private, node_ip)
    assert "Permission denied" in probe.stderr, probe.stderr

    # A server-GENERATED key authenticates and tunnels exactly like a
    # registered bring-your-own key.
    generated = await owner.generate_ssh_key("bb-issued")
    issued = tmp_path / "issued_key"
    _ = issued.write_text(generated.private_key)
    issued.chmod(0o600)
    probe = jump_probe(access.host, access.port, access.user, issued, node_ip)
    assert "administratively prohibited" not in probe.stderr, probe.stderr
    assert probe.returncode == 0 or "Connection refused" in probe.stderr, probe.stderr


async def test_jump_rejects_unregistered_and_unprivileged_keys(
    make_user_client: UserClientFactory, tmp_path: Path
) -> None:
    # No deploy needed: both cases must fail at authentication, before any
    # tunnel. Kept in the deploy slice because they need the jump service.
    _, client = await make_user_client(None)
    access = await client.get_ssh_access()
    assert access.enabled and access.host and access.port and access.user

    # Unregistered key.
    private, _ = generate_keypair(tmp_path, name="unregistered")
    probe = jump_probe(access.host, access.port, access.user, private, "10.255.255.1")
    assert "Permission denied" in probe.stderr, probe.stderr

    # Registered key whose owner holds lab:terminal NOWHERE: the backend must
    # answer with no authorized_keys line at all (the fail-safe invariant —
    # a line without permitopen would mean unrestricted forwarding), so the
    # outcome is the same denial, never an open tunnel.
    unprivileged, public = generate_keypair(tmp_path, name="unprivileged")
    _ = await client.create_ssh_key("bb-noaccess", public)
    probe = jump_probe(access.host, access.port, access.user, unprivileged, "10.255.255.1")
    assert "Permission denied" in probe.stderr, probe.stderr

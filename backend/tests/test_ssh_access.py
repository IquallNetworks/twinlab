"""authorized_keys rendering: the fail-safe invariant and the exact line shape."""

from twinlab_backend.services.ssh_access import render_authorized_keys_line

_KEY_B64 = "AAAAC3NzaC1lZDI1NTE5AAAAICqV0SzGoIXhwxC20lGKnnEfZhMb21y8MexZAcvJSUA9"


def test_empty_node_set_renders_nothing() -> None:
    # THE fail-safe invariant: a `restrict,port-forwarding` line with zero
    # permitopen options would mean unrestricted forwarding, so "no permitted
    # nodes" must render as NO line (sshd then denies authentication).
    assert render_authorized_keys_line("ssh-ed25519", _KEY_B64, "alice", []) == ""


def test_line_shape_single_node() -> None:
    line = render_authorized_keys_line("ssh-ed25519", _KEY_B64, "alice", ["10.77.4.101"])
    assert line == (
        f'restrict,port-forwarding,permitopen="10.77.4.101:*" ssh-ed25519 {_KEY_B64} twinlab:alice'
    )


def test_line_shape_multiple_nodes() -> None:
    line = render_authorized_keys_line(
        "ssh-ed25519", _KEY_B64, "alice", ["10.77.4.101", "10.77.4.102"]
    )
    options, algorithm, blob, comment = line.split(" ")
    assert options == (
        'restrict,port-forwarding,permitopen="10.77.4.101:*",permitopen="10.77.4.102:*"'
    )
    assert (algorithm, blob, comment) == ("ssh-ed25519", _KEY_B64, "twinlab:alice")


def test_every_line_starts_restricted() -> None:
    # The option order matters to a reader: restrictions first, then the
    # per-node openings that relax them.
    line = render_authorized_keys_line("ssh-rsa", _KEY_B64, "bob", ["10.77.5.101"])
    assert line.startswith("restrict,port-forwarding,")

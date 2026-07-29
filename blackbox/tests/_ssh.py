"""SSH helpers for the jump-host slices: real keypairs and real ssh probes.

The jump feature's end product is a standard `ssh` connection, so these
helpers shell out to the host's OpenSSH client (`ssh-keygen`/`ssh`) — a
deliberate exception to "tests speak only through twinlab-client", in the
same spirit as the raw-HTTP wire probes (see README).
"""

import subprocess
from pathlib import Path


def generate_keypair(directory: Path, name: str = "id_ed25519") -> tuple[Path, str]:
    """Generate an ed25519 keypair; returns (private_key_path, public_key_line)."""
    private = directory / name
    _ = subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "bb-suite", "-f", str(private)],
        check=True,
        capture_output=True,
        text=True,
    )
    return private, (directory / f"{name}.pub").read_text().strip()


def keygen_fingerprint(key_file: Path) -> str:
    """The `SHA256:...` fingerprint as OpenSSH itself computes it."""
    result = subprocess.run(
        ["ssh-keygen", "-lf", str(key_file)], check=True, capture_output=True, text=True
    )
    return result.stdout.split()[1]


def jump_probe(
    host: str,
    port: int,
    user: str,
    private_key: Path,
    target: str,
    target_port: int = 22,
) -> subprocess.CompletedProcess[str]:
    """Open a direct-tcpip channel through the jump: `ssh -W target:port`.

    `-W` implies no session/PTY, so it works against the forwarding-only jump
    account. Every failure mode exits 255 — the stderr text discriminates:
    "administratively prohibited" = sshd's permitopen rejected the channel,
    "Connection refused" = the channel cleared authorization and reached the
    target's TCP stack, "Permission denied" = authentication failed. The
    channel-failure reasons print at the default INFO level (verified live:
    LogLevel=ERROR reduces them all to "stdio forwarding failed").
    """
    command = [
        "ssh",
        "-p",
        str(port),
        "-i",
        str(private_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=5",
        "-W",
        f"{target}:{target_port}",
        f"{user}@{host}",
    ]
    return subprocess.run(
        command, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL
    )

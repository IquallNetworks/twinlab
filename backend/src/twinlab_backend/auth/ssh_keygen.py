"""Server-side keypair generation: an ssh-keygen subprocess boundary.

Concurrency-safe without locks: every call works in its own freshly-created
`TemporaryDirectory` (mkdtemp — unique name, mode 0700), so concurrent
generations never share a path. The directory — and the private key in it —
is deleted before this function returns; the caller's response is the only
copy that ever leaves.
"""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from twinlab_backend.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class GeneratedKeyPair:
    private_key: str  # OpenSSH PEM text
    public_key: str  # one authorized_keys-format line


@dataclass(frozen=True, slots=True)
class SshKeygenError:
    detail: str


def generate_ed25519(comment: str) -> Result[GeneratedKeyPair, SshKeygenError]:
    """Blocking (subprocess + file I/O) — call via `run_in_threadpool`."""
    with tempfile.TemporaryDirectory() as workdir:
        private_path = Path(workdir) / "id_ed25519"
        try:
            proc = subprocess.run(
                [
                    "ssh-keygen",
                    "-q",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-C",
                    comment,
                    "-f",
                    str(private_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0:
                return Err(SshKeygenError(proc.stderr.strip()))
            return Ok(
                GeneratedKeyPair(
                    private_key=private_path.read_text(),
                    public_key=private_path.with_suffix(".pub").read_text().strip(),
                )
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return Err(SshKeygenError(str(exc)))

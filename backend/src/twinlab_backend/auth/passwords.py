"""Password hashing via pwdlib (argon2).

pwdlib is the boundary. `hash` produces a self-describing argon2 string;
`verify` returns False for a wrong password and, defensively, for a hash it
cannot parse — auth should deny, never 500, on a malformed stored hash.
"""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password, password_hash)
    except UnknownHashError, ValueError:
        return False

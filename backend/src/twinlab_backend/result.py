"""Minimal success-or-typed-error result.

Twinlab prefers returning errors as values over raising; `try`/`except` is
confined to boundary adapters that translate a third-party exception into one of
these. Callers pattern-match on the concrete type (`isinstance(r, Err)`).
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E


type Result[T, E] = Ok[T] | Err[E]

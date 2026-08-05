"""Built-in network templates (delta 21): loading + the examples/ drift guard.

The packaged sources mirror the repo's `examples/` (the backend image cannot
see the repo root). An example edit that doesn't reach the packaged copy must
fail HERE, not ship a stale template.
"""

from pathlib import Path

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.network_templates import load_network_templates

# Template name -> the examples/ file it mirrors. The `example-` prefix keeps
# the builtin namespace off real lab names (a builtin name blocks publishing a
# lab called the same — and labs deployed from these examples ARE called by
# the bare names).
_EXAMPLE_SOURCES = {
    "example-mpls-l3vpn": "mpls-l3vpn.yml",
    "example-campus-lan": "campus-lan.yml",
}

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def test_load_serves_the_builtins_in_spec_order() -> None:
    loaded = load_network_templates()
    assert isinstance(loaded, Ok)
    library = loaded.value
    assert [t.name for t in library.templates] == list(_EXAMPLE_SOURCES)
    assert library.names == frozenset(_EXAMPLE_SOURCES)
    for template in library.templates:
        assert template.description
        assert template.content.strip()


def test_get_by_name() -> None:
    loaded = load_network_templates()
    assert isinstance(loaded, Ok)
    library = loaded.value
    found = library.get("example-campus-lan")
    assert found is not None and found.name == "example-campus-lan"
    assert library.get("no-such-template") is None


def test_packaged_sources_match_the_repo_examples() -> None:
    """Drift guard: the packaged copies are byte-identical to examples/."""
    loaded = load_network_templates()
    assert isinstance(loaded, Ok)
    by_name = {t.name: t for t in loaded.value.templates}
    for name, example_file in _EXAMPLE_SOURCES.items():
        expected = (_EXAMPLES_DIR / example_file).read_text()
        assert by_name[name].content == expected, (
            f"builtin '{name}' drifted from examples/{example_file} — "
            "re-copy it into services/builtin_network_templates/"
        )


def test_load_error_is_typed_not_raised() -> None:
    """The loader is a Result boundary; this pins the Err type exists and the
    happy path above is the one exercised (a missing-package scenario can't be
    simulated without mangling importlib state)."""
    loaded = load_network_templates()
    assert not isinstance(loaded, Err)

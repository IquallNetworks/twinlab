from twinlab_backend.result import Ok
from twinlab_backend.services.custom_config import BuiltinLibrary, BuiltinTemplate, load_builtins


def test_load_builtins_ships_mpls_te_and_ip_sla() -> None:
    loaded = load_builtins()
    assert isinstance(loaded, Ok), loaded
    library = loaded.value
    assert library.names == frozenset({"mpls_te", "ip_sla"})
    # Each built-in ships at least its IOS/iol variant, keyed by the relpath netlab
    # searches (name/<device>.j2), with real template content.
    fileset = library.fileset
    assert "mpls_te/ios.j2" in fileset
    assert "ip_sla/ios.j2" in fileset
    assert "traffic-eng" in fileset["mpls_te/ios.j2"]
    assert "ip sla" in fileset["ip_sla/ios.j2"]


def _library() -> BuiltinLibrary:
    return BuiltinLibrary(
        templates=(BuiltinTemplate(name="mpls_te", description="", files={"mpls_te/ios.j2": "x"}),)
    )


def test_collision_reserves_the_builtin_namespace() -> None:
    lib = _library()
    # A flat file, a per-device variant, and the bare name all shadow the built-in.
    assert lib.collision({"mpls_te.j2": "u"}) == "mpls_te.j2"
    assert lib.collision({"mpls_te/vyos.j2": "u"}) == "mpls_te/vyos.j2"
    # An unrelated user template is fine.
    assert lib.collision({"nat/ios.j2": "u"}) is None
    assert lib.collision({}) is None


def test_fileset_merges_all_builtin_files() -> None:
    lib = BuiltinLibrary(
        templates=(
            BuiltinTemplate(name="a", description="", files={"a/ios.j2": "1"}),
            BuiltinTemplate(name="b", description="", files={"b/ios.j2": "2", "b/eos.j2": "3"}),
        )
    )
    assert lib.fileset == {"a/ios.j2": "1", "b/ios.j2": "2", "b/eos.j2": "3"}

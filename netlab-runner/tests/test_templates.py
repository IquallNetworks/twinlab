from netlab_runner.runner import template_path_error


def test_accepts_flat_and_nested_j2() -> None:
    # A flat template and a per-device variant (netlab's name/<device>.j2 form).
    assert template_path_error("mpls_te.j2") is None
    assert template_path_error("ip_sla/ios.j2") is None


def test_rejects_traversal() -> None:
    assert template_path_error("../escape.j2") is not None
    assert template_path_error("mpls_te/../../escape.j2") is not None


def test_rejects_absolute_path() -> None:
    assert template_path_error("/etc/evil.j2") is not None


def test_rejects_non_j2_suffix() -> None:
    assert template_path_error("mpls_te.cfg") is not None
    assert template_path_error("mpls_te") is not None

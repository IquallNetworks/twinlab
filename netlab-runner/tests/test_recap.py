from netlab_runner.runner import NodeResult, aggregate, parse_recap

# A representative `netlab initial` tail: netlab chatter, then Ansible's recap.
_OUTPUT = """\
PLAY [Deploy initial device configuration] *************************************

TASK [Gathering Facts] *********************************************************
ok: [r1]
ok: [r2]

PLAY RECAP *********************************************************************
r1                         : ok=7    changed=5    unreachable=0    failed=0    skipped=1
r2                         : ok=7    changed=5    unreachable=0    failed=1    skipped=1
"""


def test_parse_recap_extracts_per_node_counts() -> None:
    nodes = {n.node: n for n in parse_recap(_OUTPUT)}
    assert set(nodes) == {"r1", "r2"}
    assert nodes["r1"].changed == 5
    assert nodes["r1"].succeeded
    # a failed task on r2 must not be read as success
    assert nodes["r2"].failed == 1
    assert not nodes["r2"].succeeded


def test_parse_recap_ignores_pre_recap_host_lines() -> None:
    # `ok: [r1]` before the PLAY RECAP header must not be parsed as a recap row.
    assert parse_recap("TASK [x]\nok: [r1]\n") == []


def test_aggregate_collapses_multiple_plays_per_node() -> None:
    # netlab runs several plays; a node's rows sum, and any failure sticks.
    rows = [
        NodeResult("r1", ok=5, changed=0, unreachable=0, failed=0),
        NodeResult("r2", ok=5, changed=0, unreachable=0, failed=0),
        NodeResult("r1", ok=18, changed=4, unreachable=0, failed=0),
        NodeResult("r2", ok=10, changed=1, unreachable=0, failed=2),
    ]
    totals = {n.node: n for n in aggregate(rows)}
    assert len(totals) == 2
    assert totals["r1"].ok == 23 and totals["r1"].changed == 4 and totals["r1"].succeeded
    assert totals["r2"].failed == 2 and not totals["r2"].succeeded

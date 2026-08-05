from netlab_runner.runner import parse_image_lines

# Representative `docker image ls --format '{{.Repository}}:{{.Tag}}'` output:
# tagged images, a dangling build layer, and an untagged pull.
_OUTPUT = """\
ghcr.io/sysoleg/vyos-container:latest
vrnetlab/mikrotik_routeros:7.21.4
python:3.13-alpine
<none>:<none>
ghcr.io/nokia/srlinux:<none>
"""


def test_parse_image_lines_keeps_tagged_names() -> None:
    assert parse_image_lines(_OUTPUT) == [
        "ghcr.io/sysoleg/vyos-container:latest",
        "vrnetlab/mikrotik_routeros:7.21.4",
        "python:3.13-alpine",
    ]


def test_parse_image_lines_empty_output() -> None:
    assert parse_image_lines("") == []

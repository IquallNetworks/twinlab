# textfsm.clitable — the index-driven template dispatcher (what
# ntc_templates.parse_output wraps). Transcribed from textfsm 2.1 source.
from collections.abc import Iterator

class CliTableError(Exception): ...

class CliTable:
    header: list[str]
    def __init__(self, index_file: str | None = ..., template_dir: str | None = ...) -> None: ...
    def ParseCmd(
        self,
        cmd_input: str,
        attributes: dict[str, str] | None = ...,
        templates: str | None = ...,
    ) -> None: ...
    def __iter__(self) -> Iterator[list[object]]: ...

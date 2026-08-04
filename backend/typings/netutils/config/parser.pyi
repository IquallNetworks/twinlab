# netutils.config.parser — transcribed from netutils 1.18 source. ConfigLine
# is `namedtuple("ConfigLine", "config_line,parents")` at runtime; `parents`
# holds the ancestor lines outermost-first.
from typing import NamedTuple

class ConfigLine(NamedTuple):
    config_line: str
    parents: tuple[str, ...]

class BaseConfigParser:
    config_lines: list[ConfigLine]
    def __init__(self, config: str) -> None: ...

class BaseSpaceConfigParser(BaseConfigParser): ...
class CiscoConfigParser(BaseSpaceConfigParser): ...
class IOSConfigParser(CiscoConfigParser): ...

# Minimal local stubs for textfsm (ships untyped). Only what Twinlab imports.
from textfsm import clitable as clitable

class Error(Exception): ...

# Raised by ParseCmd when a template RESOLVED but the output does not fit it —
# distinct from clitable.CliTableError, which means "no template found".
class TextFSMError(Error): ...

"""The user guide as MCP resources.

Each page of `docs/guide/` is one resource, `twinlab://guide/<file>`. The URI
keeps the file name, extension included, so the pages' own relative links
(`[Install](01-install.md)`) resolve against it to another resource's URI.

The pages are read once at startup: they are baked into the image, so a read
can never see anything newer.
"""

from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver.resources import TextResource

URI_PREFIX = "twinlab://guide/"


@dataclass(frozen=True, slots=True)
class GuideError:
    message: str


def load_guide(directory: Path) -> list[TextResource] | GuideError:
    try:
        pages = sorted(directory.glob("*.md"))
        texts = [(page.name, page.read_text(encoding="utf-8")) for page in pages]
    except OSError as exc:
        return GuideError(f"cannot read the guide at {directory}: {exc}")
    # A missing directory globs to nothing rather than failing, and serving no
    # guide at all would look like a guide with nothing in it.
    if not texts:
        return GuideError(f"no guide pages found in {directory}")
    return [
        TextResource(
            uri=URI_PREFIX + name,
            name=name,
            title=_title(text) or name,
            description="A page of the Twinlab user guide.",
            mime_type="text/markdown",
            text=text,
        )
        for name, text in texts
    ]


def _title(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return None

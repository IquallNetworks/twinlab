"""Provider button icons (delta 33): accept, check, and render as data: URIs.

An icon is served INLINE as a `data:` URI, never from a URL of its own. That
is what makes SVG safe without a sanitizer: an SVG served from Twinlab's
origin could run script if opened directly, but a data: URI rendered through
<img> runs none, and browsers refuse to open data: URLs as a top-level page.
"""

import base64
import xml.etree.ElementTree as ET
from typing import Literal, get_args

from twinlab_backend.result import Err, Ok, Result

IconType = Literal["image/svg+xml", "image/png", "image/webp"]
ICON_TYPES: tuple[IconType, ...] = get_args(IconType)

# Plenty for a button glyph, and it bounds what the UNAUTHENTICATED provider
# listing carries (every enabled provider's icon rides it).
MAX_ICON_BYTES = 32 * 1024

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_SVG_NAMESPACE_ROOT = "{http://www.w3.org/2000/svg}svg"


def _is_svg(content: bytes) -> bool:
    # A DTD is refused outright: it is the only road to entity expansion
    # (billion laughs, external entities), and no button icon needs one.
    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        return False
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return False
    return root.tag in ("svg", _SVG_NAMESPACE_ROOT)


def _matches(content: bytes, declared: IconType) -> bool:
    match declared:
        case "image/png":
            return content.startswith(_PNG_MAGIC)
        case "image/webp":
            return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
        case "image/svg+xml":
            return _is_svg(content)


def parse_icon_type(content_type: str | None) -> IconType | None:
    """The declared media type, parameters (`; charset=…`) ignored."""
    if content_type is None:
        return None
    bare = content_type.split(";", 1)[0].strip().lower()
    return next((kind for kind in ICON_TYPES if kind == bare), None)


def check_icon(content: bytes, content_type: str | None) -> Result[IconType, str]:
    """The icon's media type, or why it is refused. The bytes must BE what the
    request declares — a type the server never checked is a type an attacker
    chose."""
    declared = parse_icon_type(content_type)
    if declared is None:
        return Err(f"unsupported icon type; accepted: {', '.join(ICON_TYPES)}")
    if not content:
        return Err("the icon is empty")
    if len(content) > MAX_ICON_BYTES:
        return Err(f"the icon exceeds {MAX_ICON_BYTES} bytes")
    if not _matches(content, declared):
        return Err(f"the content is not a valid {declared} image")
    return Ok(declared)


def data_uri(content: bytes, icon_type: str) -> str:
    return f"data:{icon_type};base64,{base64.b64encode(content).decode()}"

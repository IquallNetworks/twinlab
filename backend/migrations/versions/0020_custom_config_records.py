"""Custom-config templates become structured records (contract delta 27).

`labs.custom_config` reshapes from the raw `{relpath: content}` fileset to a
list of template records `{name, description, variants: [{source, device?,
node?}]}`. Every existing path is one of Twinlab's own three spellings (flat
`X.j2` from user authoring, `imported/<node>.j2` carries and
`imported/<node>.quarantine.j2` quarantines from config import, and
`X/<seg>.j2` per-device variants), so the mapping is exact; an unmappable
path fails the migration loudly rather than guessing — all stored data is
Twinlab-generated, so hitting one means a real bug, not user data to salvage.

Revision ID: 0020_custom_config_records
Revises: 0019_template_library
Create Date: 2026-08-07
"""

import re
from collections.abc import Sequence
from typing import cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0020_custom_config_records"
down_revision: str | None = "0019_template_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The catalog device slugs AT THIS REVISION — deliberately a frozen copy, not
# an import from the live catalog (a migration is a point-in-time snapshot; a
# later catalog change must not alter what this revision did).
_DEVICE_SLUGS = frozenset({"vyos", "frr", "routeros7", "bird", "dnsmasq", "linux"})

_FLAT = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_-]*)\.j2$")
_QUARANTINE = re.compile(r"^imported/(?P<node>[A-Za-z_][A-Za-z0-9_-]{0,15})\.quarantine\.j2$")
_NESTED = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_-]*)/(?P<stem>[A-Za-z_][A-Za-z0-9_-]{0,15})\.j2$"
)


def _records(fileset: dict[str, str], lab_name: str) -> list[dict[str, object]]:
    by_name: dict[str, list[dict[str, object]]] = {}
    for relpath in sorted(fileset):
        content = fileset[relpath]
        quarantine = _QUARANTINE.match(relpath)
        if quarantine is not None:
            by_name.setdefault("imported_quarantine", []).append(
                {"source": content, "node": quarantine.group("node")}
            )
            continue
        flat = _FLAT.match(relpath)
        if flat is not None:
            by_name.setdefault(flat.group("name"), []).append({"source": content})
            continue
        nested = _NESTED.match(relpath)
        if nested is not None:
            stem = nested.group("stem")
            scope = "device" if stem in _DEVICE_SLUGS else "node"
            by_name.setdefault(nested.group("name"), []).append({"source": content, scope: stem})
            continue
        raise ValueError(f"lab '{lab_name}': unmappable custom-config path '{relpath}'")
    return [
        {"name": name, "description": "", "variants": variants}
        for name, variants in by_name.items()
    ]


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT name, custom_config FROM labs WHERE custom_config IS NOT NULL")
    ).fetchall()
    for name, raw in rows:
        if not isinstance(raw, dict) or not raw:
            records: list[dict[str, object]] = []
        else:
            raw_map = cast("dict[str, object]", raw)
            fileset = {
                path: content for path, content in raw_map.items() if isinstance(content, str)
            }
            records = _records(fileset, name)
        connection.execute(
            sa.text("UPDATE labs SET custom_config = :records WHERE name = :name").bindparams(
                sa.bindparam("records", records, type_=JSONB()),
                sa.bindparam("name", name),
            )
        )


def downgrade() -> None:
    # The record shape carries strictly more structure than the fileset; going
    # back would have to re-flatten and lose descriptions. One-way on purpose.
    raise NotImplementedError("delta 27 is not reversible")

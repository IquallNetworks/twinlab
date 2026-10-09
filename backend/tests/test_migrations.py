from pathlib import Path

from alembic.script import ScriptDirectory

_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

# Alembic creates alembic_version.version_num as varchar(32): a longer id
# applies its migration, then fails writing itself down, and the whole upgrade
# rolls back on every start.
_VERSION_NUM_MAX = 32


def test_every_revision_id_fits_alembic_version() -> None:
    script = ScriptDirectory(str(_MIGRATIONS))
    too_long = [
        rev.revision for rev in script.walk_revisions() if len(rev.revision) > _VERSION_NUM_MAX
    ]
    assert too_long == []


def test_the_history_has_one_head() -> None:
    assert len(ScriptDirectory(str(_MIGRATIONS)).get_heads()) == 1

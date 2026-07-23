"""Lab lifecycle contract WITHOUT deploys: create (record) -> author -> visibility.

Everything here is cheap — no containerlab work. Real deploys live in
test_labs_deploy.py behind the `deploy` marker.
"""

from collections.abc import Callable

import pytest
from twinlab_client import TwinlabApiError, TwinlabClient

from _config import (
    LAB_SCOPED_PERMISSIONS,
    LINUX_LAB_DEFINITION,
    NETLAB_INVALID_DEFINITION,
    NOT_YAML_DEFINITION,
    LabFactory,
    SuiteConfig,
    UserClientFactory,
)


async def test_create_lab_is_record_only(config: SuiteConfig, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    assert lab.status == "created"
    assert lab.definition is None  # None only while "created"
    assert lab.nodes == []
    assert lab.config_time_status == "not_run"
    assert lab.owner is not None and lab.owner.name == config.admin_username
    # Owner-implicit permissions at minimum (the admin also holds them globally).
    assert lab.permissions >= LAB_SCOPED_PERMISSIONS


async def test_create_duplicate_name_is_409(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.create_lab(lab.name)
    assert excinfo.value.status_code == 409


async def test_created_lab_appears_in_list(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    rows = {row.name: row for row in await admin.list_labs()}
    row = rows[lab.name]
    assert row.status == "created"
    assert row.nodes == 0
    assert row.config_time_status == "not_run"
    assert row.owner == lab.owner


async def test_get_unknown_lab_is_404(admin: TwinlabClient, unique: Callable[[str], str]) -> None:
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.get_lab(unique("ghost"))
    assert excinfo.value.status_code == 404


async def test_update_definition_stores_without_deploying(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    detail = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    # The backend re-pins the lab name and mgmt subnet into the stored
    # definition, so assert containment rather than equality.
    assert detail.definition is not None
    assert "defaults.device: linux" in detail.definition
    assert detail.status == "created"  # authoring never deploys


async def test_update_definition_netlab_invalid_is_422(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.update_definition(lab.name, NETLAB_INVALID_DEFINITION)
    assert excinfo.value.status_code == 422


async def test_update_definition_not_yaml_is_422(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.update_definition(lab.name, NOT_YAML_DEFINITION)
    assert excinfo.value.status_code == 422


async def test_deploy_without_definition_is_409(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.deploy_lab(lab.name)
    assert excinfo.value.status_code == 409


async def test_destroy_without_remove_requires_running(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    # Pinned QUIRK: remove=False tears down a RUNNING lab; a lab that is not
    # running (here: never deployed) is a 404.
    lab = await make_lab(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.destroy_lab(lab.name)
    assert excinfo.value.status_code == 404


async def test_destroy_with_remove_deletes_the_record(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> None:
    lab = await admin.create_lab(unique("lab"))
    result = await admin.destroy_lab(lab.name, remove=True)
    assert result.status == "deleted"
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.get_lab(lab.name)
    assert excinfo.value.status_code == 404


async def test_lab_hidden_without_read(
    make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    _, outsider = await make_user_client(None)

    assert lab.name not in {row.name for row in await outsider.list_labs()}
    # Existence-hiding: unreadable labs are 404, never 403.
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await outsider.get_lab(lab.name)
    assert excinfo.value.status_code == 404


async def test_global_viewer_reads_but_cannot_edit(
    make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    lab = await make_lab(None)
    _, viewer = await make_user_client({"global_viewer"})

    rows = {row.name: row for row in await viewer.list_labs()}
    assert rows[lab.name].permissions == {"lab:read"}
    detail = await viewer.get_lab(lab.name)
    assert detail.permissions == {"lab:read"}

    # Readable but lacking the permission: 403, not 404.
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await viewer.update_definition(lab.name, LINUX_LAB_DEFINITION)
    assert excinfo.value.status_code == 403


async def test_create_lab_requires_lab_create(
    make_user_client: UserClientFactory, unique: Callable[[str], str]
) -> None:
    _, plain = await make_user_client(None)
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await plain.create_lab(unique("lab"))
    assert excinfo.value.status_code == 403


async def test_creator_becomes_owner(
    make_user_client: UserClientFactory, make_lab: LabFactory
) -> None:
    summary, creator = await make_user_client({"creator"})
    lab = await make_lab(creator)
    assert lab.owner is not None and lab.owner.name == summary.username
    # The creator role grants nothing on the lab itself; everything they hold
    # here is the owner-implicit set.
    assert lab.permissions == LAB_SCOPED_PERMISSIONS

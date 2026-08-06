"""The template library (contract delta 21): both collections and the lab
publish toggle. All cheap — nothing deploys; instantiation is the normal
create/PUT lifecycle other modules already cover.
"""

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from twinlab_client import NodeTemplate, TwinlabApiError, TwinlabClient

from _config import LAN_LAB_DEFINITION, LINUX_LAB_DEFINITION, LabFactory, UserClientFactory

# Pinned in the contract's shipped-catalogs appendix: the builtin network
# collection is the repo examples, `example-`-prefixed so the builtin
# namespace never blocks publishing a lab called by the bare example name.
# A seed change is a contract + suite change.
_BUILTIN_NETWORK_NAMES = frozenset({"example-mpls-l3vpn", "example-campus-lan"})

_FRAGMENT = "device: vyos\nmodule: [ospf, bgp]\nbgp.as: 65001\n"

NodeTemplateFactory = Callable[[], Awaitable[NodeTemplate]]


@pytest.fixture
async def make_node_template(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> AsyncIterator[NodeTemplateFactory]:
    """Create a node template from the standard fragment; teardown best-effort
    deletes it (tests that delete their own template make this a no-op)."""
    names: list[str] = []

    async def factory() -> NodeTemplate:
        name = unique("tmpl")
        created = await admin.create_node_template(
            name, description="bb node template", content=_FRAGMENT
        )
        names.append(name)
        return created

    yield factory
    for name in names:
        with contextlib.suppress(TwinlabApiError):
            await admin.delete_node_template(name)


async def test_builtin_network_templates_are_seeded(admin: TwinlabClient) -> None:
    entries = {t.name: t for t in await admin.list_network_templates()}
    assert set(entries) >= _BUILTIN_NETWORK_NAMES
    for name in _BUILTIN_NETWORK_NAMES:
        entry = entries[name]
        assert entry.tier == "builtin"
        assert entry.description
        assert entry.source_lab is None

    template = await admin.get_network_template("example-campus-lan")
    assert template.tier == "builtin"
    assert "provider: clab" in template.content


async def test_library_reads_need_no_privilege(make_user_client: UserClientFactory) -> None:
    _, plain = await make_user_client(None)
    names = {t.name for t in await plain.list_network_templates()}
    assert names >= _BUILTIN_NETWORK_NAMES
    assert (await plain.get_network_template("example-mpls-l3vpn")).content
    _ = await plain.list_node_templates()  # empty or not — readable either way


async def test_unknown_templates_are_404(admin: TwinlabClient) -> None:
    for getter in (admin.get_network_template, admin.get_node_template):
        with pytest.raises(TwinlabApiError) as raised:
            _ = await getter("bb-no-such-template")
        assert raised.value.status_code == 404
        assert raised.value.code == "template_not_found"


async def test_publish_toggle_lifecycle(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)

    # A bare record has nothing to publish.
    with pytest.raises(TwinlabApiError) as raised:
        _ = await admin.set_lab_template(lab.name, published=True, description="too early")
    assert raised.value.code == "no_definition"

    detail = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    assert detail.template_published is False

    entry = await admin.set_lab_template(lab.name, published=True, description="bb reference lab")
    assert entry is not None
    assert entry.tier == "user"
    assert entry.source_lab == lab.name
    assert entry.description == "bb reference lab"

    listed = {t.name: t for t in await admin.list_network_templates()}
    assert listed[lab.name].tier == "user"
    assert (await admin.get_lab(lab.name)).template_published is True

    # The entry is a LIVE view: it serves the lab's CURRENT stored definition,
    # including edits made after publishing — MINUS the record pins (name,
    # mgmt subnet), which belong to the source lab's record. Served as-stored
    # they made every instantiation 409 mgmt_subnet_taken while the source lab
    # held the subnet.
    stored = (await admin.get_lab(lab.name)).definition
    assert stored is not None
    content = (await admin.get_network_template(lab.name)).content
    assert f"name: {lab.name}" in stored and f"name: {lab.name}" not in content
    assert "mgmt" in stored and "mgmt" not in content
    assert "n3" not in content
    _ = await admin.update_definition(lab.name, LAN_LAB_DEFINITION)
    assert "n3" in (await admin.get_network_template(lab.name)).content

    # Instantiation is create + PUT of the served content, and it must work
    # WHILE the source lab exists (the compose the create dialog's "Start
    # from" performs).
    clone = await make_lab(None)
    cloned = await admin.update_definition(
        clone.name, (await admin.get_network_template(lab.name)).content
    )
    assert cloned.definition is not None

    # Re-publishing updates the card.
    entry = await admin.set_lab_template(lab.name, published=True, description="new card")
    assert entry is not None and entry.description == "new card"

    withdrawn = await admin.set_lab_template(lab.name, published=False)
    assert withdrawn is None
    assert (await admin.get_lab(lab.name)).template_published is False
    assert lab.name not in {t.name for t in await admin.list_network_templates()}
    with pytest.raises(TwinlabApiError) as raised:
        _ = await admin.get_network_template(lab.name)
    assert raised.value.code == "template_not_found"


async def test_soft_delete_withdraws_the_publication(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    entry = await admin.set_lab_template(lab.name, published=True, description="doomed")
    assert entry is not None

    job = await admin.destroy_lab(lab.name, remove=True)
    finished = await admin.wait_job(lab.name, job.id, timeout=120)
    assert finished.status == "succeeded"

    assert lab.name not in {t.name for t in await admin.list_network_templates()}
    with pytest.raises(TwinlabApiError) as raised:
        _ = await admin.get_network_template(lab.name)
    assert raised.value.status_code == 404


async def test_node_template_crud_roundtrip(
    admin: TwinlabClient, make_node_template: NodeTemplateFactory
) -> None:
    created = await make_node_template()
    assert created.tier == "user"
    assert created.device == "vyos"  # extracted from the fragment, not sent

    listed = {t.name: t for t in await admin.list_node_templates()}
    assert listed[created.name].content == _FRAGMENT  # list serves FULL entries

    fetched = await admin.get_node_template(created.name)
    assert fetched == created

    # Full replace — description AND content; the device follows the fragment.
    updated = await admin.update_node_template(
        created.name, description="now frr", content="device: frr\nmodule: [ospf]\n"
    )
    assert updated.description == "now frr"
    assert updated.device == "frr"

    # The name is a per-collection namespace.
    with pytest.raises(TwinlabApiError) as raised:
        _ = await admin.create_node_template(created.name, description="dupe", content=_FRAGMENT)
    assert raised.value.code == "name_taken"

    await admin.delete_node_template(created.name)
    with pytest.raises(TwinlabApiError) as raised:
        _ = await admin.get_node_template(created.name)
    assert raised.value.code == "template_not_found"
    with pytest.raises(TwinlabApiError) as raised:
        await admin.delete_node_template(created.name)
    assert raised.value.status_code == 404


async def test_node_fragment_structural_validation(
    admin: TwinlabClient, unique: Callable[[str], str]
) -> None:
    # Invalid YAML, a non-mapping, and a device-less mapping are all rejected
    # 422 invalid_template — the device rule is the house "device is
    # intentful" rule; everything richer waits for the receiving lab's PUT.
    for content in ("device: [unclosed\n", "- device: vyos\n", "module: [ospf]\n"):
        with pytest.raises(TwinlabApiError) as raised:
            _ = await admin.create_node_template(unique("tmpl"), description="bad", content=content)
        assert raised.value.status_code == 422
        assert raised.value.code == "invalid_template"


async def test_template_mutations_need_template_manage(
    make_user_client: UserClientFactory, unique: Callable[[str], str]
) -> None:
    # A creator can author labs but holds no template:manage: publishing their
    # OWN lab is still 403 (the permission is the deliberate-publication gate).
    _, creator = await make_user_client({"creator"})
    lab = await creator.create_lab(unique("lab"))
    _ = await creator.update_definition(lab.name, LINUX_LAB_DEFINITION)
    with pytest.raises(TwinlabApiError) as raised:
        _ = await creator.set_lab_template(lab.name, published=True, description="mine")
    assert raised.value.status_code == 403

    with pytest.raises(TwinlabApiError) as raised:
        _ = await creator.create_node_template(
            unique("tmpl"), description="mine", content=_FRAGMENT
        )
    assert raised.value.status_code == 403

    # Leave nothing behind: the record is the creator's own.
    job = await creator.destroy_lab(lab.name, remove=True)
    _ = await creator.wait_job(lab.name, job.id, timeout=120)


async def test_global_operator_holds_template_manage(
    make_user_client: UserClientFactory, unique: Callable[[str], str]
) -> None:
    # Role-catalog pin (contract appendix): global_operator curates the
    # library. Publish + withdraw end to end.
    _, operator = await make_user_client({"global_operator"})
    roles = {role.name: role for role in await operator.list_roles()}
    assert "template:manage" in roles["global_operator"].permissions

    lab = await operator.create_lab(unique("lab"))
    _ = await operator.update_definition(lab.name, LINUX_LAB_DEFINITION)
    entry = await operator.set_lab_template(lab.name, published=True, description="op card")
    assert entry is not None and entry.source_lab == lab.name
    assert (await operator.set_lab_template(lab.name, published=False)) is None
    job = await operator.destroy_lab(lab.name, remove=True)
    _ = await operator.wait_job(lab.name, job.id, timeout=120)

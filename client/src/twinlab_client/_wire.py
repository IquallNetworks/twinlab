"""Wire parsing and serialization.

Turns decoded JSON (`object`) into the frozen models — validating shape as it
goes (a mismatch raises `TwinlabProtocolError`) — and models into JSON-ready
dicts for request bodies. This is the only layer that touches raw payloads.
"""

from datetime import datetime
from typing import cast
from uuid import UUID

from twinlab_client.errors import TwinlabProtocolError
from twinlab_client.models import (
    CONFIG_TIME_STATUSES,
    CONFIGURE_STATUSES,
    CONTAINER_STATES,
    DEPLOY_STATUSES,
    DESTROY_STATUSES,
    DEVICE_ROLES,
    DURATION_UNITS,
    JOB_KINDS,
    JOB_STATUSES,
    LAB_STATUSES,
    LINK_OPER_STATES,
    NODE_CONFIG_STATUSES,
    PARSE_MODES,
    PRINCIPAL_TYPES,
    QUARANTINE_CLASSES,
    READINESS_STATUSES,
    ROLE_SCOPES,
    SUITE_STAGES,
    TEMPLATE_TIERS,
    TEST_STATUSES,
    ApiKey,
    ApiKeyCreated,
    BuiltinTemplate,
    CatalogDevice,
    ConfigDiffReport,
    ConfigureResponse,
    CustomConfigResponse,
    DeployResponse,
    DestroyResponse,
    DeviceCatalog,
    Duration,
    Grant,
    GroupMember,
    GroupSummary,
    ImportWarning,
    Job,
    JobError,
    JobEvent,
    JobKind,
    LabActionResponse,
    LabDetail,
    LabEvent,
    LabFacts,
    LabLayout,
    LabLink,
    LabLinks,
    LabNodeState,
    LabOwner,
    LabSummary,
    LayoutGroupStyle,
    LayoutPosition,
    LinkEndpoint,
    Liveness,
    NetemImpairment,
    NetworkImport,
    NetworkTemplate,
    NetworkTemplateSummary,
    NodeConfigDiff,
    NodeConfigResult,
    NodeImport,
    NodeInterface,
    NodeInterfaces,
    NodeLogsResponse,
    NodeTemplate,
    Principal,
    Principals,
    QuarantineEntry,
    Readiness,
    Role,
    RoleScope,
    SaveConfigResponse,
    SshAccess,
    SshKey,
    SshKeyGenerated,
    SuiteReport,
    TestCase,
    TestExpectation,
    TestResult,
    TestSuite,
    TestSuitesResponse,
    UserInfo,
    UserSummary,
    ValidationTest,
)

# --------------------------------------------------------------------------- #
# Typed extraction primitives
# --------------------------------------------------------------------------- #


def as_object(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TwinlabProtocolError(where, f"expected object, got {type(value).__name__}")
    return cast("dict[str, object]", value)


def as_list(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise TwinlabProtocolError(where, f"expected array, got {type(value).__name__}")
    return cast("list[object]", value)


def _req(obj: dict[str, object], key: str, where: str) -> object:
    if key not in obj:
        raise TwinlabProtocolError(where, f"missing key {key!r}")
    return obj[key]


def _get_str(obj: dict[str, object], key: str, where: str) -> str:
    value = _req(obj, key, where)
    if not isinstance(value, str):
        raise TwinlabProtocolError(where, f"{key!r}: expected string, got {type(value).__name__}")
    return value


def _get_opt_str(obj: dict[str, object], key: str, where: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TwinlabProtocolError(where, f"{key!r}: expected string, got {type(value).__name__}")
    return value


def _get_bool(obj: dict[str, object], key: str, where: str) -> bool:
    value = _req(obj, key, where)
    if not isinstance(value, bool):
        raise TwinlabProtocolError(where, f"{key!r}: expected boolean, got {type(value).__name__}")
    return value


def _get_int(obj: dict[str, object], key: str, where: str) -> int:
    value = _req(obj, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TwinlabProtocolError(where, f"{key!r}: expected integer, got {type(value).__name__}")
    return value


def _get_opt_int(obj: dict[str, object], key: str, where: str) -> int | None:
    value = obj.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TwinlabProtocolError(where, f"{key!r}: expected integer, got {type(value).__name__}")
    return value


def _get_opt_bool(obj: dict[str, object], key: str, where: str) -> bool | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TwinlabProtocolError(where, f"{key!r}: expected boolean, got {type(value).__name__}")
    return value


def _get_float(obj: dict[str, object], key: str, where: str) -> float:
    value = _req(obj, key, where)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TwinlabProtocolError(where, f"{key!r}: expected number, got {type(value).__name__}")
    return float(value)


def _get_str_list(obj: dict[str, object], key: str, where: str) -> list[str]:
    values = as_list(_req(obj, key, where), where)
    for item in values:
        if not isinstance(item, str):
            raise TwinlabProtocolError(
                where, f"{key!r}: expected array of strings, got {type(item).__name__}"
            )
    return cast("list[str]", values)


def _get_str_set(obj: dict[str, object], key: str, where: str) -> set[str]:
    return set(_get_str_list(obj, key, where))


def _get_str_dict(obj: dict[str, object], key: str, where: str) -> dict[str, str]:
    entries = as_object(_req(obj, key, where), where)
    for entry_key, entry_value in entries.items():
        if not isinstance(entry_value, str):
            raise TwinlabProtocolError(
                where,
                f"{key!r}[{entry_key!r}]: expected string, got {type(entry_value).__name__}",
            )
    return cast("dict[str, str]", entries)


def _get_uuid(obj: dict[str, object], key: str, where: str) -> UUID:
    value = _get_str(obj, key, where)
    try:
        return UUID(value)
    except ValueError as exc:
        raise TwinlabProtocolError(where, f"{key!r}: not a UUID: {value!r}") from exc


def _parse_datetime(value: str, key: str, where: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise TwinlabProtocolError(where, f"{key!r}: not an ISO datetime: {value!r}") from exc


def _get_datetime(obj: dict[str, object], key: str, where: str) -> datetime:
    return _parse_datetime(_get_str(obj, key, where), key, where)


def _get_opt_datetime(obj: dict[str, object], key: str, where: str) -> datetime | None:
    value = _get_opt_str(obj, key, where)
    return None if value is None else _parse_datetime(value, key, where)


def _literal_value[T: str](value: str, key: str, where: str, allowed: tuple[T, ...]) -> T:
    for candidate in allowed:
        if value == candidate:
            return candidate
    raise TwinlabProtocolError(where, f"{key!r}: unexpected value {value!r} (allowed: {allowed})")


def _get_literal[T: str](obj: dict[str, object], key: str, where: str, allowed: tuple[T, ...]) -> T:
    return _literal_value(_get_str(obj, key, where), key, where, allowed)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


def parse_liveness(value: object) -> Liveness:
    where = "Liveness"
    obj = as_object(value, where)
    return Liveness(status=_get_literal(obj, "status", where, ("ok",)))


def parse_readiness(value: object) -> Readiness:
    where = "Readiness"
    obj = as_object(value, where)
    return Readiness(
        status=_get_literal(obj, "status", where, READINESS_STATUSES),
        checks=_get_str_dict(obj, "checks", where),
    )


# --------------------------------------------------------------------------- #
# Auth / identity
# --------------------------------------------------------------------------- #


def parse_user_info(value: object) -> UserInfo:
    where = "UserInfo"
    obj = as_object(value, where)
    return UserInfo(
        username=_get_str(obj, "username", where),
        roles=_get_str_set(obj, "roles", where),
        permissions=_get_str_set(obj, "permissions", where),
    )


def parse_user_summary(value: object) -> UserSummary:
    where = "UserSummary"
    obj = as_object(value, where)
    return UserSummary(
        id=_get_uuid(obj, "id", where),
        username=_get_str(obj, "username", where),
        is_active=_get_bool(obj, "is_active", where),
        roles=_get_str_set(obj, "roles", where),
    )


def parse_group_summary(value: object) -> GroupSummary:
    where = "GroupSummary"
    obj = as_object(value, where)
    members: list[GroupMember] = []
    for member_value in as_list(_req(obj, "members", where), where):
        member = as_object(member_value, "GroupMember")
        members.append(
            GroupMember(
                id=_get_uuid(member, "id", "GroupMember"),
                username=_get_str(member, "username", "GroupMember"),
            )
        )
    return GroupSummary(
        id=_get_uuid(obj, "id", where),
        name=_get_str(obj, "name", where),
        description=_get_str(obj, "description", where),
        members=members,
        roles=_get_str_set(obj, "roles", where),
    )


def parse_role(value: object) -> Role:
    where = "Role"
    obj = as_object(value, where)
    scopes: set[RoleScope] = {
        _literal_value(scope, "scopes", where, ROLE_SCOPES)
        for scope in _get_str_list(obj, "scopes", where)
    }
    return Role(
        name=_get_str(obj, "name", where),
        scopes=scopes,
        permissions=_get_str_set(obj, "permissions", where),
    )


def parse_api_key(value: object) -> ApiKey:
    where = "ApiKey"
    obj = as_object(value, where)
    return ApiKey(
        id=_get_uuid(obj, "id", where),
        name=_get_str(obj, "name", where),
        created_at=_get_datetime(obj, "created_at", where),
        last_used_at=_get_opt_datetime(obj, "last_used_at", where),
    )


def parse_api_key_created(value: object) -> ApiKeyCreated:
    where = "ApiKeyCreated"
    obj = as_object(value, where)
    return ApiKeyCreated(
        key=_get_str(obj, "key", where),
        info=parse_api_key(_req(obj, "info", where)),
    )


def parse_ssh_key(value: object) -> SshKey:
    where = "SshKey"
    obj = as_object(value, where)
    return SshKey(
        id=_get_uuid(obj, "id", where),
        name=_get_str(obj, "name", where),
        algorithm=_get_str(obj, "algorithm", where),
        fingerprint=_get_str(obj, "fingerprint", where),
        comment=_get_opt_str(obj, "comment", where),
        created_at=_get_datetime(obj, "created_at", where),
        last_used_at=_get_opt_datetime(obj, "last_used_at", where),
    )


def parse_ssh_key_generated(value: object) -> SshKeyGenerated:
    where = "SshKeyGenerated"
    obj = as_object(value, where)
    return SshKeyGenerated(
        private_key=_get_str(obj, "private_key", where),
        info=parse_ssh_key(_req(obj, "info", where)),
    )


def parse_ssh_access(value: object) -> SshAccess:
    where = "SshAccess"
    obj = as_object(value, where)
    return SshAccess(
        enabled=_get_bool(obj, "enabled", where),
        host=_get_opt_str(obj, "host", where),
        port=_get_opt_int(obj, "port", where),
        user=_get_opt_str(obj, "user", where),
    )


def parse_catalog_device(value: object) -> CatalogDevice:
    where = "CatalogDevice"
    obj = as_object(value, where)
    return CatalogDevice(
        device=_get_str(obj, "device", where),
        label=_get_str(obj, "label", where),
        role=_get_literal(obj, "role", where, DEVICE_ROLES),
        modules=_get_str_list(obj, "modules", where),
        image=_get_str(obj, "image", where),
        image_present=_get_opt_bool(obj, "image_present", where),
        config_import=_get_bool(obj, "config_import", where),
    )


def parse_device_catalog(value: object) -> DeviceCatalog:
    where = "DeviceCatalog"
    obj = as_object(value, where)
    return DeviceCatalog(
        devices=[parse_catalog_device(v) for v in as_list(_req(obj, "devices", where), where)],
        live=_get_bool(obj, "live", where),
    )


def parse_network_template_summary(value: object) -> NetworkTemplateSummary:
    where = "NetworkTemplateSummary"
    obj = as_object(value, where)
    return NetworkTemplateSummary(
        name=_get_str(obj, "name", where),
        tier=_get_literal(obj, "tier", where, TEMPLATE_TIERS),
        description=_get_str(obj, "description", where),
        source_lab=_get_opt_str(obj, "source_lab", where),
    )


def parse_network_template(value: object) -> NetworkTemplate:
    where = "NetworkTemplate"
    obj = as_object(value, where)
    return NetworkTemplate(
        name=_get_str(obj, "name", where),
        tier=_get_literal(obj, "tier", where, TEMPLATE_TIERS),
        description=_get_str(obj, "description", where),
        source_lab=_get_opt_str(obj, "source_lab", where),
        content=_get_str(obj, "content", where),
    )


def parse_node_template(value: object) -> NodeTemplate:
    where = "NodeTemplate"
    obj = as_object(value, where)
    return NodeTemplate(
        name=_get_str(obj, "name", where),
        tier=_get_literal(obj, "tier", where, TEMPLATE_TIERS),
        description=_get_str(obj, "description", where),
        device=_get_str(obj, "device", where),
        content=_get_str(obj, "content", where),
    )


def _get_opt_str_dict(obj: dict[str, object], key: str, where: str) -> dict[str, str | None]:
    raw = as_object(_req(obj, key, where), where)
    result: dict[str, str | None] = {}
    for name, value in raw.items():
        if value is not None and not isinstance(value, str):
            raise TwinlabProtocolError(
                where, f"{key!r}[{name!r}]: expected string or null, got {type(value).__name__}"
            )
        result[name] = value
    return result


def parse_quarantine_entry(value: object) -> QuarantineEntry:
    where = "QuarantineEntry"
    obj = as_object(value, where)
    return QuarantineEntry(
        reason=_get_literal(obj, "reason", where, QUARANTINE_CLASSES),
        content=_get_str(obj, "content", where),
    )


def parse_import_warning(value: object) -> ImportWarning:
    where = "ImportWarning"
    obj = as_object(value, where)
    return ImportWarning(
        node=_get_opt_str(obj, "node", where), message=_get_str(obj, "message", where)
    )


def parse_network_import(value: object) -> NetworkImport:
    where = "NetworkImport"
    obj = as_object(value, where)
    interface_map_raw = as_object(_req(obj, "interface_map", where), f"{where}.interface_map")
    interface_map = {
        node: _get_str_dict(interface_map_raw, node, f"{where}.interface_map")
        for node in interface_map_raw
    }
    quarantine_raw = as_object(_req(obj, "quarantine", where), f"{where}.quarantine")
    quarantine = {
        node: [
            parse_quarantine_entry(entry)
            for entry in as_list(entries, f"{where}.quarantine[{node!r}]")
        ]
        for node, entries in quarantine_raw.items()
    }
    return NetworkImport(
        definition=_get_str(obj, "definition", where),
        custom_config=_get_str_dict(obj, "custom_config", where),
        interface_map=interface_map,
        name_map=_get_str_dict(obj, "name_map", where),
        quarantine=quarantine,
        warnings=[parse_import_warning(v) for v in as_list(_req(obj, "warnings", where), where)],
    )


def parse_node_import(value: object) -> NodeImport:
    where = "NodeImport"
    obj = as_object(value, where)
    return NodeImport(
        fragment=_get_str(obj, "fragment", where),
        config=_get_str(obj, "config", where),
        interfaces=_get_opt_str_dict(obj, "interfaces", where),
        quarantine=[
            parse_quarantine_entry(v) for v in as_list(_req(obj, "quarantine", where), where)
        ],
        warnings=[parse_import_warning(v) for v in as_list(_req(obj, "warnings", where), where)],
    )


def parse_node_config_diff(value: object) -> NodeConfigDiff:
    where = "NodeConfigDiff"
    obj = as_object(value, where)
    return NodeConfigDiff(
        node=_get_str(obj, "node", where),
        matched=_get_int(obj, "matched", where),
        missing=_get_str_list(obj, "missing", where),
        extra=_get_str_list(obj, "extra", where),
        quarantined=_get_int(obj, "quarantined", where),
    )


def parse_config_diff_report(value: object) -> ConfigDiffReport:
    where = "ConfigDiffReport"
    obj = as_object(value, where)
    return ConfigDiffReport(
        nodes=[parse_node_config_diff(v) for v in as_list(_req(obj, "nodes", where), where)]
    )


def parse_principal(value: object) -> Principal:
    where = "Principal"
    obj = as_object(value, where)
    return Principal(id=_get_uuid(obj, "id", where), name=_get_str(obj, "name", where))


def parse_opt_principal(value: object) -> Principal | None:
    return None if value is None else parse_principal(value)


def parse_lab_owner(value: object) -> LabOwner:
    where = "LabOwner"
    obj = as_object(value, where)
    return LabOwner(
        lab=_get_str(obj, "lab", where),
        owner=parse_principal(_req(obj, "owner", where)),
    )


def parse_principals(value: object) -> Principals:
    where = "Principals"
    obj = as_object(value, where)
    return Principals(
        users=[parse_principal(v) for v in as_list(_req(obj, "users", where), where)],
        groups=[parse_principal(v) for v in as_list(_req(obj, "groups", where), where)],
    )


def parse_grant(value: object) -> Grant:
    where = "Grant"
    obj = as_object(value, where)
    return Grant(
        id=_get_uuid(obj, "id", where),
        principal_type=_get_literal(obj, "principal_type", where, PRINCIPAL_TYPES),
        principal_id=_get_uuid(obj, "principal_id", where),
        principal_name=_get_opt_str(obj, "principal_name", where),
        role=_get_str(obj, "role", where),
    )


# --------------------------------------------------------------------------- #
# Labs
# --------------------------------------------------------------------------- #


def parse_lab_node_state(value: object) -> LabNodeState:
    where = "LabNodeState"
    obj = as_object(value, where)
    return LabNodeState(
        name=_get_str(obj, "name", where),
        container=_get_str(obj, "container", where),
        image=_get_str(obj, "image", where),
        state=_get_literal(obj, "state", where, CONTAINER_STATES),
        mgmt_ip=_get_str(obj, "mgmt_ip", where),
    )


def parse_lab_summary(value: object) -> LabSummary:
    where = "LabSummary"
    obj = as_object(value, where)
    return LabSummary(
        name=_get_str(obj, "name", where),
        status=_get_literal(obj, "status", where, LAB_STATUSES),
        owner=parse_opt_principal(_req(obj, "owner", where)),
        created_at=_get_datetime(obj, "created_at", where),
        updated_at=_get_datetime(obj, "updated_at", where),
        nodes=_get_int(obj, "nodes", where),
        nodes_running=_get_int(obj, "nodes_running", where),
        config_time_status=_get_literal(obj, "config_time_status", where, CONFIG_TIME_STATUSES),
        definition_drifted=_get_opt_bool(obj, "definition_drifted", where),
        permissions=_get_str_set(obj, "permissions", where),
    )


def parse_lab_detail(value: object) -> LabDetail:
    where = "LabDetail"
    obj = as_object(value, where)
    return LabDetail(
        name=_get_str(obj, "name", where),
        status=_get_literal(obj, "status", where, LAB_STATUSES),
        definition=_get_opt_str(obj, "definition", where),
        deployed_definition=_get_opt_str(obj, "deployed_definition", where),
        definition_drifted=_get_opt_bool(obj, "definition_drifted", where),
        owner=parse_opt_principal(_req(obj, "owner", where)),
        created_at=_get_datetime(obj, "created_at", where),
        updated_at=_get_datetime(obj, "updated_at", where),
        nodes=[parse_lab_node_state(v) for v in as_list(_req(obj, "nodes", where), where)],
        config_time_status=_get_literal(obj, "config_time_status", where, CONFIG_TIME_STATUSES),
        permissions=_get_str_set(obj, "permissions", where),
        template_published=_get_bool(obj, "template_published", where),
    )


def parse_node_config_result(value: object) -> NodeConfigResult:
    where = "NodeConfigResult"
    obj = as_object(value, where)
    return NodeConfigResult(
        node=_get_str(obj, "node", where),
        status=_get_literal(obj, "status", where, NODE_CONFIG_STATUSES),
        changed=_get_int(obj, "changed", where),
        failed=_get_int(obj, "failed", where),
    )


def _parse_opt_configuration(value: object, where: str) -> list[NodeConfigResult] | None:
    return None if value is None else [parse_node_config_result(v) for v in as_list(value, where)]


def _parse_opt_validation(value: object, where: str) -> list[SuiteReport] | None:
    return None if value is None else [parse_suite_report(v) for v in as_list(value, where)]


def parse_deploy_response(value: object) -> DeployResponse:
    where = "DeployResponse"
    obj = as_object(value, where)
    return DeployResponse(
        status=_get_literal(obj, "status", where, DEPLOY_STATUSES),
        lab_name=_get_str(obj, "lab_name", where),
        nodes=_get_str_list(obj, "nodes", where),
        configuration=_parse_opt_configuration(_req(obj, "configuration", where), where),
        validation=_parse_opt_validation(_req(obj, "validation", where), where),
    )


def parse_configure_response(value: object) -> ConfigureResponse:
    where = "ConfigureResponse"
    obj = as_object(value, where)
    return ConfigureResponse(
        status=_get_literal(obj, "status", where, CONFIGURE_STATUSES),
        lab_name=_get_str(obj, "lab_name", where),
        configuration=[
            parse_node_config_result(v) for v in as_list(_req(obj, "configuration", where), where)
        ],
        validation=_parse_opt_validation(_req(obj, "validation", where), where),
    )


def parse_destroy_response(value: object) -> DestroyResponse:
    where = "DestroyResponse"
    obj = as_object(value, where)
    return DestroyResponse(
        status=_get_literal(obj, "status", where, DESTROY_STATUSES),
        detail=_get_str(obj, "detail", where),
    )


def parse_lab_action_response(value: object) -> LabActionResponse:
    where = "LabActionResponse"
    obj = as_object(value, where)
    return LabActionResponse(message=_get_str(obj, "message", where))


def parse_save_config_response(value: object) -> SaveConfigResponse:
    where = "SaveConfigResponse"
    obj = as_object(value, where)
    return SaveConfigResponse(
        message=_get_str(obj, "message", where),
        output=_get_str(obj, "output", where),
    )


def parse_node_logs_response(value: object) -> NodeLogsResponse:
    where = "NodeLogsResponse"
    obj = as_object(value, where)
    return NodeLogsResponse(
        node=_get_str(obj, "node", where),
        container=_get_str(obj, "container", where),
        logs=_get_str(obj, "logs", where),
    )


def parse_node_interfaces(value: object) -> NodeInterfaces:
    where = "NodeInterfaces"
    obj = as_object(value, where)
    interfaces: list[NodeInterface] = []
    for interface_value in as_list(_req(obj, "interfaces", where), where):
        interface = as_object(interface_value, "NodeInterface")
        interfaces.append(
            NodeInterface(
                name=_get_str(interface, "name", "NodeInterface"),
                alias=_get_str(interface, "alias", "NodeInterface"),
                ifindex=_get_int(interface, "ifindex", "NodeInterface"),
                mac=_get_str(interface, "mac", "NodeInterface"),
                mtu=_get_int(interface, "mtu", "NodeInterface"),
                state=_get_str(interface, "state", "NodeInterface"),
                kind=_get_str(interface, "kind", "NodeInterface"),
            )
        )
    return NodeInterfaces(node=_get_str(obj, "node", where), interfaces=interfaces)


def parse_duration(value: object) -> Duration:
    where = "Duration"
    obj = as_object(value, where)
    return Duration(
        value=_get_float(obj, "value", where),
        unit=_get_literal(obj, "unit", where, DURATION_UNITS),
    )


def parse_opt_duration(value: object) -> Duration | None:
    return None if value is None else parse_duration(value)


def parse_netem_impairment(value: object) -> NetemImpairment:
    where = "NetemImpairment"
    obj = as_object(value, where)
    return NetemImpairment(
        interface=_get_str(obj, "interface", where),
        delay=parse_opt_duration(_req(obj, "delay", where)),
        jitter=parse_opt_duration(_req(obj, "jitter", where)),
        loss=_get_float(obj, "loss", where),
        rate=_get_int(obj, "rate", where),
        corruption=_get_float(obj, "corruption", where),
    )


def parse_link_endpoint(value: object) -> LinkEndpoint:
    where = "LinkEndpoint"
    obj = as_object(value, where)
    impairment = _req(obj, "impairment", where)
    return LinkEndpoint(
        node=_get_str(obj, "node", where),
        interface=_get_str(obj, "interface", where),
        ifname=_get_str(obj, "ifname", where),
        ifindex=_get_int(obj, "ifindex", where),
        ipv4=_get_opt_str(obj, "ipv4", where),
        ipv6=_get_opt_str(obj, "ipv6", where),
        state=_get_opt_str(obj, "state", where),
        impairment=None if impairment is None else parse_netem_impairment(impairment),
    )


def parse_lab_link(value: object) -> LabLink:
    where = "LabLink"
    obj = as_object(value, where)
    return LabLink(
        index=_get_int(obj, "index", where),
        name=_get_opt_str(obj, "name", where),
        type=_get_str(obj, "type", where),
        prefix_ipv4=_get_opt_str(obj, "prefix_ipv4", where),
        prefix_ipv6=_get_opt_str(obj, "prefix_ipv6", where),
        bandwidth=_get_opt_int(obj, "bandwidth", where),
        mtu=_get_opt_int(obj, "mtu", where),
        oper_state=_get_literal(obj, "oper_state", where, LINK_OPER_STATES),
        endpoints=[
            parse_link_endpoint(item) for item in as_list(_req(obj, "endpoints", where), where)
        ],
    )


def parse_lab_links(value: object) -> LabLinks:
    where = "LabLinks"
    obj = as_object(value, where)
    return LabLinks(
        links=[parse_lab_link(item) for item in as_list(_req(obj, "links", where), where)],
        live=_get_bool(obj, "live", where),
    )


def parse_lab_layout(value: object) -> LabLayout:
    where = "LabLayout"
    obj = as_object(value, where)
    entries = as_object(_req(obj, "positions", where), where)
    positions: dict[str, LayoutPosition] = {}
    for key, entry in entries.items():
        entry_where = f"{where}.positions[{key!r}]"
        pos = as_object(entry, entry_where)
        positions[key] = LayoutPosition(
            x=_get_float(pos, "x", entry_where),
            y=_get_float(pos, "y", entry_where),
        )
    styles = as_object(_req(obj, "groups", where), where)
    groups: dict[str, LayoutGroupStyle] = {}
    for key, entry in styles.items():
        entry_where = f"{where}.groups[{key!r}]"
        style = as_object(entry, entry_where)
        groups[key] = LayoutGroupStyle(color=_get_str(style, "color", entry_where))
    return LabLayout(positions=positions, groups=groups)


def parse_lab_event(value: object) -> LabEvent:
    where = "LabEvent"
    obj = as_object(value, where)
    return LabEvent(
        lab=_get_str(obj, "lab", where),
        node=_get_opt_str(obj, "node", where),
        action=_get_str(obj, "action", where),
        timestamp=_get_str(obj, "timestamp", where),
    )


def parse_job_event(value: object) -> JobEvent:
    where = "JobEvent"
    obj = as_object(value, where)
    return JobEvent(
        lab=_get_str(obj, "lab", where),
        job_id=_get_uuid(obj, "job_id", where),
        kind=_get_literal(obj, "kind", where, JOB_KINDS),
        status=_get_literal(obj, "status", where, JOB_STATUSES),
        timestamp=_get_datetime(obj, "timestamp", where),
    )


# --------------------------------------------------------------------------- #
# Test suites
# --------------------------------------------------------------------------- #


def parse_test_expectation(value: object) -> TestExpectation:
    where = "TestExpectation"
    obj = as_object(value, where)
    compare = obj.get("compare")
    if compare is not None:
        compare = dict(as_object(compare, f"{where}.compare"))
    return TestExpectation(
        contains=_get_opt_str(obj, "contains", where),
        not_contains=_get_opt_str(obj, "not_contains", where),
        matches=_get_opt_str(obj, "matches", where),
        compare=compare,
    )


def parse_test_case(value: object) -> TestCase:
    where = "TestCase"
    obj = as_object(value, where)
    parse_mode = obj.get("parse")
    if parse_mode is not None and parse_mode not in PARSE_MODES:
        raise TwinlabProtocolError(where, f"'parse': unexpected value {parse_mode!r}")
    interactive = obj.get("interactive", False)
    if not isinstance(interactive, bool):
        raise TwinlabProtocolError(where, "'interactive': expected a bool")
    return TestCase(
        command=_get_str(obj, "command", where),
        expect=parse_test_expectation(_req(obj, "expect", where)),
        parse=parse_mode,
        interactive=interactive,
    )


def parse_validation_test(value: object) -> ValidationTest:
    where = "ValidationTest"
    obj = as_object(value, where)
    run_value = _req(obj, "run", where)
    run_obj = as_object(run_value, f"{where}.run")
    # A TestCase carries "command"; a device-keyed dict maps device -> case.
    run: TestCase | dict[str, TestCase] = (
        parse_test_case(run_value)
        if "command" in run_obj
        else {device: parse_test_case(case) for device, case in run_obj.items()}
    )
    return ValidationTest(
        nodes=_get_str_list(obj, "nodes", where),
        run=run,
        wait=_get_int(obj, "wait", where),
        description=_get_str(obj, "description", where),
    )


def parse_test_suite(value: object) -> TestSuite:
    where = "TestSuite"
    obj = as_object(value, where)
    tests = {
        name: parse_validation_test(test_value)
        for name, test_value in as_object(_req(obj, "tests", where), where).items()
    }
    return TestSuite(
        tests=tests,
        stage=_get_literal(obj, "stage", where, SUITE_STAGES),
        description=_get_str(obj, "description", where),
    )


def parse_test_result(value: object) -> TestResult:
    where = "TestResult"
    obj = as_object(value, where)
    diff = obj.get("diff")
    if diff is not None:
        diff = dict(as_object(diff, f"{where}.diff"))
    return TestResult(
        test=_get_str(obj, "test", where),
        node=_get_str(obj, "node", where),
        status=_get_literal(obj, "status", where, TEST_STATUSES),
        command=_get_str(obj, "command", where),
        output=_get_str(obj, "output", where),
        detail=_get_str(obj, "detail", where),
        diff=diff,
        elapsed_ms=_get_int(obj, "elapsed_ms", where),
    )


def parse_suite_report(value: object) -> SuiteReport:
    where = "SuiteReport"
    obj = as_object(value, where)
    return SuiteReport(
        suite=_get_str(obj, "suite", where),
        stage=_get_str(obj, "stage", where),
        passed=_get_int(obj, "passed", where),
        failed=_get_int(obj, "failed", where),
        skipped=_get_int(obj, "skipped", where),
        errored=_get_int(obj, "errored", where),
        ran_at=_get_datetime(obj, "ran_at", where),
        results=[parse_test_result(v) for v in as_list(_req(obj, "results", where), where)],
    )


def parse_test_suites_response(value: object) -> TestSuitesResponse:
    where = "TestSuitesResponse"
    obj = as_object(value, where)
    suites = {
        name: parse_test_suite(suite_value)
        for name, suite_value in as_object(_req(obj, "test_suites", where), where).items()
    }
    last_validation = {
        name: parse_suite_report(report_value)
        for name, report_value in as_object(_req(obj, "last_validation", where), where).items()
    }
    return TestSuitesResponse(
        test_suites=suites,
        last_validation=last_validation,
        config_time_status=_get_literal(obj, "config_time_status", where, CONFIG_TIME_STATUSES),
    )


def parse_lab_facts(value: object) -> LabFacts:
    where = "LabFacts"
    obj = as_object(value, where)
    nodes: dict[str, dict[str, object]] = {}
    for name, node_value in as_object(_req(obj, "nodes", where), where).items():
        nodes[name] = dict(as_object(node_value, f"{where}.nodes[{name}]"))
    return LabFacts(nodes=nodes)


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #


def parse_job_error(value: object) -> JobError:
    where = "JobError"
    obj = as_object(value, where)
    return JobError(
        status_code=_get_int(obj, "status_code", where),
        code=_get_str(obj, "code", where),
        message=_get_str(obj, "message", where),
        extras=as_object(_req(obj, "extras", where), where),
    )


def _parse_job_result(
    kind: JobKind, value: object, where: str
) -> DeployResponse | ConfigureResponse | DestroyResponse | SuiteReport | None:
    if value is None:
        return None
    if kind == "deploy":
        return parse_deploy_response(value)
    if kind == "configure":
        return parse_configure_response(value)
    if kind == "destroy":
        return parse_destroy_response(value)
    return parse_suite_report(value)


def parse_job(value: object) -> Job:
    where = "Job"
    obj = as_object(value, where)
    kind: JobKind = _get_literal(obj, "kind", where, JOB_KINDS)
    error_value = _req(obj, "error", where)
    return Job(
        id=_get_uuid(obj, "id", where),
        lab_name=_get_str(obj, "lab_name", where),
        kind=kind,
        status=_get_literal(obj, "status", where, JOB_STATUSES),
        request=as_object(_req(obj, "request", where), where),
        result=_parse_job_result(kind, _req(obj, "result", where), where),
        error=None if error_value is None else parse_job_error(error_value),
        created_at=_get_datetime(obj, "created_at", where),
        finished_at=_get_opt_datetime(obj, "finished_at", where),
    )


# --------------------------------------------------------------------------- #
# Custom config
# --------------------------------------------------------------------------- #


def parse_custom_config_response(value: object) -> CustomConfigResponse:
    where = "CustomConfigResponse"
    obj = as_object(value, where)
    builtin: list[BuiltinTemplate] = []
    for template_value in as_list(_req(obj, "builtin", where), where):
        template = as_object(template_value, "BuiltinTemplate")
        builtin.append(
            BuiltinTemplate(
                name=_get_str(template, "name", "BuiltinTemplate"),
                description=_get_str(template, "description", "BuiltinTemplate"),
                files=_get_str_dict(template, "files", "BuiltinTemplate"),
            )
        )
    return CustomConfigResponse(
        builtin=builtin,
        custom_config=_get_str_dict(obj, "custom_config", where),
    )


# --------------------------------------------------------------------------- #
# Request serialization
# --------------------------------------------------------------------------- #


def expectation_to_wire(expectation: TestExpectation) -> dict[str, object]:
    """None fields are omitted — the server checks exactly-one-of on presence."""
    wire: dict[str, object] = {}
    if expectation.contains is not None:
        wire["contains"] = expectation.contains
    if expectation.not_contains is not None:
        wire["not_contains"] = expectation.not_contains
    if expectation.matches is not None:
        wire["matches"] = expectation.matches
    if expectation.compare is not None:
        wire["compare"] = expectation.compare
    return wire


def test_case_to_wire(case: TestCase) -> dict[str, object]:
    wire: dict[str, object] = {
        "command": case.command,
        "expect": expectation_to_wire(case.expect),
        "interactive": case.interactive,
    }
    if case.parse is not None:
        wire["parse"] = case.parse
    return wire


def validation_test_to_wire(test: ValidationTest) -> dict[str, object]:
    run: dict[str, object] = (
        test_case_to_wire(test.run)
        if isinstance(test.run, TestCase)
        else {device: test_case_to_wire(case) for device, case in test.run.items()}
    )
    return {
        "nodes": list(test.nodes),
        "run": run,
        "wait": test.wait,
        "description": test.description,
    }


def test_suite_to_wire(suite: TestSuite) -> dict[str, object]:
    return {
        "tests": {name: validation_test_to_wire(test) for name, test in suite.tests.items()},
        "stage": suite.stage,
        "description": suite.description,
    }


def test_suites_to_wire(suites: dict[str, TestSuite]) -> dict[str, object]:
    return {name: test_suite_to_wire(suite) for name, suite in suites.items()}


def duration_to_wire(duration: Duration | None) -> dict[str, object] | None:
    if duration is None:
        return None
    return {"value": duration.value, "unit": duration.unit}

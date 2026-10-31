"""Parse the plugin contract's endpoints, parameters and typed errors."""

from __future__ import annotations

import re

from scripts.adoption_validation import (
    expect_bool,
    expect_closed_keys,
    expect_identifier,
    expect_object,
    expect_string,
    expect_string_tuple,
    fail,
)
from scripts.plugin_contract_model import (
    EndpointContract,
    EndpointRequest,
    EndpointRetry,
    EndpointSuccess,
    ParameterGrammar,
    TypedErrorContract,
)


def _parse_parameter(value: object, label: str) -> ParameterGrammar:
    data = expect_object(value, label)
    expect_closed_keys(data, {"name", "value_type", "required", "minimum", "maximum"}, label)
    value_type = expect_string(data.get("value_type"), f"{label}.value_type")
    if value_type not in {"opaque_id", "positive_integer"}:
        fail(f"{label}.value_type is not public grammar")
    minimum = data.get("minimum")
    maximum = data.get("maximum")
    if minimum is not None and type(minimum) is not int:
        fail(f"{label}.minimum must be an integer or null")
    if maximum is not None and type(maximum) is not int:
        fail(f"{label}.maximum must be an integer or null")
    if value_type == "positive_integer" and (
        minimum is None or minimum < 1 or (maximum is not None and maximum < minimum)
    ):
        fail(f"{label} positive integer bounds are invalid")
    if value_type == "opaque_id" and (minimum is not None or maximum is not None):
        fail(f"{label} opaque IDs may not have numeric bounds")
    return ParameterGrammar(
        name=expect_identifier(data.get("name"), f"{label}.name"),
        value_type=value_type,
        required=expect_bool(data.get("required"), f"{label}.required"),
        minimum=minimum,
        maximum=maximum,
    )


def _parse_parameter_list(value: object, label: str) -> tuple[ParameterGrammar, ...]:
    if not isinstance(value, list):
        fail(f"{label} must be a list")
    result = tuple(_parse_parameter(item, label) for item in value)
    names = tuple(item.name for item in result)
    if len(set(names)) != len(names):
        fail(f"{label} names must be unique")
    return result


def parse_endpoint(value: object) -> EndpointContract:
    data = expect_object(value, "endpoint")
    expect_closed_keys(
        data,
        {
            "endpoint_id",
            "method",
            "path",
            "principal",
            "authority",
            "request",
            "success",
            "retry",
            "timeout_policy_ref",
        },
        "endpoint",
    )
    request_data = expect_object(data.get("request"), "endpoint.request")
    expect_closed_keys(
        request_data,
        {"path_parameters", "query_parameters", "body"},
        "endpoint.request",
    )
    success_data = expect_object(data.get("success"), "endpoint.success")
    expect_closed_keys(
        success_data,
        {
            "available",
            "root_success",
            "statuses",
            "envelope",
            "required_fields",
            "revision_required_fields",
        },
        "endpoint.success",
    )
    statuses_value = success_data.get("statuses")
    if not isinstance(statuses_value, list):
        fail("success.statuses must be a list")
    statuses: list[int] = []
    for status in statuses_value:
        if type(status) is not int or status < 200 or status > 299:
            fail("success.statuses must be HTTP success status integers")
        statuses.append(status)
    raw_root_success = success_data.get("root_success")
    root_success = (
        None
        if raw_root_success is None
        else expect_bool(raw_root_success, "endpoint.success.root_success")
    )
    retry_data = expect_object(data.get("retry"), "endpoint.retry")
    expect_closed_keys(retry_data, {"mode", "identity_fields"}, "endpoint.retry")
    endpoint = EndpointContract(
        endpoint_id=expect_identifier(data.get("endpoint_id"), "endpoint.endpoint_id"),
        method=expect_string(data.get("method"), "endpoint.method"),
        path=expect_string(data.get("path"), "endpoint.path"),
        principal=expect_string(data.get("principal"), "endpoint.principal"),
        authority=expect_string(data.get("authority"), "endpoint.authority"),
        request=EndpointRequest(
            path_parameters=_parse_parameter_list(
                request_data.get("path_parameters"), "endpoint.path_parameters"
            ),
            query_parameters=_parse_parameter_list(
                request_data.get("query_parameters"), "endpoint.query_parameters"
            ),
            body=expect_string(request_data.get("body"), "endpoint.request.body"),
        ),
        success=EndpointSuccess(
            available=expect_bool(success_data.get("available"), "endpoint.success.available"),
            root_success=root_success,
            statuses=tuple(statuses),
            envelope=expect_string(success_data.get("envelope"), "endpoint.success.envelope"),
            required_fields=expect_string_tuple(
                success_data.get("required_fields"),
                "endpoint.success.required_fields",
                allow_empty=True,
            ),
            revision_required_fields=expect_string_tuple(
                success_data.get("revision_required_fields"),
                "endpoint.success.revision_required_fields",
                allow_empty=True,
            ),
        ),
        retry=EndpointRetry(
            mode=expect_string(retry_data.get("mode"), "endpoint.retry.mode"),
            identity_fields=expect_string_tuple(
                retry_data.get("identity_fields"),
                "endpoint.retry.identity_fields",
                allow_empty=True,
            ),
        ),
        timeout_policy_ref=expect_identifier(
            data.get("timeout_policy_ref"), "endpoint.timeout_policy_ref"
        ),
    )
    if endpoint.success.available:
        if (
            endpoint.success.root_success is not True
            or not endpoint.success.statuses
            or endpoint.success.envelope != "root"
            or not {"success", "data"}.issubset(endpoint.success.required_fields)
        ):
            fail("available success responses require root success=true and data envelope")
    elif (
        endpoint.success.root_success is not None
        or endpoint.success.statuses
        or endpoint.success.envelope != "blocked"
        or endpoint.success.required_fields
        or endpoint.success.revision_required_fields
    ):
        fail("blocked endpoints may not declare a reachable success response")
    if endpoint.method not in {"GET", "POST", "DELETE"}:
        fail("endpoint method is outside the public contract")
    if (
        re.fullmatch(
            r"/api/v[1-9][0-9]*(?:/[a-z0-9-]+|/\{[a-z][a-z0-9_]*\})+",
            endpoint.path,
        )
        is None
    ):
        fail("endpoint path is not versioned public REST grammar")
    placeholders = tuple(re.findall(r"\{([a-z][a-z0-9_]*)\}", endpoint.path))
    if placeholders != tuple(item.name for item in endpoint.request.path_parameters):
        fail("endpoint path parameters do not match public path placeholders")
    if endpoint.principal not in {"source_reader", "test_writer"}:
        fail("endpoint principal is not approved")
    if endpoint.method == "GET":
        if endpoint.principal != "source_reader":
            fail("GET endpoints must use source_reader")
        if endpoint.retry.mode not in {"bounded_get", "never"}:
            fail("GET retry mode must be bounded_get or never")
    else:
        if (
            endpoint.principal != "test_writer"
            or endpoint.authority != "stimulus_only"
            or endpoint.retry.mode != "never"
        ):
            fail("mutation endpoints must be non-retried test_writer stimuli")
    if any(
        operation in endpoint.endpoint_id or f"/{operation}" in endpoint.path
        for operation in ("history", "diff", "edit", "revert")
    ):
        fail("ordinary Wiki operations are excluded from the W1 plugin contract")
    return endpoint


def parse_typed_error(value: object) -> TypedErrorContract:
    data = expect_object(value, "typed error")
    expect_closed_keys(
        data,
        {
            "code",
            "reason",
            "status",
            "disposition",
            "root_success",
            "envelope",
            "required_fields",
            "error_required_fields",
            "last_committed",
            "last_committed_required_fields",
        },
        "typed error",
    )
    status = data.get("status")
    if type(status) is not int or status < 400 or status > 599:
        fail("typed error status must be an HTTP error status")
    error = TypedErrorContract(
        code=expect_identifier(data.get("code"), "typed error.code"),
        reason=expect_string(data.get("reason"), "typed error.reason"),
        status=status,
        disposition=expect_string(data.get("disposition"), "typed error.disposition"),
        root_success=expect_bool(data.get("root_success"), "typed error.root_success"),
        envelope=expect_string(data.get("envelope"), "typed error.envelope"),
        required_fields=expect_string_tuple(
            data.get("required_fields"), "typed error.required_fields"
        ),
        error_required_fields=expect_string_tuple(
            data.get("error_required_fields"),
            "typed error.error_required_fields",
        ),
        last_committed=expect_string(data.get("last_committed"), "typed error.last_committed"),
        last_committed_required_fields=expect_string_tuple(
            data.get("last_committed_required_fields"),
            "typed error.last_committed_required_fields",
            allow_empty=True,
        ),
    )
    if (
        error.root_success
        or error.envelope != "root"
        or error.required_fields != ("success", "error")
        or "code" not in error.error_required_fields
    ):
        fail("typed errors require root success=false and a typed error envelope")
    prior_commit_reasons = {"attempt_in_progress", "attempt_terminal"}
    if error.code == "revision_not_committed" and error.reason in prior_commit_reasons:
        if (
            error.last_committed != "required_when_prior_committed"
            or error.last_committed_required_fields
            != ("parse_attempt", "manifest_digest", "completed_at")
        ):
            fail("active attempts must conditionally freeze the prior committed descriptor")
    elif error.last_committed != "forbidden" or error.last_committed_required_fields:
        fail("only active attempts may expose last_committed")
    return error


def parse_string_map(value: object, label: str) -> tuple[tuple[str, str], ...]:
    data = expect_object(value, label)
    return tuple(
        (
            expect_identifier(key, f"{label} key"),
            expect_string(item, f"{label}.{key}"),
        )
        for key, item in data.items()
    )

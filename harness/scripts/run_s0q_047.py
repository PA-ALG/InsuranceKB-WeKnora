#!/usr/bin/env python3
"""One-shot OpenSpec 047 W1 input capture; no model/provider code."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import secrets
from collections.abc import Mapping, Sequence
from pathlib import Path

from insurance_harness.adapters.weknora.admin_client import (
    AdminCredentials,
    AdminSession,
    WeKnoraAdminClient,
)
from insurance_harness.live_env.compose import read_runtime_environment
from insurance_harness.s0q_047 import (
    S0QCaptureSource,
    capture_s0q_w1_inputs,
    write_s0q_capture_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
API_BASE_URL = "http://127.0.0.1:8080/api/v1"

SOURCES = (
    S0QCaptureSource(
        source_path=(
            "dataset/shouxian_product/平安e生保（尊享版）医疗保险/"
            "保险条款.pdf"
        ),
        source_bytes=1_047_811,
        source_sha256=(
            "88b784c61f52a2e21a2a12f96ba5d734"
            "12de95e68a4453af03a27e8ab1245edc"
        ),
        artifact_name="terms-w1.json",
        required_anchor_page=31,
        required_anchor_quote="免赔额",
        required_anchor_structural_type="table",
    ),
    S0QCaptureSource(
        source_path=(
            "dataset/shouxian_product/平安e生保（尊享版）医疗保险/"
            "产品说明书.pdf"
        ),
        source_bytes=492_101,
        source_sha256=(
            "5e2aef32d319b5aca6d37268e99ee525"
            "2ea0c7a56885b1e4dfa1ebb0308e4279"
        ),
        artifact_name="brochure-w1.json",
        required_anchor_page=1,
        required_anchor_quote="产品特色",
        required_anchor_structural_type="text",
    ),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture the exact two-source S0-Q W1 input bundle.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture = subcommands.add_parser("capture")
    capture.add_argument("--runtime-env", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--api-base-url", default=API_BASE_URL)
    capture.add_argument("--raw-kb-id")
    capture.add_argument("--poll-attempts", type=int, default=180)
    capture.add_argument("--poll-interval-seconds", type=float, default=2.0)
    return parser


async def _session(
    client: WeKnoraAdminClient,
    values: Mapping[str, str],
) -> AdminSession:
    session = await client.bootstrap_admin(
        AdminCredentials(
            username=values["WEKNORA_ADMIN_USERNAME"],
            email=values["WEKNORA_ADMIN_EMAIL"],
            password=values["WEKNORA_ADMIN_PASSWORD"],
        )
    )
    recorded_tenant = values.get("LOCAL_LIVE_TENANT_ID")
    if recorded_tenant is not None:
        if not recorded_tenant.isdecimal() or int(recorded_tenant) <= 0:
            raise ValueError("runtime tenant identity is invalid")
        tenant_id = int(recorded_tenant)
        if session.tenant_id != tenant_id:
            session = await client.switch_tenant(session, tenant_id)
    return session


async def _scratch_payload(
    client: WeKnoraAdminClient,
    session: AdminSession,
    values: Mapping[str, str],
    raw_kb_override: str | None,
) -> dict[str, object]:
    raw_kb_id = raw_kb_override or values.get("LOCAL_LIVE_RAW_KB_ID")
    if not isinstance(raw_kb_id, str) or not raw_kb_id:
        raise ValueError("runtime RAW knowledge-base identity is unavailable")
    matches = [
        item
        for item in await client.list_knowledge_bases(session)
        if item.get("id") == raw_kb_id
    ]
    if len(matches) != 1:
        raise ValueError("runtime RAW knowledge-base identity is unavailable")
    raw = matches[0]
    embedding_model_id = raw.get("embedding_model_id")
    vlm_config = raw.get("vlm_config")
    if (
        not isinstance(embedding_model_id, str)
        or not embedding_model_id
        or not isinstance(vlm_config, Mapping)
    ):
        raise ValueError("runtime RAW parsing profile is incomplete")
    payload: dict[str, object] = {
        "name": f"insurancekb-s0q-047-scratch-{secrets.token_hex(6)}",
        "description": json.dumps(
            {"owner": "s0q-047", "purpose": "w1-input-capture"},
            separators=(",", ":"),
            sort_keys=True,
        ),
        "type": "document",
        "embedding_model_id": embedding_model_id,
        "vlm_config": copy.deepcopy(dict(vlm_config)),
    }
    indexing_strategy = raw.get("indexing_strategy")
    if isinstance(indexing_strategy, Mapping):
        payload["indexing_strategy"] = copy.deepcopy(dict(indexing_strategy))
    return payload


async def _capture(namespace: argparse.Namespace) -> int:
    client: WeKnoraAdminClient | None = None
    try:
        values = read_runtime_environment(namespace.runtime_env)
        client = WeKnoraAdminClient(namespace.api_base_url)
        session = await _session(client, values)
        payload = await _scratch_payload(
            client,
            session,
            values,
            namespace.raw_kb_id,
        )
        report = await capture_s0q_w1_inputs(
            client=client,
            session=session,
            source_root=REPO_ROOT,
            output_dir=namespace.output,
            sources=SOURCES,
            scratch_kb_payload=payload,
            poll_attempts=namespace.poll_attempts,
            poll_interval_seconds=namespace.poll_interval_seconds,
        )
    except Exception as exc:
        report = {
            "artifact_kind": "s0q_047_input_capture_report",
            "status": "BLOCKED_ON_INPUT",
            "bucket": "input_integrity",
            "reason": (
                "environment preflight failed closed at "
                f"{type(exc).__name__}"
            ),
            "scratch": {
                "knowledge_base_id": None,
                "knowledge_ids": [],
                "cleanup": {
                    "api_key": "not_created",
                    "knowledge_base": "not_created",
                },
            },
            "input_manifest_digest": None,
            "harness_model_provider_calls": 0,
        }
        write_s0q_capture_report(namespace.output, report)
    finally:
        if client is not None:
            await client.aclose()
    print(
        json.dumps(
            {
                "status": report["status"],
                "bucket": report["bucket"],
                "reason": report["reason"],
                "report": str(namespace.output / "input-capture-report.json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "ADMITTED" else 2


def main(argv: Sequence[str] | None = None) -> int:
    namespace = _parser().parse_args(argv)
    if namespace.command == "capture":
        return asyncio.run(_capture(namespace))
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())

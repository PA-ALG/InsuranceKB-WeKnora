"""Validation-only CLI for external OpenSpec 030 admission artifacts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from insurance_harness.model_policy import AdmissionPolicyDenied, StrictAdmissionRequestBinding

from . import evaluator
from .models import MvpAdmissionPlan, _validate_exact_raw_mvp_plan
from .profiles.mvp import validate_mvp_plan


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    value: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in value:
            raise ValueError("duplicate mapping key")
        value[key] = loader.construct_object(value_node, deep=deep)
    return value


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _load_mapping(path: Path) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("input must be a regular file")
    payload = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(payload, object_pairs_hook=_reject_duplicate_json_keys)
    else:
        value = yaml.load(payload, Loader=_UniqueKeyLoader)
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError("input must contain a string-keyed mapping")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m insurance_harness.run_admission.cli",
        description="Render unsigned MVP payloads or validate an external request.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render-unsigned")
    render.add_argument("--plan", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "render-unsigned":
            raw_plan = _load_mapping(args.plan)
            plan = validate_mvp_plan(
                MvpAdmissionPlan.model_validate(_validate_exact_raw_mvp_plan(raw_plan))
            )
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(plan.model_dump_json(indent=2))
                stream.write("\n")
            return 0
        request_payload = evaluator._read_external_request(args.request)
        request_raw = yaml.load(
            request_payload.decode("utf-8"),
            Loader=_UniqueKeyLoader,
        )
        if not isinstance(request_raw, dict):
            raise ValueError("request must be a JSON mapping")
        request = StrictAdmissionRequestBinding.model_validate(request_raw)
        decision = evaluator.evaluate_admission(request)
        print(decision.model_dump_json())
        return 0 if decision.state == "READY" else 2
    except (
        AdmissionPolicyDenied,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        ValidationError,
        yaml.YAMLError,
    ):
        print(
            json.dumps(
                {"state": "BLOCKED", "reason_code": "invalid_cli_input"},
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]

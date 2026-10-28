"""Prepare a judge run: change points, material text and hash-checked requests (RV7 Spec §2.1).

Everything is read and built in memory first; only then does prepare write, into a fresh run
root outside any Git repository, without overwriting a file. Products go whole into sessions in
id order, so the same inputs always give the same sessions and requests; a product larger than a
session is refused rather than split. Material files are named by their identity (knowledge id
and parse attempt), never by their original names. Starting the judge sessions is the operator's
step: this module only writes `run.sh`.
"""

from __future__ import annotations

import json
import shlex
from importlib.resources import files
from pathlib import Path
from typing import Any

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.changes.options import registry_inputs
from insurance_harness.compilers.schema_fields.cards import card_payload, cards_version
from insurance_harness.compilers.schema_fields.definitions import pack_definitions
from insurance_harness.compilers.schema_fields.publish import REPO
from insurance_harness.eval.judge import JudgeRequest
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.ingest.judge_batch.manifest import (
    MANIFEST,
    check_fresh,
    preflight,
    write_json,
    write_session,
)
from insurance_harness.ingest.judge_batch.points import (
    JudgeBatchError,
    ProductChanges,
    Rebuilt,
    product_changes,
    rebuild,
)
from insurance_harness.ingest.source_map import PageReader


def prompt() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        files(__package__).joinpath("prompt.json").read_text(encoding="utf-8")
    )
    return data


def _source_text(pages: list[PageText]) -> str:
    return "\n".join(f"[page {page.page}]\n{page.text}" for page in pages)


def _sessions(changes: list[ProductChanges], per_session: int) -> dict[str, list[ProductChanges]]:
    sessions: dict[str, list[ProductChanges]] = {}
    current: list[ProductChanges] = []
    size = 0
    for product in sorted(changes, key=lambda item: item.product):
        if not product.points:
            continue
        if len(product.points) > per_session:
            raise JudgeBatchError("PRODUCT_TOO_LARGE")
        if current and size + len(product.points) > per_session:
            sessions[f"s{len(sessions) + 1:02d}"] = current
            current, size = [], 0
        current.append(product)
        size += len(product.points)
    if current:
        sessions[f"s{len(sessions) + 1:02d}"] = current
    return sessions


def _requests(
    product: ProductChanges, per_request: int, system: str, repo: Path
) -> list[JudgeRequest]:
    try:
        catalog = pack_definitions(
            repo / SCHEMA_PACK_CATALOG, product.pack, only_source_extractable=False
        )
    except (OSError, KeyError, ValueError):
        raise JudgeBatchError("PACK_UNKNOWN") from None
    definitions = {item.field_key: item for item in catalog}
    shown = []
    for point in product.points:
        definition = definitions.get(point.field_key)
        if definition is None:
            raise JudgeBatchError("FIELD_UNKNOWN")
        shown.append(
            {
                "slug": point.slug,
                "field_key": point.field_key,
                "title": definition.short_title,
                "description": definition.description,
                "source_guidance": definition.source_guidance,
                "card": card_payload(definition, examples=False),
                "change": point.change,
                "live": None if point.live is None else point.live.model_dump(),
                "new": point.new.model_dump(),
            }
        )
    materials = [{"document": m.document, "file": m.file} for m in product.materials]
    return [
        JudgeRequest(
            system,
            json.dumps(
                {
                    "product": product.product,
                    "name": product.name,
                    "pack": product.pack,
                    "materials": materials,
                    "points": shown[start : start + per_request],
                },
                ensure_ascii=False,
                indent=1,
            ),
        )
        for start in range(0, len(shown), per_request)
    ]


def _run_script(run_root: Path, sessions: list[str], model: str, operator_prompt: str) -> str:
    lines = [
        "#!/bin/zsh",
        "# Operator step (RV7 Spec §1): one independent judge session per directory, in parallel.",
        "# Each session can write only its own directory; the run root stays the trusted record.",
        f"run={shlex.quote(str(run_root))}",
        'mkdir -p "$run/logs"',
        f"prompt={shlex.quote(operator_prompt)}",
    ]
    for session in sessions:
        lines.append(
            f"(codex exec -m {shlex.quote(model)} -c model_reasoning_effort='\"xhigh\"' "
            f'--skip-git-repo-check -s workspace-write -C "$run/sessions/{session}" '
            f'-o "$run/logs/{session}.last.txt" "$prompt" < /dev/null '
            f'> "$run/logs/{session}.codex.log" 2>&1; '
            f'echo "{session} exit=$?" >> "$run/logs/status.txt") &'
        )
    lines.append("wait")
    return "\n".join(lines) + "\n"


def _session_texts(
    members: list[ProductChanges], rebuilt: dict[str, Rebuilt], rules: dict[str, Any]
) -> dict[str, str]:
    texts = {"AGENTS.md": "\n".join(rules["rules"]) + "\n"}
    for changes in members:
        pages = rebuilt[changes.product].pages
        for material in changes.materials:
            texts[material.file] = _source_text(pages[(material.knowledge_id, material.attempt)])
    return texts


def prepare(
    run_root: Path,
    *,
    registry: Path,
    compile_root: Path,
    products: list[str],
    reader: PageReader,
    client: PlatformClient,
    policy_ref: str,
    reviewer: str,
    model: str,
    points_per_session: int = 40,
    points_per_request: int = 12,
    repo: Path = REPO,
) -> dict[str, Any]:
    """Read-only on the platform; refuses a run root that holds anything."""
    check_fresh(run_root)
    if (
        not (policy_ref.strip() and reviewer.strip() and model.strip() and products)
        or min(points_per_session, points_per_request) < 1
    ):
        raise JudgeBatchError("INVALID_ARGUMENTS")
    rules = prompt()
    first = sorted(set(products))
    # The registry rejects unknown products before any remote read.
    space_id = registry_inputs(registry, first)[0].space_id
    active = client.active(space_id)
    rebuilt = {
        product_id: rebuild(
            product_id, registry=registry, compile_root=compile_root, reader=reader, active=active
        )
        for product_id in first
    }
    collected = [product_changes(rebuilt[product_id], active) for product_id in first]
    system = "\n".join(rules["system"])
    planned: dict[str, tuple[list[JudgeRequest], dict[str, str], list[ProductChanges]]] = {}
    for session, members in _sessions(collected, points_per_session).items():
        requests = [
            request
            for changes in members
            for request in _requests(changes, points_per_request, system, repo)
        ]
        planned[session] = (requests, _session_texts(members, rebuilt, rules), members)
    targets = [
        run_root / "sessions" / session / name
        for session, (_, texts, _) in planned.items()
        for name in texts
    ]
    preflight(run_root, targets)
    listed: dict[str, Any] = {}
    plan_sessions: dict[str, dict[str, list[str]]] = {}
    for session, (requests, texts, members) in planned.items():
        plan_sessions[session] = {
            "products": [changes.product for changes in members],
            "slugs": sorted(point.slug for changes in members for point in changes.points),
        }
        texts["run.json"] = json.dumps({"session": session, **plan_sessions[session]}) + "\n"
        written = write_session(run_root / "sessions" / session, requests, texts)
        listed[session] = {"files": written}
    for changes in collected:
        write_json(run_root / "data" / f"changes-{changes.product}.json", changes.model_dump())
    write_json(
        run_root / MANIFEST,
        {
            "sessions": listed,
            "materials": {c.product: [m.model_dump() for m in c.materials] for c in collected},
        },
    )
    plan = {
        "products": first,
        "space_id": space_id,
        "active": None if active is None else {"release": active.id, "epoch": active.epoch},
        "cards_version": cards_version(),
        "prompt_version": rules["version"],
        "policy_ref": policy_ref,
        "reviewer": reviewer,
        "model": model,
        "basis": {product_id: rebuilt[product_id].basis for product_id in first},
        "sessions": plan_sessions,
    }
    script = run_root / "run.sh"
    script.write_text(
        _run_script(run_root, sorted(plan_sessions), model, rules["operator_prompt"]),
        encoding="utf-8",
    )
    script.chmod(0o755)
    write_json(run_root / "plan.json", plan)
    return plan

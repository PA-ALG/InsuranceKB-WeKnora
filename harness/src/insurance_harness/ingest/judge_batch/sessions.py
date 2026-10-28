"""Prepare a judge run: change points, material text and hash-checked requests (RV7 Spec §2.1).

Everything the judge reads is written under the run root, outside any Git repository. Products go
whole into sessions in id order, so the same inputs always give the same sessions and requests.
Starting the judge sessions is the operator's step: this module only writes `run.sh`.
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
from insurance_harness.eval.judge_files import check_run_directory, write_requests
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.ingest.judge_batch.points import (
    JudgeBatchError,
    ProductChanges,
    material_pages,
    product_changes,
    rebuild,
)
from insurance_harness.ingest.source_map import PageReader


def prompt() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        files(__package__).joinpath("prompt.json").read_text(encoding="utf-8")
    )
    return data


def write_json(path: Path, data: object) -> None:
    """Write a whole file at once, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(path)


def check_run_root(run_root: Path) -> None:
    try:
        check_run_directory(run_root)
    except ValueError:
        raise JudgeBatchError("RUN_ROOT_IN_GIT") from None


def _source_text(pages: list[PageText]) -> str:
    return "\n".join(f"[page {page.page}]\n{page.text}" for page in pages)


def _sessions(changes: list[ProductChanges], per_session: int) -> dict[str, list[ProductChanges]]:
    sessions: dict[str, list[ProductChanges]] = {}
    current: list[ProductChanges] = []
    size = 0
    for product in sorted(changes, key=lambda item: item.product):
        if not product.points:
            continue
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
    return [
        JudgeRequest(
            system,
            json.dumps(
                {
                    "product": product.product,
                    "name": product.name,
                    "pack": product.pack,
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


def _write_session(
    session_dir: Path,
    members: list[ProductChanges],
    texts: dict[str, dict[str, list[PageText]]],
    rules: dict[str, Any],
    per_request: int,
    repo: Path,
) -> dict[str, list[str]]:
    system = "\n".join(rules["system"])
    requests: list[JudgeRequest] = []
    for changes in members:
        requests.extend(_requests(changes, per_request, system, repo))
        for rows in texts[changes.product].values():
            if rows:
                target = (
                    session_dir
                    / "sources"
                    / changes.product
                    / (Path(rows[0].document).stem + ".txt")
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_source_text(rows), encoding="utf-8")
    write_requests(requests, session_dir)
    (session_dir / "AGENTS.md").write_text("\n".join(rules["rules"]) + "\n", encoding="utf-8")
    slugs = sorted(point.slug for changes in members for point in changes.points)
    return {"products": [changes.product for changes in members], "slugs": slugs}


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
    """Read-only on the platform; refuses a run root that was already prepared."""
    check_run_root(run_root)
    if (run_root / "plan.json").exists():
        raise JudgeBatchError("RUN_EXISTS")
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
    collected: list[ProductChanges] = []
    texts: dict[str, dict[str, list[PageText]]] = {}
    for product_id in first:
        rebuilt = rebuild(
            product_id, registry=registry, compile_root=compile_root, reader=reader, active=active
        )
        material = material_pages(reader, rebuilt.space_id, rebuilt.entries)
        collected.append(product_changes(rebuilt, active, material))
        texts[product_id] = material
    plan_sessions: dict[str, dict[str, list[str]]] = {}
    for session, members in _sessions(collected, points_per_session).items():
        plan_sessions[session] = _write_session(
            run_root / "sessions" / session, members, texts, rules, points_per_request, repo
        )
        write_json(
            run_root / "sessions" / session / "run.json",
            {"session": session, **plan_sessions[session]},
        )
    for changes in collected:
        write_json(run_root / "data" / f"changes-{changes.product}.json", changes.model_dump())
    plan = {
        "products": first,
        "space_id": space_id,
        "active": None if active is None else {"release": active.id, "epoch": active.epoch},
        "cards_version": cards_version(),
        "prompt_version": rules["version"],
        "policy_ref": policy_ref,
        "reviewer": reviewer,
        "model": model,
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

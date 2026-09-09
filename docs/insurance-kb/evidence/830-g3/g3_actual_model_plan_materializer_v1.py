#!/usr/bin/env python3
"""Offline materializer for reviewed G3 bounded model stage plans."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import unicodedata
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)


def _select_worktree(source_in_image: Path, module_path: Path) -> Path:
    if source_in_image.is_dir():
        return source_in_image
    try:
        fallback = module_path.resolve().parents[4]
    except IndexError:
        raise RuntimeError("materializer source tree is unavailable") from None
    if not fallback.is_dir():
        raise RuntimeError("materializer source tree is unavailable")
    return fallback


_SOURCE_IN_IMAGE = Path("/opt/insurancekb/source")
WORKTREE = _select_worktree(_SOURCE_IN_IMAGE, Path(__file__))
EVIDENCE = WORKTREE / "docs/insurance-kb/evidence/830-g3"
sys.path.insert(0, str(WORKTREE / "harness/src"))

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime  # noqa: E402
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (  # noqa: E402
    BatchConceptCompileRequest830G3V1,
    build_batch_compile_request,
    compile_output_hash_g3,
    compiler_context_g3,
    review_context_g3,
)
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import (  # noqa: E402
    batch_json_bytes_830_g3,
)
from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (  # noqa: E402
    BatchCorpusV1,
    BatchEntityResolutionV1,
    BatchResolutionPolicyV1,
    ExistingEntitySnapshotV1,
    ProposalBatchV1,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (  # noqa: E402
    CandidateBundle,
    CompileResult,
)
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (  # noqa: E402
    G3NativePageProjectionSetV1,
    G3SemanticResponseV1,
    _render_g3_stage_contexts,
    canonical_native_page_projections,
    g3_current_schema_specs,
    g3_openai_request_bytes,
)
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import (  # noqa: E402
    validate_catalog,
)
from insurance_harness.model_policy import ModelIdentity  # noqa: E402
from insurance_harness.model_policy import g3_bounded_gateway as gateway  # noqa: E402
from insurance_harness.run_admission import evaluator  # noqa: E402
from insurance_harness.run_admission.g3_models import (  # noqa: E402
    G3ArtifactRefV1,
    G3AuthorizedMaterialV1,
    G3BoundedAdmissionPlanV1,
    G3BoundedApprovalEnvelopeV1,
    G3CallPlanV1,
    G3ChainManifestV1,
    G3ChainStageV1,
    G3DelegatedStageSignerV1,
    G3DerivedStageReceiptV1,
    G3EligibilityCheckV1,
    G3FailurePolicyV1,
    G3LedgerPolicyV1,
    G3ModelProcessingAuthorizationEnvelopeV1,
    G3ModelProcessingAuthorizationV1,
    G3ProtocolSeedLockV1,
    G3RequestManifestV1,
    G3RoutingLockV1,
    G3SchemaArtifactV1,
    G3SchemaLockV1,
    G3StageCapsV1,
    G3StageDispatchLockV1,
    G3StageEligibilityLockV1,
    G3StageProvenanceLockV1,
    G3StageRightsLockV1,
    G3StageTerminalReceiptV1,
    G3TemplateLockV1,
    canonical_g3_hash,
    canonical_json,
)
from insurance_harness.run_admission.g3_trust_policy import (  # noqa: E402
    load_g3_root_trust_policy,
    verify_delegated_stage_signature,
    verify_parent_authorization,
)
from insurance_harness.run_admission.models import (  # noqa: E402
    ResourceCaps,
    canonical_model_identities_hash,
    canonical_model_plan_hash,
)
from insurance_harness.run_admission.profiles.g3_bounded_execution import (  # noqa: E402
    G3_STAGE_PROFILES,
    validate_g3_bounded_plan,
    validate_g3_parent_scope,
)

DESIGN_SHA256 = "0a93188db54302510e5f2f3cce9004264cf4ca264c018e9acdb34a04b93a0228"
BUILDER_DESIGN_SHA256 = "93d43e9638b008ebfb38fcbda8fc4a0e9568b068905612328c395bd9ec92482f"
SOURCE_RUNNER_SHA256 = "d10d0a8e4fd4b130131a3326cceaa6e44e9ae6eda789dec798dabe955c46809f"
G3_SCOPE = {
    "tenant_id": 10003,
    "space_id": "a8751a40-83ce-55c8-a160-079b283483ca",
    "raw_kb_id": "b1f1764c-443d-46b8-98e3-d5aa5e55eb42",
    "wiki_kb_id": "8d5695de-f255-42d5-9a41-042ba86e97b9",
}
G3_MATERIAL_IDS = tuple(
    f"g3-material-{ordinal:02d}" for ordinal in (1, 2, 3, 4, 7, 8, 9, 11, 12, 13, 14, 17, 18, 19, 21)
)
G3_ACQUISITION_INPUT_LOCKS = {
    "selected_file_set": {
        "sha256": "3260b23abec9740cc7cbed161273922a3c7a63771fe60fc4cbad013f481a9753",
        "file_set_sha256": "0fa401475bf868a5f0f49f406da40214b6e1af7b88cca64e65c2e2b84fc4648f",
    },
    "native_capture_set": {
        "sha256": "3cbbf7776f16e216d28902580acf34197b56475a1c29f9654b2bdde5892e2de8",
        "capture_set_sha256": "70a6fe13275f7366c610abbed0d8c44b480197696b1f4a03624457f48d4cf4e5",
    },
}
G2_PATH = WORKTREE / "docs/insurance-kb/evidence/830-g2/b-source-complete-candidate-bundle.json"
CATALOG_PATH = EVIDENCE / "catalog/catalog.json"
PROFILE_PATH = EVIDENCE / "profile-user-confirmation.json"
FROZEN = {
    G2_PATH: "69dd25e29ea771a512cf24c083a52e8347386def68b30d90d379f2b0dfe181d1",
    CATALOG_PATH: "0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9",
    PROFILE_PATH: "7f6141c63db4a77e3d13a0a8d632ea5463761bedeee7bd1aabef165d68c86863",
}
BUILDER_NAMES = (
    "source-acquisition-bundle.json",
    "batch-corpus.json",
    "g3-native-page-projections.json",
    "existing-entities.json",
    "batch-resolution-policy.json",
    "protocol-seed-artifact.json",
    "builder-result.json",
)
TEMPLATE_NAMES = {
    "C_CLASSIFY": "g3_c_classify_v1.txt",
    "D_COMPILE": "g3_d_compile_v1.txt",
    "D_REVIEW": "g3_d_review_v1.txt",
}
INSTALL_ROOT = Path("/var/lib/insurancekb/run-admission")
ZERO = "0" * 64
Hash = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[StrictStr, StringConstraints(min_length=1)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class StageRun(_Closed):
    stage: Literal["C_CLASSIFY", "D_COMPILE", "D_REVIEW"]
    run_id: Text
    run_revision: Text


class StageIdentity(_Closed):
    stage: Literal["C_CLASSIFY", "D_COMPILE", "D_REVIEW"]
    identity: ModelIdentity


class Route(_Closed):
    endpoint_origin: Literal["https://dashscope.aliyuncs.com"]
    endpoint_path: Literal["/compatible-mode/v1/chat/completions"]
    temperature_micros: Literal[0]
    thinking: StrictBool
    response_format: Literal["json_object"]
    follow_redirects: Literal[False]
    fallback_limit: Literal[0]
    retry_limit: Literal[0]


class CallOption(_Closed):
    stage: Literal["C_CLASSIFY", "D_COMPILE", "D_REVIEW"]
    call_id: Text
    ordinal: Annotated[StrictInt, Field(ge=0)]
    window_id: Text | None
    material_ids: tuple[Text, ...]
    input_token_ceiling: Annotated[StrictInt, Field(gt=0)]
    output_token_ceiling: Annotated[StrictInt, Field(gt=0)]
    timeout_seconds: Annotated[StrictInt, Field(gt=0)]


class Estimator(_Closed):
    version: Literal["g3-utf8-body-upper-bound.830.v1"]
    mode: Literal["UTF8_BODY_BYTES_PLUS_FRAMING_TOKENS", "PUBLISHED_MAX_RESERVATION"]
    framing_token_allowance: Annotated[StrictInt, Field(ge=0)]
    proof_sha256s: tuple[Hash, ...]


class PublicLimits(_Closed):
    context_tokens: Annotated[StrictInt, Field(gt=0)]
    max_input_tokens: Annotated[StrictInt, Field(gt=0)]
    max_output_tokens: Annotated[StrictInt, Field(gt=0)]
    source_sha256s: tuple[Hash, ...]


class Approver(_Closed):
    key_id: Text
    public_key_b64: Text
    public_key_fingerprint: Hash
    human_identity: Text
    approver_role: Literal["g3-model-processing-authorization-approver"]
    signature_domain: Literal["insurancekb.run-admission.g3-model-processing-authorization.v1"]


class ExecutionOptions(_Closed):
    contract: Literal["g3-actual-model-execution-options.830.v1"]
    authorization_id: Text
    chain_id: Text
    clean_integration_sha: Annotated[
        StrictStr, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    ]
    expires_at: AwareDatetime
    stage_runs: tuple[StageRun, ...]
    identities: tuple[StageIdentity, ...]
    route: Route
    calls: tuple[CallOption, ...]
    input_estimator: Estimator
    public_model_limits: PublicLimits
    expected_parent_approver: Approver
    delegated_stage_signer: G3DelegatedStageSignerV1

    @model_validator(mode="after")
    def closure(self):
        stages = ("C_CLASSIFY", "D_COMPILE", "D_REVIEW")
        if (
            tuple(x.stage for x in self.stage_runs) != stages
            or tuple(x.stage for x in self.identities) != stages
        ):
            raise ValueError("stage rows must be exact and ordered")
        if self.expires_at <= dt.datetime.now(dt.UTC):
            raise ValueError("authorization expiry is not in the future")
        ids = [x.call_id for x in self.calls]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate call id")
        identities = [x.identity for x in self.identities]
        if any(
            (x.provider, x.deployment_id, x.family, x.policy_version)
            != (
                identities[0].provider,
                identities[0].deployment_id,
                identities[0].family,
                identities[0].policy_version,
            )
            for x in identities
        ) or tuple(x.role for x in identities) != ("classify", "extract", "verify"):
            raise ValueError("identity projection mismatch")
        if any(
            x.identity.provider != "bailian" or x.identity.family != "qwen" for x in self.identities
        ):
            raise ValueError("unsupported model family")
        for stage in stages:
            rows = [x for x in self.calls if x.stage == stage]
            if stage == "C_CLASSIFY":
                if not rows or tuple(x.ordinal for x in rows) != tuple(range(len(rows))):
                    raise ValueError("C ordinals are not contiguous")
                mids = [m for x in rows for m in x.material_ids]
                if any(
                    x.window_id is None or tuple(sorted(set(x.material_ids))) != x.material_ids
                    for x in rows
                ) or len(mids) != len(set(mids)):
                    raise ValueError("C windows are not canonical")
            elif (
                len(rows) != 1
                or rows[0].ordinal != 0
                or rows[0].window_id is not None
                or rows[0].material_ids
            ):
                raise ValueError("D call shape invalid")
            if len({x.timeout_seconds for x in rows}) != 1:
                raise ValueError("stage timeout mismatch")
        for values in (self.input_estimator.proof_sha256s, self.public_model_limits.source_sha256s):
            if values != tuple(sorted(set(values))):
                raise ValueError("source hashes are not sorted unique")
        raw = base64.b64decode(self.expected_parent_approver.public_key_b64, validate=True)
        if (
            len(raw) != 32
            or base64.b64encode(raw).decode() != self.expected_parent_approver.public_key_b64
            or _sha(raw) != self.expected_parent_approver.public_key_fingerprint
        ):
            raise ValueError("approver public key invalid")
        if (
            self.input_estimator.mode == "PUBLISHED_MAX_RESERVATION"
            and self.input_estimator.framing_token_allowance != 0
        ):
            raise ValueError("published reservation requires zero allowance")
        return self


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: bytes, label: str) -> Any:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key in {label}")
            out[key] = value
        return out

    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {label}") from exc

    def walk(item):
        if isinstance(item, str) and unicodedata.normalize("NFC", item) != item:
            raise ValueError(f"non-NFC JSON in {label}")
        if isinstance(item, float) and not __import__("math").isfinite(item):
            raise ValueError(f"non-finite JSON in {label}")
        if isinstance(item, dict):
            for k, v in item.items():
                walk(k)
                walk(v)
        elif isinstance(item, list):
            for v in item:
                walk(v)

    walk(value)
    return value


def _canonical_wire_json(raw: bytes, label: str) -> Any:
    """Read one canonical JSON wire without granting any field an exemption."""

    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key in {label}")
            out[key] = value
        return out

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON in {label}: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {label}") from exc
    if canonical_json(value) != raw:
        raise ValueError(f"noncanonical JSON in {label}")
    return value


def _native_json(raw: bytes, label: str) -> G3NativePageProjectionSetV1:
    value = _canonical_wire_json(raw, label)
    native = G3NativePageProjectionSetV1.model_validate(value)
    if canonical_native_page_projections(native) != raw:
        raise ValueError(f"native typed wire mismatch in {label}")
    return native


def _corpus_json(raw: bytes, label: str) -> BatchCorpusV1:
    value = _canonical_wire_json(raw, label)
    corpus = BatchCorpusV1.model_validate(value)
    if batch_json_bytes_830_g3(corpus) != raw:
        raise ValueError(f"corpus typed wire mismatch in {label}")
    return corpus


_RENDERED_BODY_CONTRACTS = frozenset(
    {
        "g3-rendered-call-context.830.v1",
        "g3-stage-render-contexts.830.v1",
        "g3-c-prompt-preview.830.v1",
        "g3-http-request-body.830.v1",
    }
)


def _validate_artifact_wire(contract: str, raw: bytes, label: str) -> object:
    if contract == "batch-corpus.830.g3.v1":
        return _corpus_json(raw, label)
    if contract == "g3-native-page-projections.830.v1":
        return _native_json(raw, label)
    if contract in _RENDERED_BODY_CONTRACTS:
        return _canonical_wire_json(raw, label)
    value = _strict_json(raw, label)
    if canonical_json(value) != raw:
        raise ValueError(f"noncanonical JSON in {label}")
    return value


def _regular(path: Path, *, canonical: bool = False, expected_sha: str | None = None) -> bytes:
    before = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_mode & 0o022
    ):
        raise ValueError(f"unsafe input file: {path}")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read()
        after = os.fstat(stream.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
    ) or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"unstable input file: {path}")
    if expected_sha and _sha(raw) != expected_sha:
        raise ValueError(f"frozen input drift: {path}")
    if canonical:
        value = _strict_json(raw, str(path))
        if canonical_json(value) != raw:
            raise ValueError(f"noncanonical JSON: {path}")
    return raw


def _no_symlink_ancestors(path: Path, root: Path) -> None:
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"symlink path component: {current}")
        if root not in current.parents:
            raise ValueError("artifact path escapes package root")
        current = current.parent


def _git_identity() -> tuple[str, bytes]:
    return evaluator._clean_repository_sha(), b""


def _hashed(cls, domain: str, field: str, **values):
    provisional = cls(**values, **{field: ZERO})
    return provisional.model_copy(update={field: canonical_g3_hash(domain, provisional, field)})


def _ref(contract: str, raw: bytes, filename: str) -> G3ArtifactRefV1:
    digest = _sha(raw)
    return G3ArtifactRefV1(
        contract=contract,
        artifact_ref=str(INSTALL_ROOT / "sha256" / digest / filename),
        sha256=digest,
        bytes=len(raw),
    )


def _template(stage: str):
    rel = f"harness/src/insurance_harness/knowledge_compiler/prompts/{TEMPLATE_NAMES[stage]}"
    raw = (WORKTREE / rel).read_bytes()
    values = {
        "contract": "g3-stage-template-lock.830.v1",
        "stage": stage,
        "path": rel,
        "raw_sha256": _sha(raw),
        "prompt_version": Path(rel).stem.replace("_", "-"),
        "render_rules_version": "g3-prompt-render.830.v1",
    }
    approved = _sha(b"g3-approved-template.830.v1\0" + canonical_json(values))
    lock = _hashed(
        G3TemplateLockV1,
        "g3-stage-template-lock.830.v1",
        "template_lock_hash",
        **values,
        approved_template_hash=approved,
    )
    return lock, raw


def _schema(stage: str):
    rows = []
    for direction, module, schema in g3_current_schema_specs(stage):
        raw = (WORKTREE / module).read_bytes()
        rows.append(
            G3SchemaArtifactV1(
                stage=stage,
                direction=direction,
                enforcing_module=module,
                enforcing_module_sha256=_sha(raw),
                canonical_schema_sha256=_sha(canonical_json(schema)),
            )
        )
    return _hashed(
        G3SchemaLockV1,
        "g3-stage-schema-set.830.v1",
        "schema_hash",
        contract="g3-stage-schema-set.830.v1",
        artifacts=tuple(sorted(rows, key=lambda x: (x.stage, x.direction, x.enforcing_module))),
    )


def _failure():
    return G3FailurePolicyV1(
        policy_version="g3-chain-failure-policy.830.v1",
        retry_limit=0,
        worker_limit=1,
        incomplete_reservation_action="PERMANENTLY_CONSUME_AND_STOP_STAGE",
        started_without_terminal_action="PERMANENT_OUTCOME_UNKNOWN_STOP_CHAIN",
        call_failure_action="STOP_CHAIN",
        c_execution_failure_action="STOP_BEFORE_RESOLVE",
        c_coverage_gap_action="MARK_DOD_GAP_CONTINUE_ELIGIBLE_AUTOMATIC_CHILDREN",
        d_compile_failure_action="STOP_BEFORE_REVIEW",
        d_review_failure_action="STOP_BEFORE_CANDIDATE",
    )


def _ledger():
    return G3LedgerPolicyV1(
        protocol_version="g3-cross-process-ledger.830.v1",
        root_path="/var/lib/insurancekb/g3-bounded-execution-ledger/v1",
        owner_rule="LEAF_OWNER_EQUALS_EFFECTIVE_SERVICE_UID",
        root_mode="0700",
        stage_binding_mode="ONE_ADMISSION_DIGEST_PER_CHAIN_STAGE_O_EXCL",
        call_reservation_mode="ATOMIC_MKDIR_AND_O_EXCL_RECORD",
        duplicate_action="DENY_HTTP_ZERO",
        malformed_ledger_action="PERMANENTLY_CONSUME_AND_DENY_HTTP_ZERO",
    )


def _options(path: Path) -> tuple[ExecutionOptions, bytes]:
    raw = _regular(path, canonical=True)
    value = ExecutionOptions.model_validate_json(raw)
    return value, raw


def _chain(options: ExecutionOptions):
    rows = []
    for run, identity in zip(options.stage_runs, options.identities, strict=True):
        calls = [x for x in options.calls if x.stage == run.stage]
        purpose, schema, role = G3_STAGE_PROFILES[run.stage]
        if identity.identity.role != role:
            raise ValueError("stage role mismatch")
        rows.append(
            G3ChainStageV1(
                stage=run.stage,
                purpose=purpose,
                run_schema_version=schema,
                role=role,
                max_calls=len(calls),
                input_token_ceiling=sum(x.input_token_ceiling for x in calls),
                output_token_ceiling=sum(x.output_token_ceiling for x in calls),
                time_limit_seconds=sum(x.timeout_seconds for x in calls),
            )
        )
    return _hashed(
        G3ChainManifestV1,
        "g3-bounded-chain.830.v1",
        "chain_manifest_hash",
        contract="g3-bounded-chain.830.v1",
        chain_id=options.chain_id,
        clean_integration_sha=options.clean_integration_sha,
        stages=tuple(rows),
        max_calls=sum(x.max_calls for x in rows),
        total_input_token_ceiling=sum(x.input_token_ceiling for x in rows),
        total_output_token_ceiling=sum(x.output_token_ceiling for x in rows),
        total_time_limit_seconds=sum(x.time_limit_seconds for x in rows),
        retry_limit=0,
        worker_limit=1,
        derivation_rules_version="g3-c-to-d-derivation.830.v1",
        prompt_render_rules_version="g3-prompt-render.830.v1",
        schema_derivation_version="g3-schema-derivation.830.v1",
        failure_policy=_failure(),
        ledger_policy=_ledger(),
    )


def _builder(builder_dir: Path):
    directory_info = builder_dir.stat(follow_symlinks=False)
    if builder_dir.is_symlink() or not stat.S_ISDIR(directory_info.st_mode):
        raise ValueError("builder input is not a real directory")
    if set(p.name for p in builder_dir.iterdir()) != set(BUILDER_NAMES):
        raise ValueError("builder directory set drift")
    raw = {name: _regular(builder_dir / name) for name in BUILDER_NAMES}
    _corpus_json(raw["batch-corpus.json"], "batch-corpus.json")
    _native_json(raw["g3-native-page-projections.json"], "g3-native-page-projections.json")
    for name in set(BUILDER_NAMES) - {
        "batch-corpus.json",
        "g3-native-page-projections.json",
    }:
        value = _strict_json(raw[name], name)
        if canonical_json(value) != raw[name]:
            raise ValueError(f"noncanonical JSON: {name}")
    result, seed = _validate_builder_proof(raw)
    corpus = _corpus_json(raw["batch-corpus.json"], "batch-corpus.json")
    native = _native_json(raw["g3-native-page-projections.json"], "g3-native-page-projections.json")
    existing = ExistingEntitySnapshotV1.model_validate_json(raw["existing-entities.json"])
    policy = BatchResolutionPolicyV1.model_validate_json(raw["batch-resolution-policy.json"])
    return raw, result, corpus, native, existing, policy, seed


def _source_acquisition_mapping(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"source acquisition {label} keys drift")
    return value


def _source_acquisition_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"source acquisition {label} hash invalid")
    return value


def _source_acquisition_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"source acquisition {label} text invalid")
    return value


def _validate_chunk_page_receipts(
    material_id: str,
    chunk_count: int,
    artifacts: list[dict[str, Any]],
    response_hashes: list[str],
) -> None:
    # The frozen local SOURCE runner requests 100 W1 rows per HTTP page.
    family = "after-old" if material_id in G3_MATERIAL_IDS[:4] else "current"
    prefix = f"local-completion:{family}-chunks-{material_id}-"
    pages = []
    for artifact in artifacts:
        label = artifact["label"]
        if "chunks-" not in label:
            continue
        match = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]*)", label)
        if match is None or artifact["artifact"] != (
            "local-completion--" + label.split(":", 1)[1] + ".json"
        ):
            raise ValueError("source acquisition HTTP pagination identity mismatch")
        pages.append((int(match.group(1)), artifact["response_sha256"]))
    pages.sort()
    expected_pages = (chunk_count + 99) // 100
    if (
        [ordinal for ordinal, _ in pages] != list(range(1, expected_pages + 1))
        or response_hashes != [digest for _, digest in pages]
    ):
        raise ValueError("source acquisition HTTP pagination closure mismatch")


def _validate_source_acquisition(
    acquisition: object,
    corpus: BatchCorpusV1,
    native: G3NativePageProjectionSetV1,
) -> None:
    value = _source_acquisition_mapping(
        acquisition,
        {
            "contract",
            "source_run_receipt",
            "source_artifact_manifest",
            "guard_ledger",
            "selected_file_set",
            "native_capture_set",
            "scope",
            "materials",
        },
        "bundle",
    )
    if value["contract"] != "g3-source-acquisition-bundle.830.v1":
        raise ValueError("source acquisition contract drift")

    source_run = _source_acquisition_mapping(
        value["source_run_receipt"], {"sha256", "observation_sha256", "observed_at"}, "run receipt"
    )
    _source_acquisition_hash(source_run["sha256"], "run receipt")
    _source_acquisition_hash(source_run["observation_sha256"], "run observation")
    observed_at = _source_acquisition_text(source_run["observed_at"], "observed_at")
    try:
        observed = dt.datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("source acquisition observed_at invalid") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("source acquisition observed_at must be aware")

    source_manifest = value["source_artifact_manifest"]
    if not isinstance(source_manifest, list):
        raise ValueError("source acquisition artifact manifest invalid")
    source_names = []
    for row_value in source_manifest:
        row = _source_acquisition_mapping(row_value, {"artifact", "sha256", "size"}, "artifact row")
        name = _source_acquisition_text(row["artifact"], "artifact")
        if Path(name).name != name:
            raise ValueError("source acquisition artifact path invalid")
        _source_acquisition_hash(row["sha256"], "artifact")
        if type(row["size"]) is not int or row["size"] <= 0:
            raise ValueError("source acquisition artifact size invalid")
        source_names.append(name)
    if source_names != sorted(source_names) or len(source_names) != len(set(source_names)):
        raise ValueError("source acquisition artifact manifest order drift")

    source_manifest_by_name = {row["artifact"]: row for row in source_manifest}

    guard = _source_acquisition_mapping(value["guard_ledger"], {"artifact", "sha256", "size"}, "guard")
    guard_name = _source_acquisition_text(guard["artifact"], "guard artifact")
    if Path(guard_name).name != guard_name:
        raise ValueError("source acquisition guard path invalid")
    _source_acquisition_hash(guard["sha256"], "guard")
    if type(guard["size"]) is not int or guard["size"] <= 0:
        raise ValueError("source acquisition guard size invalid")
    for key, expected_keys in (
        ("selected_file_set", {"sha256", "file_set_sha256"}),
        ("native_capture_set", {"sha256", "capture_set_sha256"}),
    ):
        lock = _source_acquisition_mapping(value[key], expected_keys, key)
        for name, digest in lock.items():
            _source_acquisition_hash(digest, f"{key}.{name}")
        if lock != G3_ACQUISITION_INPUT_LOCKS[key]:
            raise ValueError(f"source acquisition {key} lock drift")

    scope = _source_acquisition_mapping(
        value["scope"], {"tenant_id", "space_id", "raw_kb_id", "wiki_kb_id"}, "scope"
    )
    expected_scope = {
        "tenant_id": corpus.tenant_id,
        "space_id": corpus.space_id,
        "raw_kb_id": corpus.raw_kb_id,
        "wiki_kb_id": corpus.wiki_kb_id,
    }
    if scope != expected_scope or scope != G3_SCOPE:
        raise ValueError("source acquisition scope does not match corpus")

    materials = value["materials"]
    if not isinstance(materials, list):
        raise ValueError("source acquisition materials invalid")
    corpus_entries = {entry.material_id: entry for entry in corpus.entries}
    material_ids = []
    native_pages: dict[str, list[Any]] = {material_id: [] for material_id in corpus_entries}
    for page in native.pages:
        if page.material_id not in native_pages:
            raise ValueError("source acquisition native material outside corpus")
        native_pages[page.material_id].append(page)
    if any(not pages for pages in native_pages.values()):
        raise ValueError("source acquisition native material missing")

    facts_keys = {
        "inventory_file",
        "source_http",
        "registered_source_receipt",
        "revision",
        "w1",
        "native",
        "acquisition_context",
    }
    for row_value in materials:
        row = _source_acquisition_mapping(
            row_value, {"material_id", "facts", "acquisition_receipt_sha256"}, "material"
        )
        material_id = _source_acquisition_text(row["material_id"], "material id")
        if material_id not in corpus_entries:
            raise ValueError("source acquisition material outside corpus")
        material_ids.append(material_id)
        entry = corpus_entries[material_id]
        facts = _source_acquisition_mapping(row["facts"], facts_keys, "facts")
        receipt_hash = _source_acquisition_hash(
            row["acquisition_receipt_sha256"], "material receipt"
        )
        if receipt_hash != _sha(canonical_json(facts)):
            raise ValueError("source acquisition material receipt does not match facts")
        if entry.provenance.acquisition_receipt_sha256 != receipt_hash:
            raise ValueError("source acquisition receipt does not match corpus provenance")

        inventory = _source_acquisition_mapping(
            facts["inventory_file"], {"path", "file_sha256", "size", "page_count"}, "inventory"
        )
        _source_acquisition_text(inventory["path"], "inventory path")
        _source_acquisition_hash(inventory["file_sha256"], "inventory file")
        source_http = _source_acquisition_mapping(
            facts["source_http"], {"knowledge_id", "parse_attempt", "artifacts"}, "source HTTP"
        )
        http_artifacts = source_http["artifacts"]
        if not isinstance(http_artifacts, list):
            raise ValueError("source acquisition HTTP artifacts invalid")
        http_order = []
        for artifact_value in http_artifacts:
            artifact = _source_acquisition_mapping(
                artifact_value, {"label", "artifact", "response_sha256", "size"}, "HTTP artifact"
            )
            label = _source_acquisition_text(artifact["label"], "HTTP artifact label")
            artifact_name = _source_acquisition_text(artifact["artifact"], "HTTP artifact")
            if Path(artifact_name).name != artifact_name:
                raise ValueError("source acquisition HTTP artifact path invalid")
            _source_acquisition_hash(artifact["response_sha256"], "HTTP response")
            if type(artifact["size"]) is not int or artifact["size"] <= 0:
                raise ValueError("source acquisition HTTP artifact size invalid")
            if source_manifest_by_name.get(artifact_name) != {
                "artifact": artifact_name,
                "sha256": artifact["response_sha256"],
                "size": artifact["size"],
            }:
                raise ValueError("source acquisition HTTP artifact manifest mismatch")
            http_order.append(label)
        if http_order != sorted(http_order) or len(http_order) != len(set(http_order)):
            raise ValueError("source acquisition HTTP artifact order drift")

        receipt = entry.receipt.model_dump(mode="json")
        registered = _source_acquisition_mapping(
            facts["registered_source_receipt"], set(receipt), "registered receipt"
        )
        if registered != receipt:
            raise ValueError("source acquisition registered receipt does not match corpus")
        revision = _source_acquisition_mapping(
            facts["revision"],
            {
                "before_response_sha256",
                "after_response_sha256",
                "descriptor_sha256",
                "parser_identity_sha256",
                "manifest_algorithm",
                "manifest_digest",
                "chunk_count",
            },
            "revision",
        )
        for name in (
            "before_response_sha256",
            "after_response_sha256",
            "descriptor_sha256",
            "parser_identity_sha256",
            "manifest_digest",
        ):
            _source_acquisition_hash(revision[name], f"revision.{name}")
        w1 = _source_acquisition_mapping(
            facts["w1"],
            {"chunk_response_sha256s", "ordered_rows_sha256", "chunk_count", "manifest_digest"},
            "W1",
        )
        if not isinstance(w1["chunk_response_sha256s"], list):
            raise ValueError("source acquisition W1 chunk receipts invalid")
        for digest in w1["chunk_response_sha256s"]:
            _source_acquisition_hash(digest, "W1 chunk response")
        _source_acquisition_hash(w1["ordered_rows_sha256"], "W1 rows")
        _source_acquisition_hash(w1["manifest_digest"], "W1 manifest")
        native_facts = _source_acquisition_mapping(
            facts["native"],
            {
                "path",
                "capture_file_sha256",
                "raw_capture_sha256",
                "native_sha256",
                "markdown_sha256",
                "parser_identity_sha256",
                "page_count",
            },
            "native",
        )
        _source_acquisition_text(native_facts["path"], "native path")
        for name in (
            "capture_file_sha256",
            "raw_capture_sha256",
            "native_sha256",
            "markdown_sha256",
            "parser_identity_sha256",
        ):
            _source_acquisition_hash(native_facts[name], f"native.{name}")
        context = _source_acquisition_mapping(
            facts["acquisition_context"],
            {
                "source_run_receipt_sha256",
                "authenticated_user_id",
                "authenticated_role",
                "login_response_sha256",
                "me_sha256",
                "observed_at",
                "tenant_id",
                "space_id",
                "raw_kb_id",
                "wiki_kb_id",
            },
            "context",
        )
        _source_acquisition_hash(context["login_response_sha256"], "login response")
        _source_acquisition_hash(context["me_sha256"], "me response")
        _source_acquisition_text(context["authenticated_user_id"], "authenticated user")
        _source_acquisition_text(context["authenticated_role"], "authenticated role")

        integer_values = (
            inventory["size"],
            inventory["page_count"],
            source_http["parse_attempt"],
            revision["chunk_count"],
            w1["chunk_count"],
            native_facts["page_count"],
        )
        if any(type(item) is not int or item <= 0 for item in integer_values):
            raise ValueError("source acquisition count invalid")
        if (
            inventory["file_sha256"] != receipt["file_sha256"]
            or inventory["size"] != receipt["size"]
            or inventory["page_count"] != receipt["page_count"]
            or source_http["knowledge_id"] != receipt["knowledge_id"]
            or source_http["parse_attempt"] != receipt["parse_attempt"]
            or revision["parser_identity_sha256"] != entry.parser_identity_sha256
            or revision["manifest_algorithm"] != receipt["manifest_algorithm"]
            or revision["manifest_digest"] != receipt["manifest_digest"]
            or revision["chunk_count"] != receipt["chunk_count"]
            or w1["manifest_digest"] != receipt["manifest_digest"]
            or w1["chunk_count"] != receipt["chunk_count"]
            or native_facts["native_sha256"] != entry.native_capture_sha256
            or native_facts["page_count"] != receipt["page_count"]
            or context["source_run_receipt_sha256"] != source_run["sha256"]
            or context["observed_at"] != observed_at
            or {key: context[key] for key in expected_scope} != expected_scope
            or context["authenticated_user_id"] != entry.provenance.declared_by
        ):
            raise ValueError("source acquisition facts do not match corpus")
        _validate_chunk_page_receipts(
            material_id, receipt["chunk_count"], http_artifacts, w1["chunk_response_sha256s"]
        )
        blocks = {(block.revision_id, block.block_id): block for block in entry.blocks}
        for page in native_pages[material_id]:
            block = blocks.get((page.revision_id, page.block_id))
            if block is None or block.page_number != page.page_number:
                raise ValueError("source acquisition native projection does not match corpus")

    expected_material_ids = [entry.material_id for entry in corpus.entries]
    if (
        material_ids != expected_material_ids
        or tuple(material_ids) != G3_MATERIAL_IDS
        or len(material_ids) != len(set(material_ids))
    ):
        raise ValueError("source acquisition material denominator does not match corpus")


def _validate_builder_proof(raw: dict[str, bytes]):
    if set(raw) != set(BUILDER_NAMES):
        raise ValueError("builder proof file set drift")
    result = _strict_json(raw["builder-result.json"], "builder-result")
    result_keys = {
        "contract",
        "status",
        "design_sha256",
        "source_runner_sha256",
        "inputs",
        "outputs",
        "protocol_seed_lock",
        "effects",
    }
    input_keys = {
        "source_receipt_sha256",
        "source_observation_sha256",
        "head_wrapper_sha256",
        "business_input_sha256",
        "provenance_input_sha256",
    }
    if (
        not isinstance(result, dict)
        or set(result) != result_keys
        or result.get("contract") != "g3-actual-c-input-builder-result.830.v1"
        or result.get("status") != "PASS"
        or result.get("design_sha256") != BUILDER_DESIGN_SHA256
        or result.get("source_runner_sha256") != SOURCE_RUNNER_SHA256
        or not isinstance(result.get("inputs"), dict)
        or set(result["inputs"]) != input_keys
        or result.get("effects")
        != {"database": 0, "docker": 0, "http": 0, "model": 0, "provider": 0}
    ):
        raise ValueError("builder result invalid")
    expected = {
        name: {"sha256": _sha(raw[name]), "bytes": len(raw[name])} for name in BUILDER_NAMES[:-1]
    }
    if result.get("outputs") != expected:
        raise ValueError("builder output closure mismatch")
    acquisition = _strict_json(raw["source-acquisition-bundle.json"], "source acquisition")
    corpus = _corpus_json(raw["batch-corpus.json"], "batch-corpus.json")
    native = _native_json(raw["g3-native-page-projections.json"], "g3-native-page-projections.json")
    _validate_source_acquisition(acquisition, corpus, native)
    source_receipt = acquisition.get("source_run_receipt", {})
    if (
        not isinstance(result.get("inputs"), dict)
        or source_receipt.get("sha256") != result["inputs"].get("source_receipt_sha256")
        or source_receipt.get("observation_sha256")
        != result["inputs"].get("source_observation_sha256")
    ):
        raise ValueError("builder source proof closure mismatch")
    seed = G3ProtocolSeedLockV1.model_validate(result["protocol_seed_lock"])
    if (
        seed.seed_artifact.contract != "g3-protocol-seed-artifact.830.v1"
        or seed.seed_artifact.artifact_ref != "protocol-seed-artifact.json"
        or _sha(raw["protocol-seed-artifact.json"]) != seed.seed_artifact.sha256
        or len(raw["protocol-seed-artifact.json"]) != seed.seed_artifact.bytes
    ):
        raise ValueError("seed artifact mismatch")
    return result, seed


def _frozen_sources():
    g2_raw = _regular(G2_PATH, expected_sha=FROZEN[G2_PATH])
    catalog_raw = _regular(CATALOG_PATH, expected_sha=FROZEN[CATALOG_PATH])
    profile_raw = _regular(PROFILE_PATH, expected_sha=FROZEN[PROFILE_PATH])
    g2 = CandidateBundle.model_validate(_strict_json(g2_raw, str(G2_PATH)))
    catalog = validate_catalog(catalog_raw)
    # The compile builder owns the profile receipt DTO; this pass rejects duplicate keys.
    _strict_json(profile_raw, str(PROFILE_PATH))
    return g2, catalog, catalog_raw, profile_raw


def _artifact_contracts(raw: dict[str, bytes]) -> dict[str, tuple[str, str, bytes]]:
    return {
        "corpus": ("batch-corpus.830.g3.v1", "batch-corpus.json", raw["batch-corpus.json"]),
        "native": (
            "g3-native-page-projections.830.v1",
            "g3-native-page-projections.json",
            raw["g3-native-page-projections.json"],
        ),
        "existing": (
            "existing-entities.830.g3.v1",
            "existing-entities.json",
            raw["existing-entities.json"],
        ),
        "policy": (
            "batch-resolution-policy.830.g3.v1",
            "batch-resolution-policy.json",
            raw["batch-resolution-policy.json"],
        ),
        "seed": (
            "g3-protocol-seed-data.830.v1",
            "protocol-seed-artifact.json",
            raw["protocol-seed-artifact.json"],
        ),
    }


def _authorized_materials(corpus: BatchCorpusV1, native: G3NativePageProjectionSetV1):
    pages: dict[str, list[Any]] = {entry.material_id: [] for entry in corpus.entries}
    for page in native.pages:
        if page.material_id not in pages:
            raise ValueError("native material outside corpus")
        pages[page.material_id].append(page)
    result = []
    for entry in sorted(corpus.entries, key=lambda x: x.material_id):
        own = sorted(pages[entry.material_id], key=lambda x: x.block_ref)
        if not own:
            raise ValueError("material has no native projection")
        result.append(
            G3AuthorizedMaterialV1(
                material_id=entry.material_id,
                corpus_entry_sha256=entry.entry_sha256,
                source_revision_receipt_sha256=_sha(
                    canonical_json(entry.receipt.model_dump(mode="json"))
                ),
                w1_sha256=_sha(batch_json_bytes_830_g3(entry.blocks)),
                native_page_map_sha256=_sha(
                    canonical_native_page_projections(
                        G3NativePageProjectionSetV1(
                            contract="g3-native-page-projections.830.v1",
                            pages=tuple(own),
                        )
                    )
                ),
            )
        )
    return tuple(result)


def _c_contexts(corpus, native, existing, policy, catalog, calls):
    entries = {x.material_id: x for x in corpus.entries}
    blocks = {
        x.material_id: {(b.revision_id, b.block_id): b for b in x.blocks} for x in corpus.entries
    }
    pages = {x.material_id: [] for x in corpus.entries}
    for page in native.pages:
        source = blocks.get(page.material_id, {}).get((page.revision_id, page.block_id))
        if source is None or source.page_number != page.page_number:
            raise ValueError("foreign native projection")
        pages[page.material_id].append(page)
    roles = sorted({role for rule in policy.rules for role in rule.material_roles})
    labels = sorted(
        {label for row in catalog.entries for label in row.pack.applicable_classifications}
    )
    out = {}
    for call in calls:
        materials = []
        for mid in call.material_ids:
            if mid not in entries:
                raise ValueError("call material outside corpus")
            materials.append(
                {
                    "material_id": mid,
                    "blocks": [
                        {
                            "block_ref": p.block_ref,
                            "text": blocks[mid][(p.revision_id, p.block_id)].text,
                        }
                        for p in sorted(pages[mid], key=lambda x: x.block_ref)
                    ],
                }
            )
        out[call.call_id] = canonical_json(
            {
                "contract": "g3-c-classify-prompt-context.830.v1",
                "window_id": call.window_id,
                "materials": materials,
                "allowed_material_roles": roles,
                "allowed_taxonomy_labels": labels,
                "existing_entities": [x.model_dump(mode="json") for x in existing.entities],
                "response_schema": G3SemanticResponseV1.model_json_schema(),
            }
        )
    return out


def _stage_fixed(
    options: ExecutionOptions,
    stage: str,
    chain,
    *,
    context_raws: dict[str, bytes],
    typed: list[tuple[str, str, bytes]],
    preview_raw: bytes | None = None,
):
    purpose, schema_version, role = G3_STAGE_PROFILES[stage]
    identity = next(x.identity for x in options.identities if x.stage == stage)
    configured = [x for x in options.calls if x.stage == stage]
    schema = _schema(stage)
    template, template_raw = _template(stage)
    routing = _hashed(
        G3RoutingLockV1,
        "g3-stage-routing.830.v1",
        "routing_policy_hash",
        contract="g3-stage-routing.830.v1",
        stage=stage,
        purpose=purpose,
        run_schema_version=schema_version,
        role=role,
        identity=identity,
        endpoint_origin=options.route.endpoint_origin,
        endpoint_path=options.route.endpoint_path,
        temperature_micros=options.route.temperature_micros,
        thinking=options.route.thinking,
        response_format=options.route.response_format,
        timeout_seconds=configured[0].timeout_seconds,
        follow_redirects=False,
        fallback_limit=0,
        retry_limit=0,
        template_hash=template.approved_template_hash,
        schema_hash=schema.schema_hash,
    )
    calls = []
    bodies = {}
    from types import SimpleNamespace

    for item in configured:
        ctx = context_raws[item.call_id]
        provisional = G3CallPlanV1(
            call_id=item.call_id,
            ordinal=item.ordinal,
            stage=stage,
            window_id=item.window_id,
            material_ids=item.material_ids,
            input_context_sha256=_sha(ctx),
            endpoint_origin=options.route.endpoint_origin,
            endpoint_path=options.route.endpoint_path,
            identity=identity,
            response_mode="json_object",
            request_body_sha256=ZERO,
            request_bytes=1,
            input_token_estimate=0,
            input_token_ceiling=item.input_token_ceiling,
            output_token_ceiling=item.output_token_ceiling,
            timeout_seconds=item.timeout_seconds,
        )
        body = g3_openai_request_bytes(
            plan=SimpleNamespace(routing_lock=routing),
            call=provisional,
            system=template_raw.decode(),
            user=ctx.decode(),
        )
        estimate = (
            len(body) + options.input_estimator.framing_token_allowance
            if options.input_estimator.mode == "UTF8_BODY_BYTES_PLUS_FRAMING_TOKENS"
            else item.input_token_ceiling
        )
        if options.input_estimator.mode == "PUBLISHED_MAX_RESERVATION" and (
            item.input_token_ceiling
            != min(
                options.public_model_limits.max_input_tokens,
                options.public_model_limits.context_tokens - item.output_token_ceiling,
            )
        ):
            raise ValueError("published max reservation ceiling mismatch")
        call = provisional.model_copy(
            update={
                "request_body_sha256": _sha(body),
                "request_bytes": len(body),
                "input_token_estimate": estimate,
            }
        )
        if (
            item.input_token_ceiling > options.public_model_limits.max_input_tokens
            or item.output_token_ceiling > options.public_model_limits.max_output_tokens
            or item.input_token_ceiling + item.output_token_ceiling
            > options.public_model_limits.context_tokens
        ):
            raise ValueError("call exceeds public model limits")
        calls.append(call)
        bodies[item.call_id] = body
    calls = tuple(calls)
    manifest = _hashed(
        G3RequestManifestV1,
        "g3-request-manifest.830.v1",
        "manifest_hash",
        contract="g3-request-manifest.830.v1",
        stage=stage,
        chain_id=options.chain_id,
        calls=calls,
    )
    index = canonical_json(
        {
            "contract": "g3-stage-render-contexts.830.v1",
            "stage": stage,
            "calls": [
                {
                    "call_id": x.call_id,
                    "ordinal": x.ordinal,
                    "input_context_sha256": x.input_context_sha256,
                }
                for x in calls
            ],
        }
    )
    if stage == "C_CLASSIFY":
        preview_raw = canonical_json(
            {
                "contract": "g3-c-prompt-preview.830.v1",
                "calls": [
                    {
                        "call_id": x.call_id,
                        "ordinal": x.ordinal,
                        "window_id": x.window_id,
                        "material_ids": list(x.material_ids),
                        "input_context_sha256": x.input_context_sha256,
                        "request_body_sha256": x.request_body_sha256,
                        "system": template_raw.decode(),
                        "user": context_raws[x.call_id].decode(),
                    }
                    for x in calls
                ],
            }
        )
    artifacts = [_ref(c, r, f) for c, f, r in typed]
    artifacts += [
        _ref("g3-rendered-call-context.830.v1", context_raws[x.call_id], "call-context.json")
        for x in calls
    ]
    artifacts += [_ref("g3-stage-render-contexts.830.v1", index, "stage-contexts.json")]
    if preview_raw is not None:
        artifacts += [_ref("g3-c-prompt-preview.830.v1", preview_raw, "prompt-preview.json")]
    artifacts += [
        _ref("g3-http-request-body.830.v1", bodies[x.call_id], "request-body.json") for x in calls
    ]
    artifacts = tuple(sorted(artifacts, key=lambda x: (x.contract, x.artifact_ref)))
    dispatch = _hashed(
        G3StageDispatchLockV1,
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        contract="g3-stage-dispatch.830.v1",
        stage=stage,
        calls=calls,
        opaque_block_map_sha256=next(
            (x.sha256 for x in artifacts if x.contract == "g3-native-page-projections.830.v1"), None
        )
        if stage == "C_CLASSIFY"
        else None,
        input_context_sha256=_sha(index),
        schema_hash=schema.schema_hash,
        template_hash=template.approved_template_hash,
    )
    caps = _hashed(
        G3StageCapsV1,
        "g3-stage-caps.830.v1",
        "caps_sha256",
        contract="g3-stage-caps.830.v1",
        stage=stage,
        worker_limit=1,
        call_limit=len(calls),
        attempts_per_call=1,
        retry_limit=0,
        input_token_ceiling=sum(x.input_token_ceiling for x in calls),
        output_token_ceiling=sum(x.output_token_ceiling for x in calls),
        time_limit_seconds=sum(x.timeout_seconds for x in calls),
    )
    return {
        "purpose": purpose,
        "schema_version": schema_version,
        "role": role,
        "identity": identity,
        "schema": schema,
        "template": template,
        "template_raw": template_raw,
        "routing": routing,
        "calls": calls,
        "manifest": manifest,
        "index": index,
        "preview": preview_raw,
        "bodies": bodies,
        "artifacts": artifacts,
        "dispatch": dispatch,
        "caps": caps,
    }


def _seed_installed(seed: G3ProtocolSeedLockV1, seed_raw: bytes):
    ref = _ref(seed.seed_artifact.contract, seed_raw, "protocol-seed-artifact.json")
    return _hashed(
        G3ProtocolSeedLockV1,
        "g3-protocol-seed.830.v1",
        "golden_slice_hash",
        contract=seed.contract,
        seed_artifact=ref,
        denominator_material_ids=seed.denominator_material_ids,
        expected_coverage_codes=seed.expected_coverage_codes,
        quality_authority=False,
    )


def _parent(options, chain, space_id, materials, manifest_hash, preview_sha):
    ident = options.identities[0].identity
    return G3ModelProcessingAuthorizationV1(
        contract="g3-model-processing-authorization.830.v1",
        authorization_id=options.authorization_id,
        chain_manifest=chain,
        chain_manifest_hash=chain.chain_manifest_hash,
        space_id=space_id,
        provider=ident.provider,
        endpoint_origin=options.route.endpoint_origin,
        deployment_id=ident.deployment_id,
        family=ident.family,
        policy_version=ident.policy_version,
        c_materials=materials,
        c_request_manifest_hash=manifest_hash,
        c_prompt_preview_sha256=preview_sha,
        allowed_stages=("C_CLASSIFY", "D_COMPILE", "D_REVIEW"),
        allowed_roles=("classify", "extract", "verify"),
        allowed_derived_data_categories=tuple(
            sorted(
                (
                    "C_W1_SOURCE",
                    "C_CATALOG_POLICY_SNAPSHOT",
                    "C_EXISTING_ENTITY_SNAPSHOT",
                    "D_AUTOMATIC_CHILD_SOURCE_CLOSURE",
                    "D_CATALOG_PROFILE_BASE",
                    "D_COMPOSED_CANDIDATE_REVIEW_CONTEXT",
                )
            )
        ),
        derivation_rules_version="g3-c-to-d-derivation.830.v1",
        max_calls=chain.max_calls,
        total_input_token_ceiling=chain.total_input_token_ceiling,
        total_output_token_ceiling=chain.total_output_token_ceiling,
        total_time_limit_seconds=chain.total_time_limit_seconds,
        retry_limit=0,
        worker_limit=1,
        delegated_stage_signer=options.delegated_stage_signer,
        expires_at=options.expires_at,
    )


def _plan(options, chain, parent, parent_digest, seed, stage, parts, prior=None):
    calls = parts["calls"]
    artifacts = parts["artifacts"]
    if stage == "C_CLASSIFY":
        binding_hashes = sorted(
            {
                h
                for m in parent.c_materials
                for h in (
                    m.corpus_entry_sha256,
                    m.source_revision_receipt_sha256,
                    m.w1_sha256,
                    m.native_page_map_sha256,
                )
            }
            | {parent.c_prompt_preview_sha256}
        )
        checks = (
            G3EligibilityCheckV1(
                check_id="c-parent-material-bindings",
                check_kind="exact-parent-material-bindings",
                subject_id="all-authorized-c-materials",
                input_sha256s=tuple(binding_hashes),
                observed_count=len(parent.c_materials),
                required_min=len(parent.c_materials),
                required_max=len(parent.c_materials),
                status="PASS",
                reason_code="EXACT_BINDINGS_PRESENT",
            ),
        )
        subjects = tuple(x.material_id for x in parent.c_materials)
        derivation_ids = subjects
        categories = ("C_W1_SOURCE",)
        derived = None
    else:
        checks = ()
        subjects = ("c-to-d-compile",) if stage == "D_COMPILE" else ("d-compile-to-review",)
        derivation_ids = subjects
        categories = (
            tuple(sorted(("D_AUTOMATIC_CHILD_SOURCE_CLOSURE", "D_CATALOG_PROFILE_BASE")))
            if stage == "D_COMPILE"
            else ("D_COMPOSED_CANDIDATE_REVIEW_CONTEXT",)
        )
        derived = _hashed(
            G3DerivedStageReceiptV1,
            "g3-derived-stage-receipt.830.v1",
            "receipt_sha256",
            contract="g3-derived-stage-receipt.830.v1",
            parent_authorization_digest=parent_digest,
            stage=stage,
            prior_terminal_receipt_sha256=prior,
            derivation_rules_version="g3-c-to-d-derivation.830.v1",
            input_artifact_sha256s=tuple(sorted({x.sha256 for x in artifacts})),
            derived_request_manifest_hash=parts["manifest"].manifest_hash,
        )
    eligibility = _hashed(
        G3StageEligibilityLockV1,
        "g3-stage-eligibility.830.v1",
        "eligibility_hash",
        contract="g3-stage-eligibility.830.v1",
        stage=stage,
        input_artifacts=artifacts,
        checks=checks,
        eligible_subject_ids=subjects,
    )
    rights = _hashed(
        G3StageRightsLockV1,
        "g3-external-send-rights.830.v1",
        "rights_hash",
        contract="g3-external-send-rights.830.v1",
        parent_authorization_digest=parent_digest,
        stage=stage,
        purpose=parts["purpose"],
        run_schema_version=parts["schema_version"],
        role=parts["role"],
        provider=parts["identity"].provider,
        endpoint_origin=options.route.endpoint_origin,
        endpoint_path=options.route.endpoint_path,
        deployment_id=parts["identity"].deployment_id,
        call_ids=tuple(sorted(x.call_id for x in calls)),
        window_ids=tuple(sorted(x.window_id for x in calls if x.window_id is not None)),
        artifacts=artifacts,
        material_or_derivation_ids=derivation_ids,
        data_categories=categories,
        call_limit=len(calls),
        input_token_ceiling=parts["caps"].input_token_ceiling,
        output_token_ceiling=parts["caps"].output_token_ceiling,
        time_limit_seconds=parts["caps"].time_limit_seconds,
        expires_at=options.expires_at,
        retry_limit=0,
    )
    provenance = _hashed(
        G3StageProvenanceLockV1,
        "g3-stage-provenance.830.v1",
        "provenance_hash",
        contract="g3-stage-provenance.830.v1",
        stage=stage,
        artifacts=artifacts,
        prior_terminal_receipt_sha256=prior,
    )
    resource = ResourceCaps(
        worker_limit=1,
        attempt_limit=len(calls),
        time_limit_seconds=parts["caps"].time_limit_seconds,
        token_limit=parts["caps"].input_token_ceiling + parts["caps"].output_token_ceiling,
    )
    run = next(x for x in options.stage_runs if x.stage == stage)
    result = G3BoundedAdmissionPlanV1(
        contract="g3-bounded-admission-plan.830.v1",
        stage=stage,
        purpose=parts["purpose"],
        run_schema_version=parts["schema_version"],
        run_id=run.run_id,
        run_revision=run.run_revision,
        space_id=parent.space_id,
        chain_id=options.chain_id,
        chain_manifest=chain,
        chain_manifest_hash=chain.chain_manifest_hash,
        parent_authorization_digest=parent_digest,
        prior_terminal_receipt_sha256=prior,
        derived_stage_receipt=derived,
        request_manifest=parts["manifest"],
        manifest_hash=parts["manifest"].manifest_hash,
        eligibility_lock=eligibility,
        eligibility_hash=eligibility.eligibility_hash,
        protocol_seed_lock=seed,
        golden_slice_hash=seed.golden_slice_hash,
        routing_lock=parts["routing"],
        routing_policy_hash=parts["routing"].routing_policy_hash,
        schema_lock=parts["schema"],
        schema_hash=parts["schema"].schema_hash,
        template_lock=parts["template"],
        template_lock_hash=parts["template"].template_lock_hash,
        approved_template_hashes=(parts["template"].approved_template_hash,),
        dispatch_lock=parts["dispatch"],
        structured_dispatch_hash=parts["dispatch"].structured_dispatch_hash,
        approved_identities=(parts["identity"],),
        model_plan_hash=canonical_model_plan_hash((parts["identity"],)),
        deployment_roles_hash=canonical_model_identities_hash((parts["identity"],)),
        stage_caps=parts["caps"],
        resource_caps=resource,
        resource_caps_hash=resource.digest,
        rights_lock=rights,
        rights_hash=rights.rights_hash,
        provenance_lock=provenance,
        provenance_hash=provenance.provenance_hash,
        clean_integration_sha=options.clean_integration_sha,
        expires_at=options.expires_at,
    )
    validate_g3_bounded_plan(result)
    validate_g3_parent_scope(parent, result)
    return result


def _derive_c(builder_dir: Path, options_path: Path):
    options, options_raw = _options(options_path)
    head, status = _git_identity()
    if status or head != options.clean_integration_sha:
        raise ValueError("clean integration identity mismatch")
    raw, result, corpus, native, existing, policy, seed = _builder(builder_dir)
    _, catalog, catalog_raw, _ = _frozen_sources()
    crows = [x for x in options.calls if x.stage == "C_CLASSIFY"]
    if tuple(sorted(m for x in crows for m in x.material_ids)) != tuple(
        x.material_id for x in corpus.entries
    ):
        raise ValueError("C partition does not equal corpus")
    chain = _chain(options)
    if (Path(gateway.G3_LEDGER_ROOT) / "chains" / chain.chain_manifest_hash).exists():
        raise ValueError("chain already exists")
    dummy = []
    for x in crows:
        dummy.append(
            type(
                "Call",
                (),
                {"call_id": x.call_id, "window_id": x.window_id, "material_ids": x.material_ids},
            )()
        )
    contexts = _c_contexts(corpus, native, existing, policy, catalog, dummy)
    catalog_runtime = canonical_json(catalog.model_dump(mode="json", round_trip=True))
    typed = [
        ("batch-corpus.830.g3.v1", "batch-corpus.json", raw["batch-corpus.json"]),
        (
            "batch-resolution-policy.830.g3.v1",
            "batch-resolution-policy.json",
            raw["batch-resolution-policy.json"],
        ),
        ("schema-pack-catalog.830.g3.v1", "catalog.json", catalog_runtime),
        ("existing-entities.830.g3.v1", "existing-entities.json", raw["existing-entities.json"]),
        (
            "g3-native-page-projections.830.v1",
            "g3-native-page-projections.json",
            raw["g3-native-page-projections.json"],
        ),
    ]
    parts = _stage_fixed(options, "C_CLASSIFY", chain, context_raws=contexts, typed=typed)
    materials = _authorized_materials(corpus, native)
    parent = _parent(
        options,
        chain,
        corpus.space_id,
        materials,
        parts["manifest"].manifest_hash,
        _sha(parts["preview"]),
    )
    installed_seed = _seed_installed(seed, raw["protocol-seed-artifact.json"])
    # Prove the final parent makes the production renderer reconstruct exactly these bytes.
    fake_digest = "1" * 64
    check_plan = _plan(options, chain, parent, fake_digest, installed_seed, "C_CLASSIFY", parts)
    artifact_map = {}
    for contract, _, body in typed:
        artifact_map.setdefault(contract, []).append(body)
    rebuilt, index, preview = _render_g3_stage_contexts(
        plan=check_plan, parent=parent, artifacts=artifact_map, template_bytes=parts["template_raw"]
    )
    if rebuilt != contexts or index != parts["index"] or preview != parts["preview"]:
        raise ValueError("production C renderer mismatch")
    if _git_identity() != (head, b""):
        raise ValueError("repository changed during materialization")
    artifact_raw = {(c, f, _sha(b)): b for c, f, b in typed}
    artifact_raw[
        (
            installed_seed.seed_artifact.contract,
            "protocol-seed-artifact.json",
            installed_seed.seed_artifact.sha256,
        )
    ] = raw["protocol-seed-artifact.json"]
    for call in parts["calls"]:
        artifact_raw[
            ("g3-rendered-call-context.830.v1", "call-context.json", call.input_context_sha256)
        ] = contexts[call.call_id]
        artifact_raw[
            ("g3-http-request-body.830.v1", "request-body.json", call.request_body_sha256)
        ] = parts["bodies"][call.call_id]
    artifact_raw[
        ("g3-stage-render-contexts.830.v1", "stage-contexts.json", _sha(parts["index"]))
    ] = parts["index"]
    artifact_raw[("g3-c-prompt-preview.830.v1", "prompt-preview.json", _sha(parts["preview"]))] = (
        parts["preview"]
    )
    return options, options_raw, raw, result, chain, parent, installed_seed, parts, artifact_raw


def _write_file(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _atomic_package(output_dir: Path, files: dict[str, bytes]):
    if output_dir.exists():
        raise ValueError("output directory exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp = output_dir.parent / ("." + output_dir.name + ".tmp")
    lock = output_dir.parent / ("." + output_dir.name + ".lock")
    if temp.exists():
        raise ValueError("temporary directory exists")
    old = os.umask(0o077)
    lock_fd = -1
    try:
        lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fsync(lock_fd)
        if output_dir.exists():
            raise ValueError("output directory exists")
        temp.mkdir(mode=0o700)
        for rel, raw in sorted(files.items()):
            _write_file(temp / rel, raw)
        for directory, _, _ in os.walk(temp, topdown=False):
            fd = os.open(directory, os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        os.replace(temp, output_dir)
        fd = os.open(output_dir.parent, os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
        os.umask(old)


def _install_rows(artifact_raw: dict[tuple[str, str, str], bytes]):
    rows = []
    for (contract, filename, digest), raw in artifact_raw.items():
        if _sha(raw) != digest:
            raise ValueError("artifact raw hash mismatch")
        rel = f"install/sha256/{digest}/{filename}"
        rows.append(
            {
                "contract": contract,
                "source": rel,
                "destination": str(INSTALL_ROOT / "sha256" / digest / filename),
                "sha256": digest,
                "bytes": len(raw),
            }
        )
    rows.sort(key=lambda x: (x["contract"], x["destination"]))
    if len({(x["contract"], x["destination"]) for x in rows}) != len(rows):
        raise ValueError("duplicate import row")
    return rows


def _artifact_files(artifact_raw):
    return {
        f"install/sha256/{digest}/{filename}": raw
        for (_, filename, digest), raw in artifact_raw.items()
    }


def preview_c(builder_dir: Path, execution_options: Path, output_dir: Path):
    options, options_raw, braw, bresult, chain, parent, _, parts, artifact_raw = _derive_c(
        builder_dir, execution_options
    )
    parent_raw = canonical_json(parent.model_dump(mode="json", round_trip=True))
    manifest_raw = canonical_json(parts["manifest"].model_dump(mode="json", round_trip=True))
    chain_raw = canonical_json(chain.model_dump(mode="json", round_trip=True))
    measurements = canonical_json(
        {
            "contract": "g3-model-input-measurements.830.v1",
            "estimator_version": options.input_estimator.version,
            "estimator_mode": options.input_estimator.mode,
            "framing_token_allowance": options.input_estimator.framing_token_allowance,
            "proof_sha256s": list(options.input_estimator.proof_sha256s),
            "public_model_limits": options.public_model_limits.model_dump(mode="json"),
            "public_limit_source_sha256s": list(options.public_model_limits.source_sha256s),
            "calls": [
                {
                    "call_id": x.call_id,
                    "request_bytes": x.request_bytes,
                    "input_token_estimate": x.input_token_estimate,
                    "input_token_ceiling": x.input_token_ceiling,
                    "output_token_ceiling": x.output_token_ceiling,
                    "timeout_seconds": x.timeout_seconds,
                }
                for x in parts["calls"]
            ],
        }
    )
    acq = _strict_json(braw["source-acquisition-bundle.json"], "source acquisition")
    inventory = {
        x["material_id"]: x
        for x in acq.get("materials", [])
        if isinstance(x, dict) and "material_id" in x
    }
    corpus = BatchCorpusV1.model_validate_json(braw["batch-corpus.json"])
    corpus_rows = {row.material_id: row for row in corpus.entries}
    materials = []
    for row in parent.c_materials:
        source = inventory.get(row.material_id, {})
        facts = source.get("facts", {})
        inventory_file = facts.get("inventory_file", {})
        materials.append(
            {
                "material_id": row.material_id,
                "inventory_path": inventory_file.get("path"),
                "source_uri": corpus_rows[row.material_id].provenance.source_uri,
                "corpus_entry_sha256": row.corpus_entry_sha256,
                "source_revision_receipt_sha256": row.source_revision_receipt_sha256,
                "w1_sha256": row.w1_sha256,
                "native_page_map_sha256": row.native_page_map_sha256,
            }
        )
    full = [
        {
            "path": f"install/sha256/{x.request_body_sha256}/request-body.json",
            "sha256": x.request_body_sha256,
            "bytes": x.request_bytes,
        }
        for x in parts["calls"]
    ]
    drows = []
    for stage in ("D_COMPILE", "D_REVIEW"):
        run = next(x for x in options.stage_runs if x.stage == stage)
        call = next(x for x in options.calls if x.stage == stage)
        identity = next(x.identity for x in options.identities if x.stage == stage)
        drows.append(
            {
                "stage": stage,
                "run_id": run.run_id,
                "run_revision": run.run_revision,
                "call_id": call.call_id,
                "identity": identity.model_dump(mode="json"),
                "input_token_ceiling": call.input_token_ceiling,
                "output_token_ceiling": call.output_token_ceiling,
                "timeout_seconds": call.timeout_seconds,
            }
        )
    preview = canonical_json(
        {
            "contract": "g3-model-processing-preview.830.v1",
            "authorization_id": options.authorization_id,
            "chain_id": options.chain_id,
            "recipient": {
                "provider": options.identities[0].identity.provider,
                "origin": options.route.endpoint_origin,
                "deployment": options.identities[0].identity.deployment_id,
                "family": options.identities[0].identity.family,
                "policy": options.identities[0].identity.policy_version,
            },
            "materials": materials,
            "c_calls": [
                {
                    "call_id": x.call_id,
                    "window_id": x.window_id,
                    "material_ids": list(x.material_ids),
                    "request_body_sha256": x.request_body_sha256,
                    "request_bytes": x.request_bytes,
                    "input_context_sha256": x.input_context_sha256,
                    "input_token_estimate": x.input_token_estimate,
                    "input_token_ceiling": x.input_token_ceiling,
                    "output_token_ceiling": x.output_token_ceiling,
                    "timeout_seconds": x.timeout_seconds,
                }
                for x in parts["calls"]
            ],
            "authorized_derivation_stages": drows,
            "derived_data_categories": list(parent.allowed_derived_data_categories),
            "chain_caps": {
                "max_calls": chain.max_calls,
                "total_input_token_ceiling": chain.total_input_token_ceiling,
                "total_output_token_ceiling": chain.total_output_token_ceiling,
                "total_time_limit_seconds": chain.total_time_limit_seconds,
            },
            "expires_at": parent.model_dump(mode="json")["expires_at"],
            "expected_parent_approver": options.expected_parent_approver.model_dump(mode="json"),
            "delegated_stage_signer": options.delegated_stage_signer.model_dump(mode="json"),
            "public_model_limits": options.public_model_limits.model_dump(mode="json"),
            "public_limit_source_sha256s": list(options.public_model_limits.source_sha256s),
            "clean_integration_sha": options.clean_integration_sha,
            "parent_payload_sha256": _sha(parent_raw),
            "full_request_artifacts": full,
        }
    )
    rows = _install_rows(artifact_raw)
    result = canonical_json(
        {
            "contract": "g3-model-processing-review-package-result.830.v1",
            "status": "READY_FOR_MODEL_PROCESSING_REVIEW",
            "design_sha256": DESIGN_SHA256,
            "builder_result_sha256": _sha(braw["builder-result.json"]),
            "execution_options_sha256": _sha(options_raw),
            "clean_integration_sha": options.clean_integration_sha,
            "parent_payload_sha256": _sha(parent_raw),
            "request_manifest_sha256": _sha(manifest_raw),
            "chain_manifest_sha256": _sha(chain_raw),
            "measurements_sha256": _sha(measurements),
            "preview_sha256": _sha(preview),
            "install_manifest": rows,
            "effects": {"http": 0, "provider": 0, "database": 0, "docker": 0, "signatures": 0},
        }
    )
    files = _artifact_files(artifact_raw) | {
        "execution-options.json": options_raw,
        "parent-payload.json": parent_raw,
        "c-request-manifest.json": manifest_raw,
        "c-chain-manifest.json": chain_raw,
        "c-measurements.json": measurements,
        "model-processing-preview.json": preview,
        "review-package-result.json": result,
        "proof/source-acquisition-bundle.json": braw["source-acquisition-bundle.json"],
        "proof/builder-result.json": braw["builder-result.json"],
    }
    _atomic_package(output_dir, files)
    return _sha(result)


def _review_package(review_dir: Path):
    directory_info = review_dir.stat(follow_symlinks=False)
    if review_dir.is_symlink() or not stat.S_ISDIR(directory_info.st_mode):
        raise ValueError("review package is not a real directory")
    names = {
        "execution-options.json",
        "parent-payload.json",
        "c-request-manifest.json",
        "c-chain-manifest.json",
        "c-measurements.json",
        "model-processing-preview.json",
        "review-package-result.json",
        "install",
        "proof",
    }
    if set(x.name for x in review_dir.iterdir()) != names:
        raise ValueError("review package file set drift")
    raws = {
        name: _regular(review_dir / name)
        for name in names
        if name not in {"install", "proof"}
    }
    for name, raw in raws.items():
        if name == "model-processing-preview.json":
            _canonical_wire_json(raw, name)
        else:
            value = _strict_json(raw, name)
            if canonical_json(value) != raw:
                raise ValueError(f"noncanonical JSON: {name}")
    proof_dir = review_dir / "proof"
    proof_info = proof_dir.stat(follow_symlinks=False)
    proof_names = {"source-acquisition-bundle.json", "builder-result.json"}
    if (
        proof_dir.is_symlink()
        or not stat.S_ISDIR(proof_info.st_mode)
        or set(item.name for item in proof_dir.iterdir()) != proof_names
    ):
        raise ValueError("review proof file set drift")
    proof_raws = {}
    for name in proof_names:
        path = proof_dir / name
        _no_symlink_ancestors(path, review_dir)
        proof_raws[name] = _regular(path, canonical=True)
    options = ExecutionOptions.model_validate_json(raws["execution-options.json"])
    parent = G3ModelProcessingAuthorizationV1.model_validate_json(raws["parent-payload.json"])
    manifest = G3RequestManifestV1.model_validate_json(raws["c-request-manifest.json"])
    chain = G3ChainManifestV1.model_validate_json(raws["c-chain-manifest.json"])
    result = _strict_json(raws["review-package-result.json"], "review package result")
    result_keys = {
        "contract",
        "status",
        "design_sha256",
        "builder_result_sha256",
        "execution_options_sha256",
        "clean_integration_sha",
        "parent_payload_sha256",
        "request_manifest_sha256",
        "chain_manifest_sha256",
        "measurements_sha256",
        "preview_sha256",
        "install_manifest",
        "effects",
    }
    if (
        not isinstance(result, dict)
        or set(result) != result_keys
        or result.get("contract") != "g3-model-processing-review-package-result.830.v1"
        or result.get("status") != "READY_FOR_MODEL_PROCESSING_REVIEW"
    ):
        raise ValueError("review result key set or status invalid")
    links = {
        "execution_options_sha256": "execution-options.json",
        "parent_payload_sha256": "parent-payload.json",
        "request_manifest_sha256": "c-request-manifest.json",
        "chain_manifest_sha256": "c-chain-manifest.json",
        "measurements_sha256": "c-measurements.json",
        "preview_sha256": "model-processing-preview.json",
    }
    if (
        any(result.get(k) != _sha(raws[v]) for k, v in links.items())
        or result.get("builder_result_sha256") != _sha(proof_raws["builder-result.json"])
        or result.get("design_sha256") != DESIGN_SHA256
        or result.get("clean_integration_sha") != options.clean_integration_sha
        or result.get("effects")
        != {"http": 0, "provider": 0, "database": 0, "docker": 0, "signatures": 0}
    ):
        raise ValueError("review result cross-link mismatch")
    if (
        parent.chain_manifest != chain
        or parent.c_request_manifest_hash != manifest.manifest_hash
        or parent.chain_manifest_hash != chain.chain_manifest_hash
        or options.chain_id != chain.chain_id
        or chain.clean_integration_sha != options.clean_integration_sha
    ):
        raise ValueError("review parent/chain mismatch")
    head, status = _git_identity()
    if status or head != options.clean_integration_sha:
        raise ValueError("review package clean integration identity mismatch")
    preview_value = _canonical_wire_json(raws["model-processing-preview.json"], "model preview")
    if preview_value.get("clean_integration_sha") != options.clean_integration_sha:
        raise ValueError("review preview clean integration mismatch")
    rows = result.get("install_manifest")
    if not isinstance(rows, list) or rows != sorted(
        rows, key=lambda x: (x["contract"], x["destination"])
    ):
        raise ValueError("review import rows invalid")
    artifact_raw = {}
    for row in rows:
        if set(row) != {"contract", "source", "destination", "sha256", "bytes"}:
            raise ValueError("review import row keys drift")
        expected = f"install/sha256/{row['sha256']}/{Path(row['destination']).name}"
        if row["source"] != expected or row["destination"] != str(
            INSTALL_ROOT / "sha256" / row["sha256"] / Path(row["destination"]).name
        ):
            raise ValueError("review import row path drift")
        source_path = review_dir / row["source"]
        _no_symlink_ancestors(source_path, review_dir)
        raw = _regular(source_path)
        _validate_artifact_wire(row["contract"], raw, str(source_path))
        if _sha(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise ValueError("review install artifact mismatch")
        artifact_raw[(row["contract"], Path(row["destination"]).name, row["sha256"])] = raw
    counts: dict[str, int] = {}
    for contract, _, _ in artifact_raw:
        counts[contract] = counts.get(contract, 0) + 1
    call_count = len(manifest.calls)
    expected_counts = {
        "batch-corpus.830.g3.v1": 1,
        "batch-resolution-policy.830.g3.v1": 1,
        "schema-pack-catalog.830.g3.v1": 1,
        "existing-entities.830.g3.v1": 1,
        "g3-native-page-projections.830.v1": 1,
        "g3-protocol-seed-artifact.830.v1": 1,
        "g3-rendered-call-context.830.v1": call_count,
        "g3-stage-render-contexts.830.v1": 1,
        "g3-c-prompt-preview.830.v1": 1,
        "g3-http-request-body.830.v1": call_count,
    }
    if counts != expected_counts:
        raise ValueError("review install artifact contract set drift")
    original_contracts = {
        "batch-corpus.830.g3.v1": "batch-corpus.json",
        "g3-native-page-projections.830.v1": "g3-native-page-projections.json",
        "existing-entities.830.g3.v1": "existing-entities.json",
        "batch-resolution-policy.830.g3.v1": "batch-resolution-policy.json",
        "g3-protocol-seed-artifact.830.v1": "protocol-seed-artifact.json",
    }
    builder_raw = {
        "source-acquisition-bundle.json": proof_raws["source-acquisition-bundle.json"],
        "builder-result.json": proof_raws["builder-result.json"],
    }
    for contract, filename in original_contracts.items():
        matches = [raw for (key, name, _), raw in artifact_raw.items() if key == contract and name == filename]
        if len(matches) != 1:
            raise ValueError("review builder proof artifact set drift")
        builder_raw[filename] = matches[0]
    _validate_builder_proof(builder_raw)
    if _git_identity() != (head, b""):
        raise ValueError("repository changed during review package validation")
    return options, parent, manifest, chain, result, raws, artifact_raw


def _parts_from_artifacts(options, parent, stage, manifest, artifact_raw):
    by_contract = {}
    for (contract, _, _), raw in artifact_raw.items():
        by_contract.setdefault(contract, []).append(raw)
    schema = _schema(stage)
    template, template_raw = _template(stage)
    identity = next(x.identity for x in options.identities if x.stage == stage)
    purpose, schema_version, role = G3_STAGE_PROFILES[stage]
    configured = [x for x in options.calls if x.stage == stage]
    if tuple(
        (
            x.call_id,
            x.ordinal,
            x.window_id,
            x.material_ids,
            x.input_token_ceiling,
            x.output_token_ceiling,
            x.timeout_seconds,
        )
        for x in manifest.calls
    ) != tuple(
        (
            x.call_id,
            x.ordinal,
            x.window_id,
            x.material_ids,
            x.input_token_ceiling,
            x.output_token_ceiling,
            x.timeout_seconds,
        )
        for x in configured
    ):
        raise ValueError("review call projection mismatch")
    routing = _hashed(
        G3RoutingLockV1,
        "g3-stage-routing.830.v1",
        "routing_policy_hash",
        contract="g3-stage-routing.830.v1",
        stage=stage,
        purpose=purpose,
        run_schema_version=schema_version,
        role=role,
        identity=identity,
        endpoint_origin=options.route.endpoint_origin,
        endpoint_path=options.route.endpoint_path,
        temperature_micros=0,
        thinking=options.route.thinking,
        response_format="json_object",
        timeout_seconds=configured[0].timeout_seconds,
        follow_redirects=False,
        fallback_limit=0,
        retry_limit=0,
        template_hash=template.approved_template_hash,
        schema_hash=schema.schema_hash,
    )
    artifacts = tuple(
        sorted(
            (
                _ref(c, raw, f)
                for (c, f, _), raw in artifact_raw.items()
                if c != "g3-protocol-seed-artifact.830.v1"
            ),
            key=lambda x: (x.contract, x.artifact_ref),
        )
    )
    index = next(iter(by_contract["g3-stage-render-contexts.830.v1"]))
    preview = next(iter(by_contract.get("g3-c-prompt-preview.830.v1", [])), None)
    calls = manifest.calls
    dispatch = _hashed(
        G3StageDispatchLockV1,
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        contract="g3-stage-dispatch.830.v1",
        stage=stage,
        calls=calls,
        opaque_block_map_sha256=next(
            (x.sha256 for x in artifacts if x.contract == "g3-native-page-projections.830.v1"), None
        )
        if stage == "C_CLASSIFY"
        else None,
        input_context_sha256=_sha(index),
        schema_hash=schema.schema_hash,
        template_hash=template.approved_template_hash,
    )
    caps = _hashed(
        G3StageCapsV1,
        "g3-stage-caps.830.v1",
        "caps_sha256",
        contract="g3-stage-caps.830.v1",
        stage=stage,
        worker_limit=1,
        call_limit=len(calls),
        attempts_per_call=1,
        retry_limit=0,
        input_token_ceiling=sum(x.input_token_ceiling for x in calls),
        output_token_ceiling=sum(x.output_token_ceiling for x in calls),
        time_limit_seconds=sum(x.timeout_seconds for x in calls),
    )
    return {
        "purpose": purpose,
        "schema_version": schema_version,
        "role": role,
        "identity": identity,
        "schema": schema,
        "template": template,
        "template_raw": template_raw,
        "routing": routing,
        "calls": calls,
        "manifest": manifest,
        "index": index,
        "preview": preview,
        "bodies": {
            x.call_id: next(
                raw
                for (c, _, d), raw in artifact_raw.items()
                if c == "g3-http-request-body.830.v1" and d == x.request_body_sha256
            )
            for x in calls
        },
        "artifacts": artifacts,
        "dispatch": dispatch,
        "caps": caps,
        "by_contract": by_contract,
    }


def _verify_parent(
    raw: bytes, reviewed: G3ModelProcessingAuthorizationV1, options: ExecutionOptions
):
    if canonical_json(_strict_json(raw, "signed parent")) != raw:
        raise ValueError("signed parent is noncanonical")
    envelope = G3ModelProcessingAuthorizationEnvelopeV1.model_validate_json(raw)
    if canonical_json(envelope.payload.model_dump(mode="json", round_trip=True)) != canonical_json(
        reviewed.model_dump(mode="json", round_trip=True)
    ):
        raise ValueError("signed parent payload differs from review")
    expected = options.expected_parent_approver
    if (
        envelope.key_id,
        envelope.public_key_fingerprint,
        envelope.human_identity,
        envelope.approver_role,
        envelope.signature_domain,
    ) != (
        expected.key_id,
        expected.public_key_fingerprint,
        expected.human_identity,
        expected.approver_role,
        expected.signature_domain,
    ):
        raise ValueError("signed parent metadata differs from review")
    verify_parent_authorization(load_g3_root_trust_policy(), envelope)
    return envelope


def _materialization_package(
    output_dir,
    *,
    command,
    stage,
    review_result_sha,
    options_raw,
    parent_raw,
    prior,
    plan,
    artifact_raw,
):
    plan_raw = canonical_json(plan.model_dump(mode="json", round_trip=True))
    pd = _sha(parent_raw)
    combined = dict(artifact_raw)
    if command == "materialize-c":
        combined[
            (
                "g3-model-processing-authorization-envelope.830.v1",
                "model-processing-authorization.json",
                pd,
            )
        ] = parent_raw
    combined[("g3-bounded-admission-plan.830.v1", "stage-input.json", _sha(plan_raw))] = plan_raw
    rows = _install_rows(combined)
    manifest = canonical_json(
        {"contract": "g3-stage-import-manifest.830.v1", "stage": stage, "rows": rows}
    )
    result = canonical_json(
        {
            "contract": "g3-actual-stage-materialization-result.830.v1",
            "status": "READY_FOR_IMPORT_AND_PREPARE_STAGE",
            "design_sha256": DESIGN_SHA256,
            "command": command,
            "stage": stage,
            "review_package_result_sha256": review_result_sha,
            "execution_options_sha256": _sha(options_raw),
            "parent_authorization_sha256": pd,
            "prior_terminal_receipt_sha256": prior,
            "stage_input_sha256": _sha(plan_raw),
            "import_manifest_sha256": _sha(manifest),
            "effects": {"http": 0, "provider": 0, "database": 0, "docker": 0, "signatures": 0},
        }
    )
    files = _artifact_files(combined) | {
        "import-manifest.json": manifest,
        "materialization-result.json": result,
    }
    _atomic_package(output_dir, files)
    return _sha(result)


def materialize_c(review_dir: Path, signed_parent: Path, output_dir: Path):
    options, parent, manifest, chain, result, raws, artifact_raw = _review_package(review_dir)
    head, status = _git_identity()
    if status or head != options.clean_integration_sha:
        raise ValueError("clean integration identity mismatch")
    if (Path(gateway.G3_LEDGER_ROOT) / "chains" / chain.chain_manifest_hash).exists():
        raise ValueError("chain already exists")
    parent_raw = _regular(signed_parent, canonical=True)
    _verify_parent(parent_raw, parent, options)
    pd = _sha(parent_raw)
    parts = _parts_from_artifacts(options, parent, "C_CLASSIFY", manifest, artifact_raw)
    seed_raw = next(
        raw for (c, _, _), raw in artifact_raw.items() if c == "g3-protocol-seed-artifact.830.v1"
    )
    seed_value = _strict_json(seed_raw, "seed artifact")
    expectations = seed_value.get("material_expectations")
    coverage = seed_value.get("expected_coverage_codes")
    if (
        seed_value.get("contract") != "g3-protocol-seed-artifact.830.v1"
        or not isinstance(expectations, list)
        or not isinstance(coverage, list)
    ):
        raise ValueError("reviewed Seed artifact shape drift")
    denominator = tuple(row.get("material_id") for row in expectations)
    if denominator != tuple(x.material_id for x in parent.c_materials):
        raise ValueError("reviewed Seed denominator drift")
    seed = _hashed(
        G3ProtocolSeedLockV1,
        "g3-protocol-seed.830.v1",
        "golden_slice_hash",
        contract="g3-protocol-seed-lock.830.v1",
        seed_artifact=_ref(
            "g3-protocol-seed-artifact.830.v1", seed_raw, "protocol-seed-artifact.json"
        ),
        denominator_material_ids=denominator,
        expected_coverage_codes=tuple(coverage),
        quality_authority=False,
    )
    plan = _plan(options, chain, parent, pd, seed, "C_CLASSIFY", parts)
    rebuilt, index, preview = _render_g3_stage_contexts(
        plan=plan,
        parent=parent,
        artifacts=parts["by_contract"],
        template_bytes=parts["template_raw"],
    )
    if index != parts["index"] or preview != parts["preview"]:
        raise ValueError("review renderer drift")
    for call in plan.request_manifest.calls:
        body = g3_openai_request_bytes(
            plan=plan,
            call=call,
            system=parts["template_raw"].decode(),
            user=rebuilt[call.call_id].decode(),
        )
        if body != parts["bodies"][call.call_id]:
            raise ValueError("review request body drift")
    if _git_identity() != (head, b""):
        raise ValueError("repository changed during materialization")
    return _materialization_package(
        output_dir,
        command="materialize-c",
        stage="C_CLASSIFY",
        review_result_sha=_sha(raws["review-package-result.json"]),
        options_raw=raws["execution-options.json"],
        parent_raw=parent_raw,
        prior=None,
        plan=plan,
        artifact_raw=artifact_raw,
    )


def _read_runtime_json(path: Path, cls):
    raw = runtime._read_secure_exact(path)
    value = cls.model_validate_json(raw)
    if canonical_json(value.model_dump(mode="json", round_trip=True)) != raw:
        raise ValueError(f"noncanonical runtime artifact: {path}")
    return value, raw


def _prior_stage(parent_envelope, parent_raw, chain, stage):
    prior_stage = "C_CLASSIFY" if stage == "D_COMPILE" else "D_COMPILE"
    chain_dir = Path(gateway.G3_LEDGER_ROOT) / "chains" / chain.chain_manifest_hash
    terminal, terminal_raw = _read_runtime_json(
        chain_dir / "stage-terminals" / f"{prior_stage}.json", G3StageTerminalReceiptV1
    )
    pd = _sha(parent_raw)
    if (
        terminal.stage != prior_stage
        or terminal.status != "SUCCESS"
        or terminal.chain_id != chain.chain_id
        or terminal.parent_authorization_digest != pd
        or terminal.receipt_sha256
        != canonical_g3_hash("g3-stage-terminal-receipt.830.v1", terminal, "receipt_sha256")
    ):
        raise ValueError("prior stage terminal invalid")
    admission_path = (
        Path(evaluator._ADMISSION_STORE_ROOT)
        / "sha256"
        / terminal.admission_artifact_digest
        / "approval-envelope.json"
    )
    approval, approval_raw = _read_runtime_json(admission_path, G3BoundedApprovalEnvelopeV1)
    if (
        _sha(approval_raw) != terminal.admission_artifact_digest
        or approval.parent_authorization_digest != pd
        or approval.payload.stage != prior_stage
        or approval.payload.chain_manifest != chain
    ):
        raise ValueError("prior approval mismatch")
    verify_delegated_stage_signature(parent_envelope, approval)
    validate_g3_bounded_plan(approval.payload)
    validate_g3_parent_scope(parent_envelope.payload, approval.payload)
    evaluator._verify_g3_current_content(approval.payload, parent_envelope.payload)
    reopened = tuple(
        gateway._read_successful_g3_stage_call(
            plan=approval.payload,
            call=call,
            admission_artifact_digest=terminal.admission_artifact_digest,
        )
        for call in approval.payload.request_manifest.calls
    )
    if (
        any(item is None for item in reopened)
        or tuple(item[0].receipt_sha256 for item in reopened if item is not None)
        != terminal.call_terminal_sha256s
    ):
        raise ValueError("prior call ledger closure mismatch")
    result_dir = chain_dir / "stage-results" / prior_stage
    if prior_stage == "C_CLASSIFY":
        proposal, proposal_raw = _read_runtime_json(
            result_dir / "proposal-batch.json", ProposalBatchV1
        )
        resolution, resolution_raw = _read_runtime_json(
            result_dir / "resolution.json", BatchEntityResolutionV1
        )
        if (
            resolution.proposals_sha256 != proposal.proposals_sha256
            or terminal.stage_output_sha256 != resolution.batch_sha256
        ):
            raise ValueError("C result closure mismatch")
        results = {"proposal": (proposal, proposal_raw), "resolution": (resolution, resolution_raw)}
    else:
        model, model_raw = _read_runtime_json(
            result_dir / "model-compile-result.json", CompileResult
        )
        final, final_raw = _read_runtime_json(
            result_dir / "final-compile-result.json", CompileResult
        )
        if terminal.stage_output_sha256 != compile_output_hash_g3(final.output):
            raise ValueError("D compile output closure mismatch")
        results = {"model": (model, model_raw), "final": (final, final_raw)}
    return terminal, terminal_raw, approval, results


def _reject_current_or_later(chain_hash: str, stage: str):
    chain_dir = Path(gateway.G3_LEDGER_ROOT) / "chains" / chain_hash
    stages = ("D_COMPILE", "D_REVIEW") if stage == "D_COMPILE" else ("D_REVIEW",)
    for current in stages:
        candidates = (
            chain_dir / "stage-terminals" / f"{current}.json",
            chain_dir / "stage-results" / current,
            chain_dir / "stage-bindings" / f"{current}.json",
        )
        if any(x.exists() for x in candidates):
            raise ValueError("current or later stage state exists")


def _artifact_from_plan(plan, contract):
    refs = [x for x in plan.eligibility_lock.input_artifacts if x.contract == contract]
    if len(refs) != 1:
        raise ValueError(f"expected one prior artifact {contract}")
    return evaluator._read_g3_artifact(refs[0])


def materialize_d(stage: str, signed_parent: Path, review_dir: Path, output_dir: Path):
    if stage not in ("D_COMPILE", "D_REVIEW"):
        raise ValueError("invalid D stage")
    options, parent, _, chain, result, raws, _ = _review_package(review_dir)
    expected_parent = (
        Path(evaluator._ADMISSION_STORE_ROOT)
        / "sha256"
        / signed_parent.parent.name
        / "model-processing-authorization.json"
    )
    if signed_parent != expected_parent:
        raise ValueError("signed parent path is not fixed content-addressed path")
    parent_raw = evaluator._read_g3_parent(str(signed_parent), signed_parent.parent.name)
    if canonical_json(_strict_json(parent_raw, "installed signed parent")) != parent_raw:
        raise ValueError("installed signed parent is noncanonical")
    envelope = _verify_parent(parent_raw, parent, options)
    if _sha(parent_raw) != signed_parent.parent.name:
        raise ValueError("signed parent path digest mismatch")
    head, status = _git_identity()
    if status or head != options.clean_integration_sha:
        raise ValueError("clean integration identity mismatch")
    _reject_current_or_later(chain.chain_manifest_hash, stage)
    terminal, terminal_raw, prior_approval, results = _prior_stage(
        envelope, parent_raw, chain, stage
    )
    pd = _sha(parent_raw)
    if stage == "D_COMPILE":
        cplan = prior_approval.payload
        corpus = BatchCorpusV1.model_validate_json(
            _artifact_from_plan(cplan, "batch-corpus.830.g3.v1")
        )
        existing = ExistingEntitySnapshotV1.model_validate_json(
            _artifact_from_plan(cplan, "existing-entities.830.g3.v1")
        )
        policy = BatchResolutionPolicyV1.model_validate_json(
            _artifact_from_plan(cplan, "batch-resolution-policy.830.g3.v1")
        )
        proposal = results["proposal"][0]
        resolution = results["resolution"][0]
        selected = tuple(
            sorted(
                {
                    (decision.material_id, child.proposal_ref)
                    for decision in resolution.decisions
                    for child in decision.children
                    if child.disposition in ("MATCH", "CREATE")
                }
            )
        )
        if not selected:
            raise ValueError("no automatic children for D compile")
        g2, _, catalog_raw, profile_raw = _frozen_sources()
        request = build_batch_compile_request(
            base_request=g2.request,
            catalog_json=catalog_raw,
            profile_confirmation_json=profile_raw,
            corpus=corpus,
            proposals=proposal,
            existing_entities=existing,
            policy=policy,
            resolution=resolution,
            selected_decision_refs=selected,
        )
        request_raw = canonical_json(request.model_dump(mode="json", round_trip=True))
        typed = [
            (
                "batch-concept-compile-request.830.g3.v1",
                "batch-concept-compile-request.json",
                request_raw,
            )
        ]
        call = next(x for x in options.calls if x.stage == stage)
        contexts = {
            call.call_id: batch_json_bytes_830_g3(
                {
                    "contract": "g3-d-compile-prompt-context.830.v1",
                    "context": compiler_context_g3(request),
                    "response_schema": __import__(
                        "insurance_harness.knowledge_compiler.concept_compile_830_g2",
                        fromlist=["CompileOutput"],
                    ).CompileOutput.model_json_schema(),
                }
            )
        }
    else:
        dplan = prior_approval.payload
        request_raw = _artifact_from_plan(dplan, "batch-concept-compile-request.830.g3.v1")
        request = BatchConceptCompileRequest830G3V1.model_validate_json(request_raw)
        model, model_raw = results["model"]
        final, final_raw = results["final"]
        typed = [
            (
                "batch-concept-compile-request.830.g3.v1",
                "batch-concept-compile-request.json",
                request_raw,
            ),
            ("g3-d-model-compile-result.830.v1", "model-compile-result.json", model_raw),
            ("g3-d-final-compile-result.830.v1", "final-compile-result.json", final_raw),
        ]
        call = next(x for x in options.calls if x.stage == stage)
        contexts = {
            call.call_id: batch_json_bytes_830_g3(
                {
                    "contract": "g3-d-review-prompt-context.830.v1",
                    "context": review_context_g3(request, final.output),
                    "response_schema": __import__(
                        "insurance_harness.knowledge_compiler.concept_compile_830_g2",
                        fromlist=["ReviewOutput"],
                    ).ReviewOutput.model_json_schema(),
                }
            )
        }
    parts = _stage_fixed(options, stage, chain, context_raws=contexts, typed=typed)
    seed = prior_approval.payload.protocol_seed_lock
    plan = _plan(options, chain, parent, pd, seed, stage, parts, prior=terminal.receipt_sha256)
    by_contract = {}
    for c, _, raw in typed:
        by_contract.setdefault(c, []).append(raw)
    rebuilt, index, _ = _render_g3_stage_contexts(
        plan=plan, parent=parent, artifacts=by_contract, template_bytes=parts["template_raw"]
    )
    if index != parts["index"] or rebuilt != contexts:
        raise ValueError("production D renderer mismatch")
    runtime._validate_g3_prior_stage_results(plan, by_contract)
    artifact_raw = {(c, f, _sha(raw)): raw for c, f, raw in typed}
    for plan_call in parts["calls"]:
        artifact_raw[
            ("g3-rendered-call-context.830.v1", "call-context.json", plan_call.input_context_sha256)
        ] = contexts[plan_call.call_id]
        artifact_raw[
            ("g3-http-request-body.830.v1", "request-body.json", plan_call.request_body_sha256)
        ] = parts["bodies"][plan_call.call_id]
    artifact_raw[
        ("g3-stage-render-contexts.830.v1", "stage-contexts.json", _sha(parts["index"]))
    ] = parts["index"]
    if _git_identity() != (head, b""):
        raise ValueError("repository changed during materialization")
    return _materialization_package(
        output_dir,
        command="materialize-d",
        stage=stage,
        review_result_sha=_sha(raws["review-package-result.json"]),
        options_raw=raws["execution-options.json"],
        parent_raw=parent_raw,
        prior=terminal.receipt_sha256,
        plan=plan,
        artifact_raw=artifact_raw,
    )


def _build_parser():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview-c")
    preview.add_argument("--builder-dir", type=Path, required=True)
    preview.add_argument("--execution-options", type=Path, required=True)
    preview.add_argument("--output-dir", type=Path, required=True)
    mc = commands.add_parser("materialize-c")
    mc.add_argument("--review-dir", type=Path, required=True)
    mc.add_argument("--signed-parent", type=Path, required=True)
    mc.add_argument("--output-dir", type=Path, required=True)
    md = commands.add_parser("materialize-d")
    md.add_argument("--stage", choices=("D_COMPILE", "D_REVIEW"), required=True)
    md.add_argument("--signed-parent", type=Path, required=True)
    md.add_argument("--review-dir", type=Path, required=True)
    md.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "preview-c":
            digest = preview_c(args.builder_dir, args.execution_options, args.output_dir)
        elif args.command == "materialize-c":
            digest = materialize_c(args.review_dir, args.signed_parent, args.output_dir)
        else:
            digest = materialize_d(args.stage, args.signed_parent, args.review_dir, args.output_dir)
        print(
            json.dumps(
                {"status": "READY", "output_dir": str(args.output_dir), "result_sha256": digest},
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps({"status": "STOP", "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

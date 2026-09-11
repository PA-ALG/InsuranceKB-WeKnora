from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3NativePageProjectionSetV1,
    G3NativePageProjectionV1,
    _render_g3_stage_contexts,
)
from insurance_harness.run_admission.g3_models import canonical_json

SCRIPT = Path(__file__).with_name("g3_actual_model_plan_materializer_v1.py")


@pytest.fixture(scope="module")
def published_base_oracle():
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        validate_batch_candidate,
    )

    path = SCRIPT.parents[4] / "harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json"
    return validate_batch_candidate(path.read_bytes()).request


def test_d_materialize_uses_current_published_base(
    monkeypatch, tmp_path: Path, published_base_oracle,
) -> None:
    from types import SimpleNamespace

    module = _load_module()
    expected = published_base_oracle
    inputs = expected.resolution_inputs
    options = _options(module)
    parent_raw = canonical_json({})
    digest = hashlib.sha256(parent_raw).hexdigest()
    signed = tmp_path / "sha256" / digest / "model-processing-authorization.json"
    monkeypatch.setattr(module.evaluator, "_ADMISSION_STORE_ROOT", str(tmp_path))
    monkeypatch.setattr(module.evaluator, "_read_g3_parent", lambda *a: parent_raw)
    monkeypatch.setattr(module, "_review_package", lambda *a: (
        options, None, None,
        SimpleNamespace(chain_manifest_hash="b" * 64), None, None, None,
    ))
    monkeypatch.setattr(module, "_verify_parent", lambda *a: None)
    monkeypatch.setattr(module, "_git_identity", lambda: ("a" * 40, ""))
    monkeypatch.setattr(module, "_reject_current_or_later", lambda *a: None)
    monkeypatch.setattr(module, "_prior_stage", lambda *a: (
        None, None, SimpleNamespace(payload=None),
        {"proposal": (inputs.proposals,), "resolution": (expected.resolution,)},
    ))
    artifacts = {
        "batch-corpus.830.g3.v1": inputs.corpus,
        "existing-entities.830.g3.v1": inputs.existing_entities,
        "batch-resolution-policy.830.g3.v1": inputs.policy,
    }
    monkeypatch.setattr(module, "_artifact_from_plan", lambda _, contract: canonical_json(
        artifacts[contract].model_dump(mode="json", round_trip=True)
    ))
    real_builder = module.build_batch_compile_request

    class RequestVerified(Exception):
        pass

    def verify_request(**kwargs):
        rebuilt = real_builder(**kwargs)
        assert rebuilt == expected
        assert kwargs["base_request"] == expected.base_request
        raise RequestVerified

    monkeypatch.setattr(module, "build_batch_compile_request", verify_request)
    with pytest.raises(RequestVerified):
        module.materialize_d("D_COMPILE", signed, tmp_path / "review", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    ("stage", "expected_role", "gemini"),
    (
        ("D_COMPILE", "extract", False),
        ("D_REVIEW", "verify", False),
        ("D_COMPILE", "extract", True),
        ("D_REVIEW", "verify", True),
    ),
)
def test_d_materialize_resolves_stage_identity_before_real_render(
    monkeypatch, tmp_path: Path, stage: str, expected_role: str, gemini: bool,
) -> None:
    from types import SimpleNamespace

    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        validate_batch_candidate,
    )

    module = _load_module()
    candidate = validate_batch_candidate(
        (SCRIPT.parents[4] / "harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json").read_bytes()
    )
    request = candidate.request
    material_ids = tuple(sorted({
        material_id
        for binding in request.entity_bindings
        for material_id in binding.source_material_ids
    }))
    options = (
        (_gemini_review_options(module, material_ids) if stage == "D_REVIEW"
         else _gemini_options(module, material_ids))
        if gemini else _options(module)
    )
    parent_raw = canonical_json({})
    digest = hashlib.sha256(parent_raw).hexdigest()
    signed = tmp_path / "sha256" / digest / "model-processing-authorization.json"
    monkeypatch.setattr(module.evaluator, "_ADMISSION_STORE_ROOT", str(tmp_path))
    monkeypatch.setattr(module.evaluator, "_read_g3_parent", lambda *a: parent_raw)
    monkeypatch.setattr(module, "_review_package", lambda *a: (
        options, None, None, SimpleNamespace(chain_manifest_hash="b" * 64),
        None, None, None,
    ))
    monkeypatch.setattr(module, "_verify_parent", lambda *a: None)
    monkeypatch.setattr(module, "_git_identity", lambda: ("a" * 40, b""))
    monkeypatch.setattr(module, "_reject_current_or_later", lambda *a: None)
    if stage == "D_COMPILE":
        inputs = request.resolution_inputs
        monkeypatch.setattr(module, "_prior_stage", lambda *a: (
            SimpleNamespace(receipt_sha256="c" * 64), b"{}",
            SimpleNamespace(payload=SimpleNamespace(protocol_seed_lock=None)),
            {"proposal": (inputs.proposals,), "resolution": (request.resolution,)},
        ))
        artifacts = {
            "batch-corpus.830.g3.v1": inputs.corpus,
            "existing-entities.830.g3.v1": inputs.existing_entities,
            "batch-resolution-policy.830.g3.v1": inputs.policy,
        }
        monkeypatch.setattr(module, "_artifact_from_plan", lambda _, contract: canonical_json(
            artifacts[contract].model_dump(mode="json", round_trip=True)
        ))
    else:
        monkeypatch.setattr(module, "_prior_stage", lambda *a: (
            SimpleNamespace(receipt_sha256="c" * 64), b"{}",
            SimpleNamespace(payload=SimpleNamespace(protocol_seed_lock=None)),
            {
                "model": (
                    candidate.model_compile_result,
                    canonical_json(candidate.model_compile_result.model_dump(mode="json", round_trip=True)),
                ),
                "final": (
                    candidate.compile_result,
                    canonical_json(candidate.compile_result.model_dump(mode="json", round_trip=True)),
                ),
            },
        ))
        monkeypatch.setattr(
            module,
            "_artifact_from_plan",
            lambda *_: canonical_json(request.model_dump(mode="json", round_trip=True)),
        )

    class RenderReached(Exception):
        pass

    real_render = module.runtime.render_g3_d_prompt_context

    def render(stage_value, identity, request_value, *extra):
        rendered = real_render(stage_value, identity, request_value, *extra)
        assert rendered
        assert identity.role == expected_role
        assert request_value == request
        raise RenderReached

    monkeypatch.setattr(module.runtime, "render_g3_d_prompt_context", render)
    real_window_render = module.runtime.render_gemini_d_compile_window_context

    def render_window(identity, request_value, window):
        rendered = real_window_render(identity, request_value, window)
        assert rendered
        assert identity.role == expected_role
        assert request_value == request
        raise RenderReached

    monkeypatch.setattr(
        module.runtime, "render_gemini_d_compile_window_context", render_window
    )
    if gemini and stage == "D_REVIEW":
        real_review_window = module.runtime.render_gemini_d_review_window_context

        def render_review_window(identity, request_value, output, window):
            assert real_review_window(identity, request_value, output, window)
            assert identity.role == expected_role and request_value == request
            raise RenderReached

        monkeypatch.setattr(
            module.runtime, "render_gemini_d_review_window_context", render_review_window
        )
    with pytest.raises(RenderReached):
        module.materialize_d(stage, signed, tmp_path / "review", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def _d_projection_arguments(module, oracle):
    published, catalog, _, _ = module._frozen_sources()
    return dict(
        published=published, catalog=catalog, corpus=oracle.resolution_inputs.corpus,
        proposals=oracle.resolution_inputs.proposals, resolution=oracle.resolution,
        selected=tuple(sorted(
            (ref.material_id, ref.proposal_ref)
            for binding in oracle.entity_bindings for ref in binding.resolution_refs
        )),
    )


@pytest.mark.parametrize("document,key,value", (
    ("b-source-publication-execution.json", "candidate_hash", "0" * 64),
    ("b-source-publication-execution.json", "release_id", "other"),
    ("b-source-publication-execution.json", "activation_epoch", 4),
    ("b-source-publication-execution.json", "status", "FAIL"),
    ("b-source-publication-execution.json", "authority", "LOCAL_ONLY"),
    ("g2-closeout.json", "acceptance", {"field_pages": 67, "products": 2}),
    ("g2-closeout.json", "artifacts_sha256", {}),
))
def test_d_projection_rejects_semantic_authority_drift(
    monkeypatch, published_base_oracle, document, key, value,
):
    module = _load_module()
    args = _d_projection_arguments(module, published_base_oracle)
    regular = module._regular

    def changed(path, **kwargs):
        raw = regular(path, **kwargs)
        if path.name == document:
            data = json.loads(raw)
            data[key] = value
            return json.dumps(data).encode()
        return raw

    monkeypatch.setattr(module, "_regular", changed)
    with pytest.raises(ValueError, match="D published base authority mismatch"):
        module._d_active_base_request(**args)


def test_d_projection_rejects_raw_authority_drift(monkeypatch, tmp_path, published_base_oracle):
    module = _load_module()
    args = _d_projection_arguments(module, published_base_oracle)
    original = module.G2_PATH.parent / "b-source-publication-execution.json"
    (tmp_path / original.name).write_bytes(original.read_bytes() + b" ")
    monkeypatch.setattr(module, "G2_PATH", tmp_path / module.G2_PATH.name)
    with pytest.raises(ValueError, match="frozen input drift"):
        module._d_active_base_request(**args)


@pytest.mark.parametrize("mutation", (
    "published-missing", "published-conflict", "selected-missing", "selected-conflict",
))
def test_d_projection_rejects_source_drift(published_base_oracle, mutation):
    module = _load_module()
    args = _d_projection_arguments(module, published_base_oracle)
    published = args["published"]
    output = published.compile_result.output
    evidence = next(e for member in (*output.definitions, *output.fields, *output.pages)
                    for e in member.evidence)
    key = (evidence.revision_id, evidence.block_id)
    sources = published.request.sources
    block = next(s for s in sources if (s.revision_id, s.block_id) == key)
    if mutation.startswith("published-"):
        changed = tuple(s for s in sources if (s.revision_id, s.block_id) != key)
        if mutation == "published-conflict":
            changed = (*sources, block.model_copy(update={"text": block.text + " changed"}))
        args["published"] = published.model_copy(update={
            "request": published.request.model_copy(update={"sources": changed}),
        })
    else:
        corpus = args["corpus"]
        selected_id = args["selected"][0][0]
        entries = tuple(e for e in corpus.entries if e.material_id != selected_id)
        if mutation == "selected-conflict":
            entry = next(e for e in corpus.entries if e.material_id == selected_id)
            changed = entry.model_copy(update={
                "blocks": (*entry.blocks, block.model_copy(update={"text": block.text + " changed"})),
            })
            entries = tuple(changed if e.material_id == selected_id else e for e in corpus.entries)
        args["corpus"] = corpus.model_copy(update={"entries": entries})
    with pytest.raises(ValueError, match="source|material"):
        module._d_active_base_request(**args)


def _load_module():
    spec = importlib.util.spec_from_file_location("g3_actual_model_plan_materializer_v1", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def full_fake_builder_artifacts() -> dict[str, bytes]:
    test_path = SCRIPT.with_name("g3_actual_c_input_artifact_builder_v1_test.py")
    spec = importlib.util.spec_from_file_location("g3_builder_fixture_for_materializer", test_path)
    assert spec is not None and spec.loader is not None
    builder_test = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = builder_test
    spec.loader.exec_module(builder_test)
    captured: dict[str, bytes] = {}
    original_load = builder_test.load

    def load_and_capture(name: str = "g3_actual_c_input_artifact_builder_v1"):
        module = original_load(name + "_materializer_capture")
        original_build = module.build

        def build(args):
            artifacts = original_build(args)
            captured.update(artifacts)
            return artifacts

        module.build = build
        return module

    builder_test.load = load_and_capture
    case = builder_test.ActualCInputBuilderTests(
        "test_complete_fake_build_emits_all_seven_validated_artifacts"
    )
    case.test_complete_fake_build_emits_all_seven_validated_artifacts()
    assert set(captured) == {
        "source-acquisition-bundle.json",
        "batch-corpus.json",
        "g3-native-page-projections.json",
        "existing-entities.json",
        "batch-resolution-policy.json",
        "protocol-seed-artifact.json",
        "builder-result.json",
    }
    return _local_fake_builder_artifacts(captured)


def _write_full_fake_builder(
    root: Path, artifacts: dict[str, bytes]
) -> Path:
    builder_dir = root / "builder"
    builder_dir.mkdir(mode=0o700)
    for name, raw in artifacts.items():
        path = builder_dir / name
        path.write_bytes(raw)
        path.chmod(0o600)
    return builder_dir


def _full_fake_review_package(module, root: Path, artifacts: dict[str, bytes]) -> Path:
    builder_dir = _write_full_fake_builder(root, artifacts)
    options = _options(module).model_dump(mode="json", round_trip=True)
    corpus = json.loads(artifacts["batch-corpus.json"])
    options["calls"][0]["material_ids"] = [
        row["material_id"] for row in corpus["entries"]
    ]
    options_path = root / "execution-options.json"
    options_path.write_bytes(canonical_json(options))
    options_path.chmod(0o600)
    module._git_identity = lambda: ("a" * 40, b"")
    module.gateway.G3_LEDGER_ROOT = str(root / "ledger")
    review_dir = root / "review"
    module.preview_c(builder_dir, options_path, review_dir)
    return review_dir


def test_materializer_module_exposes_exact_commands() -> None:
    module = _load_module()
    parser = module._build_parser()
    commands = parser._subparsers._group_actions[0].choices
    assert tuple(commands) == ("preview-c", "materialize-c", "materialize-d")


def test_native_artifact_reader_preserves_non_nfc_only_after_typed_validation() -> None:
    module = _load_module()
    raw_text = "actual-\uf99c-source"
    raw = canonical_json(
        {
            "contract": "g3-native-page-projections.830.v1",
            "pages": [
                {
                    "block_id": "block-1",
                    "block_ref": "opaque-1",
                    "boxes": [],
                    "material_id": "m-001",
                    "page_height": 100.0,
                    "page_number": 1,
                    "page_width": 100.0,
                    "revision_id": "revision-1",
                    "text": raw_text,
                }
            ],
        }
    )

    native = module._native_json(raw, "native fixture")

    assert native.pages[0].text == raw_text
    with pytest.raises(ValueError):
        module._strict_json(raw, "structured fixture")


def test_image_source_is_selected_before_exact_shallow_tool_fallback(tmp_path: Path) -> None:
    module = _load_module()
    image_source = tmp_path / "source"
    image_source.mkdir()
    exact_tool_path = Path("/opt/insurancekb/tools/g3_actual_model_plan_materializer_v1.py")
    assert module._select_worktree(image_source, exact_tool_path) == image_source


def test_builder_accepts_frozen_source_runner_identity_without_source_file(
    tmp_path: Path, full_fake_builder_artifacts: dict[str, bytes]
) -> None:
    module = _load_module()
    builder_dir = _write_full_fake_builder(tmp_path, full_fake_builder_artifacts)
    module.SOURCE_RUNNER_PATH = tmp_path / "source-runner-is-deliberately-absent.py"
    _, result, *_ = module._builder(builder_dir)
    assert result["source_runner_sha256"] == (
        "d10d0a8e4fd4b130131a3326cceaa6e44e9ae6eda789dec798dabe955c46809f"
    )


def test_source_acquisition_binds_corpus_to_native_parser_identity(
    tmp_path: Path, full_fake_builder_artifacts: dict[str, bytes]
) -> None:
    module = _load_module()
    acquisition = json.loads(full_fake_builder_artifacts["source-acquisition-bundle.json"])
    corpus = json.loads(full_fake_builder_artifacts["batch-corpus.json"])
    for facts_row, entry in zip(acquisition["materials"], corpus["entries"], strict=True):
        facts = facts_row["facts"]
        assert facts["revision"]["parser_identity_sha256"] != (
            facts["native"]["parser_identity_sha256"]
        )
        assert entry["parser_identity_sha256"] == facts["native"]["parser_identity_sha256"]
        assert all(
            block["parser_identity"] == entry["parser_identity_sha256"]
            for block in entry["blocks"]
        )
    builder_dir = _write_full_fake_builder(tmp_path, full_fake_builder_artifacts)
    module._builder(builder_dir)


def test_source_acquisition_rejects_native_parser_fact_tamper(
    tmp_path: Path, full_fake_builder_artifacts: dict[str, bytes]
) -> None:
    module = _load_module()
    artifacts = dict(full_fake_builder_artifacts)
    acquisition = json.loads(artifacts["source-acquisition-bundle.json"])
    acquisition["materials"][0]["facts"]["native"]["parser_identity_sha256"] = "0" * 64
    artifacts["source-acquisition-bundle.json"] = canonical_json(acquisition)
    result = json.loads(artifacts["builder-result.json"])
    result["outputs"]["source-acquisition-bundle.json"] = {
        "sha256": hashlib.sha256(artifacts["source-acquisition-bundle.json"]).hexdigest(),
        "bytes": len(artifacts["source-acquisition-bundle.json"]),
    }
    artifacts["builder-result.json"] = canonical_json(result)
    builder_dir = _write_full_fake_builder(tmp_path, artifacts)
    with pytest.raises(ValueError, match="receipt does not match facts"):
        module._builder(builder_dir)


def test_full_fake_builder_preview_preserves_exact_nonruntime_proof(
    tmp_path: Path, full_fake_builder_artifacts: dict[str, bytes]
) -> None:
    module = _load_module()
    review_dir = _full_fake_review_package(module, tmp_path, full_fake_builder_artifacts)
    assert (review_dir / "proof/source-acquisition-bundle.json").read_bytes() == (
        full_fake_builder_artifacts["source-acquisition-bundle.json"]
    )
    assert (review_dir / "proof/builder-result.json").read_bytes() == (
        full_fake_builder_artifacts["builder-result.json"]
    )
    assert all("/proof/" not in row["source"] for row in json.loads(
        (review_dir / "review-package-result.json").read_bytes()
    )["install_manifest"])
    module._review_package(review_dir)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("approved", True),
        ("builder_result_sha256", "0" * 64),
        ("clean_integration_sha", "f" * 40),
    ),
)
def test_review_package_rejects_false_builder_or_approval_evidence(
    tmp_path: Path,
    full_fake_builder_artifacts: dict[str, bytes],
    field: str,
    value: object,
) -> None:
    module = _load_module()
    review_dir = _full_fake_review_package(module, tmp_path, full_fake_builder_artifacts)
    result_path = review_dir / "review-package-result.json"
    result = json.loads(result_path.read_bytes())
    result[field] = value
    result_path.write_bytes(canonical_json(result))
    result_path.chmod(0o600)
    with pytest.raises(ValueError, match="review result"):
        module._review_package(review_dir)


@pytest.mark.parametrize("mutation", ("extra", "source-runner", "output-hash"))
def test_review_package_revalidates_exact_builder_proof(
    tmp_path: Path,
    full_fake_builder_artifacts: dict[str, bytes],
    mutation: str,
) -> None:
    module = _load_module()
    review_dir = _full_fake_review_package(module, tmp_path, full_fake_builder_artifacts)
    proof_path = review_dir / "proof/builder-result.json"
    proof = json.loads(proof_path.read_bytes())
    if mutation == "extra":
        proof["approved"] = True
    elif mutation == "source-runner":
        proof["source_runner_sha256"] = "0" * 64
    else:
        proof["outputs"]["batch-corpus.json"]["sha256"] = "0" * 64
    proof_raw = canonical_json(proof)
    proof_path.write_bytes(proof_raw)
    proof_path.chmod(0o600)
    result_path = review_dir / "review-package-result.json"
    result = json.loads(result_path.read_bytes())
    result["builder_result_sha256"] = hashlib.sha256(proof_raw).hexdigest()
    result_path.write_bytes(canonical_json(result))
    result_path.chmod(0o600)
    with pytest.raises(ValueError, match="builder result|builder output"):
        module._review_package(review_dir)


def test_review_package_rejects_changed_acquisition_proof_and_current_head(
    tmp_path: Path, full_fake_builder_artifacts: dict[str, bytes]
) -> None:
    module = _load_module()
    review_dir = _full_fake_review_package(module, tmp_path, full_fake_builder_artifacts)
    acquisition_path = review_dir / "proof/source-acquisition-bundle.json"
    acquisition = json.loads(acquisition_path.read_bytes())
    acquisition["contract"] = "changed"
    acquisition_path.write_bytes(canonical_json(acquisition))
    acquisition_path.chmod(0o600)
    with pytest.raises(ValueError, match="builder output"):
        module._review_package(review_dir)

    second_root = tmp_path / "head-drift"
    second_root.mkdir()
    review_dir = _full_fake_review_package(module, second_root, full_fake_builder_artifacts)
    module._git_identity = lambda: ("f" * 40, b"")
    with pytest.raises(ValueError, match="clean integration identity"):
        module._review_package(review_dir)


def _builder_artifacts_for_materializer(module, artifacts: dict[str, bytes]) -> dict[str, bytes]:
    current = dict(artifacts)
    result = json.loads(current["builder-result.json"])
    result["source_runner_sha256"] = module.SOURCE_RUNNER_SHA256
    current["builder-result.json"] = canonical_json(result)
    return current


def _rewrite_acquisition_proof(review_dir: Path, mutation: str) -> None:
    acquisition_path = review_dir / "proof/source-acquisition-bundle.json"
    acquisition = json.loads(acquisition_path.read_bytes())
    if mutation == "extra-approved":
        acquisition["approved"] = True
    elif mutation == "scope-tenant":
        acquisition["scope"]["tenant_id"] += 1
    elif mutation == "receipt-hash":
        acquisition["materials"][0]["acquisition_receipt_sha256"] = "0" * 64
    elif mutation == "material-denominator":
        acquisition["materials"] = acquisition["materials"][:-1]
    elif mutation == "facts-native-hash":
        row = acquisition["materials"][0]
        row["facts"]["native"]["native_sha256"] = "f" * 64
        row["acquisition_receipt_sha256"] = hashlib.sha256(
            canonical_json(row["facts"])
        ).hexdigest()
    elif mutation == "facts-extra-key":
        row = acquisition["materials"][0]
        row["facts"]["approved"] = True
        row["acquisition_receipt_sha256"] = hashlib.sha256(
            canonical_json(row["facts"])
        ).hexdigest()
    elif mutation == "context-scope":
        row = acquisition["materials"][0]
        row["facts"]["acquisition_context"]["raw_kb_id"] = "foreign-kb"
        row["acquisition_receipt_sha256"] = hashlib.sha256(
            canonical_json(row["facts"])
        ).hexdigest()
    elif mutation == "registered-receipt":
        row = acquisition["materials"][0]
        row["facts"]["registered_source_receipt"]["knowledge_id"] = "foreign-knowledge"
        row["facts"]["source_http"]["knowledge_id"] = "foreign-knowledge"
        row["acquisition_receipt_sha256"] = hashlib.sha256(
            canonical_json(row["facts"])
        ).hexdigest()
    elif mutation == "selected-set-lock":
        acquisition["selected_file_set"]["file_set_sha256"] = "e" * 64
    else:
        raise AssertionError(mutation)
    acquisition_raw = canonical_json(acquisition)
    acquisition_path.write_bytes(acquisition_raw)
    acquisition_path.chmod(0o600)

    builder_path = review_dir / "proof/builder-result.json"
    builder = json.loads(builder_path.read_bytes())
    builder["outputs"]["source-acquisition-bundle.json"] = {
        "sha256": hashlib.sha256(acquisition_raw).hexdigest(),
        "bytes": len(acquisition_raw),
    }
    builder_raw = canonical_json(builder)
    builder_path.write_bytes(builder_raw)
    builder_path.chmod(0o600)

    result_path = review_dir / "review-package-result.json"
    result = json.loads(result_path.read_bytes())
    result["builder_result_sha256"] = hashlib.sha256(builder_raw).hexdigest()
    result_path.write_bytes(canonical_json(result))
    result_path.chmod(0o600)


@pytest.mark.parametrize(
    "mutation",
    (
        "extra-approved",
        "scope-tenant",
        "receipt-hash",
        "material-denominator",
        "facts-native-hash",
        "facts-extra-key",
        "context-scope",
        "registered-receipt",
        "selected-set-lock",
    ),
)
def test_review_package_rejects_fully_rehashed_acquisition_semantic_tamper(
    tmp_path: Path,
    full_fake_builder_artifacts: dict[str, bytes],
    mutation: str,
) -> None:
    module = _load_module()
    artifacts = _builder_artifacts_for_materializer(module, full_fake_builder_artifacts)
    review_dir = _full_fake_review_package(module, tmp_path, artifacts)
    _rewrite_acquisition_proof(review_dir, mutation)
    with pytest.raises(ValueError, match="source acquisition"):
        module._review_package(review_dir)


def _options(module, *, extra: dict[str, object] | None = None):
    public = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    fingerprint = hashlib.sha256(public).hexdigest()
    identity = {
        "provider": "bailian",
        "deployment_id": "qwen3.5-plus-2026-04-20",
        "family": "qwen",
        "policy_version": "g3-reviewed-v1",
    }
    value = {
        "contract": "g3-actual-model-execution-options.830.v1",
        "authorization_id": "authorization-1",
        "chain_id": "chain-1",
        "clean_integration_sha": "a" * 40,
        "expires_at": "2099-01-01T00:00:00Z",
        "stage_runs": [
            {"stage": stage, "run_id": f"run-{index}", "run_revision": "revision-1"}
            for index, stage in enumerate(("C_CLASSIFY", "D_COMPILE", "D_REVIEW"), 1)
        ],
        "identities": [
            {"stage": stage, "identity": {**identity, "role": role}}
            for stage, role in zip(
                ("C_CLASSIFY", "D_COMPILE", "D_REVIEW"),
                ("classify", "extract", "verify"),
                strict=True,
            )
        ],
        "route": {
            "endpoint_origin": "https://dashscope.aliyuncs.com",
            "endpoint_path": "/compatible-mode/v1/chat/completions",
            "temperature_micros": 0,
            "thinking": False,
            "response_format": "json_object",
            "follow_redirects": False,
            "fallback_limit": 0,
            "retry_limit": 0,
        },
        "calls": [
            {
                "stage": "C_CLASSIFY",
                "call_id": "c-1",
                "ordinal": 0,
                "window_id": "window-1",
                "material_ids": ["material-1"],
                "input_token_ceiling": 200000,
                "output_token_ceiling": 100,
                "timeout_seconds": 30,
            },
            *[
                {
                    "stage": stage,
                    "call_id": call,
                    "ordinal": 0,
                    "window_id": None,
                    "material_ids": [],
                    "input_token_ceiling": 200000,
                    "output_token_ceiling": 100,
                    "timeout_seconds": 30,
                }
                for stage, call in (("D_COMPILE", "dc-1"), ("D_REVIEW", "dr-1"))
            ],
        ],
        "input_estimator": {
            "version": "g3-utf8-body-upper-bound.830.v1",
            "mode": "UTF8_BODY_BYTES_PLUS_FRAMING_TOKENS",
            "framing_token_allowance": 10,
            "proof_sha256s": ["1" * 64],
        },
        "public_model_limits": {
            "context_tokens": 1_000_000,
            "max_input_tokens": 991_808,
            "max_output_tokens": 65_536,
            "source_sha256s": ["2" * 64],
        },
        "expected_parent_approver": {
            "key_id": "approver-1",
            "public_key_b64": __import__("base64").b64encode(public).decode(),
            "public_key_fingerprint": fingerprint,
            "human_identity": "reviewer-1",
            "approver_role": "g3-model-processing-authorization-approver",
            "signature_domain": "insurancekb.run-admission.g3-model-processing-authorization.v1",
        },
        "delegated_stage_signer": {
            "key_id": "stage-1",
            "algorithm": "Ed25519",
            "public_key_b64": __import__("base64").b64encode(public).decode(),
            "public_key_fingerprint": fingerprint,
        },
    }
    if extra:
        value.update(extra)
    return module.ExecutionOptions.model_validate_json(canonical_json(value))


def _legacy_gemini_options(module):
    value = _options(module).model_dump(mode="json", round_trip=True)
    for row in value["identities"]:
        row["identity"].update(
            provider="g3-user-gateway",
            deployment_id="gemini-3.7-flash-medium",
            family="gemini",
            policy_version="g3-user-gemini-gateway-v1",
        )
    value["route"].update(
        endpoint_origin="http://8.148.158.241:3131",
        endpoint_path="/v1/chat/completions",
        thinking=True,
    )
    return module.ExecutionOptions.model_validate_json(canonical_json(value))


def _gemini_options(module, required_material_ids: tuple[str, ...] = ("material-1",)):
    value = _legacy_gemini_options(module).model_dump(mode="json", round_trip=True)
    c_template = next(row for row in value["calls"] if row["stage"] == "C_CLASSIFY")
    d_template = next(row for row in value["calls"] if row["stage"] == "D_COMPILE")
    d_template["input_token_ceiling"] = 900000
    review = next(row for row in value["calls"] if row["stage"] == "D_REVIEW")
    required_material_ids = tuple(sorted(set(required_material_ids)))
    fillers = tuple(
        f"zz-capacity-material-{index:02d}"
        for index in range(15 - len(required_material_ids))
    )
    material_ids = tuple(sorted((*required_material_ids, *fillers)))
    c_rows = [
        {
            **c_template,
            "call_id": f"c-{index:03d}",
            "ordinal": index,
            "window_id": f"c-window-{index:03d}",
            "material_ids": [material_id],
        }
        for index, material_id in enumerate(material_ids)
    ]
    capacity = [
        {
            **d_template,
            "call_id": spec["call_id"],
            "ordinal": spec["ordinal"],
            "window_id": spec["window_id"],
            "material_ids": [spec["material_id"]],
        }
        for spec in module._gemini_d_capacity_slot_rows(material_ids)
    ]
    value["calls"] = c_rows + capacity + [review]
    return module.ExecutionOptions.model_validate_json(canonical_json(value))


def _gemini_review_options(module, required_material_ids=("material-1",)):
    value = _gemini_options(module, required_material_ids).model_dump(mode="json")
    review = next(row for row in value["calls"] if row["stage"] == "D_REVIEW")
    review["input_token_ceiling"] = 900000
    material_ids = tuple(sorted(
        mid for row in value["calls"] if row["stage"] == "C_CLASSIFY"
        for mid in row["material_ids"]
    ))
    value["calls"] = [row for row in value["calls"] if row["stage"] != "D_REVIEW"] + [
        {**review, "call_id": slot["call_id"], "ordinal": slot["ordinal"],
         "window_id": slot["window_id"], "material_ids": [slot["material_id"]]}
        for slot in module._gemini_d_review_capacity_slot_rows(material_ids)
    ]
    return module.ExecutionOptions.model_validate_json(canonical_json(value))


def test_cfg38_capacity_accounts_for_two_entities_and_product_reviews():
    module = _load_module()
    mids = tuple(f"material-{index:02d}" for index in range(15))
    compile_slots = module._gemini_d_capacity_slot_rows(mids)
    assert len(compile_slots) == 300
    review_slots = module._gemini_d_review_capacity_slot_rows(mids)
    assert len(review_slots) == 30
    assert {(row["material_id"], row["entity_slot"]) for row in review_slots} == {
        (mid, slot) for mid in mids for slot in range(2)
    }
    options = _gemini_review_options(module, mids)
    assert module._chain(options).max_calls == 345
    changed = options.model_dump(mode="json")
    row = next(row for row in changed["calls"] if row["stage"] == "D_REVIEW")
    row["window_id"] = "window_" + "f" * 64
    with pytest.raises(ValueError, match="capacity grid"):
        module.ExecutionOptions.model_validate_json(canonical_json(changed))


@pytest.mark.parametrize("stage", ("D_COMPILE", "D_REVIEW"))
def test_cfg38_active_mapping_preserves_entity_slots_and_merged_materials(monkeypatch, stage):
    module = _load_module()
    options = _gemini_review_options(module, ("material-1", "material-2"))
    windows = tuple({
        "primary_material_id": "material-1", "material_ids": ("material-1", "material-2"),
        "entity_slot": slot, "entity_id": f"entity-{slot}",
        "kind": "ENTITY_SYNTHESIS" if stage == "D_COMPILE" else "ENTITY_REVIEW",
        "window_id": "window_" + str(slot + 1) * 64,
    } for slot in range(2))
    name = "derive_gemini_d_compile_windows" if stage == "D_COMPILE" else "derive_gemini_d_review_windows"
    monkeypatch.setattr(module.runtime, name, lambda *args: windows, raising=False)
    active = (module._active_gemini_d_compile_options(options, None)
              if stage == "D_COMPILE" else module._active_gemini_d_review_options(options, None, None))
    assert len(active) == 2
    assert len({row.call_id for row in active}) == 2
    assert tuple(row.ordinal for row in active) == (0, 1)
    assert all(row.material_ids == ("material-1", "material-2") for row in active)
    assert tuple(row.window_id for row in active) == tuple(row["window_id"] for row in windows)
    assert all(row.call_id in {c.call_id for c in options.calls if c.stage == stage} for row in active)


@pytest.mark.parametrize("change", (
    {"entity_slot": 2}, {"material_ids": ("material-2", "material-1")},
    {"material_ids": ("material-1", "unapproved")},
    {"primary_material_id": "material-2"}, {"kind": "FIELDS"},
))
def test_cfg38_active_review_rejects_foreign_capacity_or_material_binding(monkeypatch, change):
    module = _load_module()
    options = _gemini_review_options(module, ("material-1", "material-2"))
    window = {"primary_material_id": "material-1", "material_ids": ("material-1", "material-2"),
              "entity_slot": 0, "kind": "ENTITY_REVIEW", "window_id": "window_" + "1" * 64}
    monkeypatch.setattr(module.runtime, "derive_gemini_d_review_windows",
                        lambda *args: ({**window, **change},), raising=False)
    with pytest.raises(ValueError, match="Gemini D"):
        module._active_gemini_d_review_options(options, None, None)


def test_cfg38_review_materialization_and_reopen_preserve_exact_active_partition():
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import validate_batch_candidate

    module = _load_module()
    candidate = validate_batch_candidate((SCRIPT.parents[4] /
        "harness/tests/fixtures/batch_concept_compile_830_g3/candidate.json").read_bytes())
    request, output = candidate.request, candidate.compile_result.output
    mids = tuple(sorted({mid for binding in request.entity_bindings for mid in binding.source_material_ids}))
    options = _gemini_review_options(module, mids)
    identity = next(row.identity for row in options.identities if row.stage == "D_REVIEW")
    active = module._active_gemini_d_review_options(options, request, output)
    windows = module.runtime.derive_gemini_d_review_windows(request, output)
    assert len(active) == len(request.entity_bindings)
    assert len(active) < 30
    contexts = {call.call_id: module.batch_json_bytes_830_g3(
        module.runtime.render_gemini_d_review_window_context(identity, request, output, window))
        for call, window in zip(active, windows, strict=True)}
    typed = [
        ("batch-concept-compile-request.830.g3.v1", "batch-concept-compile-request.json", canonical_json(request.model_dump(mode="json"))),
        ("g3-d-final-compile-result.830.v1", "final-compile-result.json", module.batch_json_bytes_830_g3(candidate.compile_result)),
        ("g3-d-model-compile-result.830.v1", "model-compile-result.json", module.batch_json_bytes_830_g3(candidate.model_compile_result)),
    ]
    parts = module._stage_fixed(options, "D_REVIEW", module._chain(options),
                                context_raws=contexts, typed=typed, configured=active)
    artifact_raw = {(contract, filename, module._sha(raw)): raw for contract, filename, raw in typed}
    for call in parts["calls"]:
        artifact_raw[("g3-rendered-call-context.830.v1", "call-context.json", call.input_context_sha256)] = contexts[call.call_id]
        artifact_raw[("g3-http-request-body.830.v1", "request-body.json", call.request_body_sha256)] = parts["bodies"][call.call_id]
    artifact_raw[("g3-stage-render-contexts.830.v1", "stage-contexts.json", module._sha(parts["index"]))] = parts["index"]
    reopened = module._parts_from_artifacts(options, None, "D_REVIEW", parts["manifest"], artifact_raw)
    assert reopened["calls"] == parts["calls"]
    assert reopened["caps"] == parts["caps"]
    assert reopened["bodies"] == parts["bodies"]
    assert parts["caps"].call_limit == len(active)
    assert parts["caps"].time_limit_seconds == sum(row.timeout_seconds for row in active)
    bad = module._hashed(
        module.G3RequestManifestV1, "g3-request-manifest.830.v1", "manifest_hash",
        **{**parts["manifest"].model_dump(mode="python", exclude={"manifest_hash"}),
           "calls": parts["calls"][:-1]},
    )
    with pytest.raises(ValueError, match="call projection mismatch"):
        module._parts_from_artifacts(options, None, "D_REVIEW", bad, artifact_raw)


@pytest.mark.parametrize("stage", ("D_COMPILE", "D_REVIEW"))
def test_cfg38_plan_binds_all_active_material_rights(stage):
    import tests.test_run_admission_g3_bounded_830 as admission_fixture

    module = _load_module()
    options = _gemini_review_options(module, ("material-1", "material-2"))
    capacity = tuple(row for row in options.calls if row.stage == stage)
    active = (capacity[0].model_copy(update={"material_ids": ("material-1", "material-2")}),)
    contexts = {active[0].call_id: canonical_json({"test_unit": "merged-product"})}
    chain = module._chain(options)
    parts = module._stage_fixed(options, stage, chain, context_raws=contexts, typed=[], configured=active)
    materials = tuple(module.G3AuthorizedMaterialV1(
        material_id=mid, corpus_entry_sha256="1" * 64, source_revision_receipt_sha256="2" * 64,
        w1_sha256="3" * 64, native_page_map_sha256="4" * 64,
    ) for mid in ("material-1", "material-2"))
    seed = admission_fixture.valid_c_plan().protocol_seed_lock
    parent = module._parent(options, chain, "space-1", materials, "5" * 64, "6" * 64)
    plan = module._plan(options, chain, parent, "7" * 64, seed, stage, parts, prior="8" * 64)
    assert plan.rights_lock.material_or_derivation_ids == ("material-1", "material-2")
    assert plan.eligibility_lock.eligible_subject_ids == ("material-1", "material-2")
    assert plan.stage_caps.call_limit == 1


def test_options_and_chain_are_closed_and_stage_exact() -> None:
    module = _load_module()
    options = _options(module)
    chain = module._chain(options)
    assert chain.chain_id == "chain-1"
    assert tuple(row.stage for row in chain.stages) == (
        "C_CLASSIFY",
        "D_COMPILE",
        "D_REVIEW",
    )
    assert chain.max_calls == 3
    with pytest.raises(ValueError):
        _options(module, extra={"unknown": True})


def test_options_accept_only_exact_gemini_identity_route_projection() -> None:
    module = _load_module()
    options = _gemini_options(module)
    value = options.model_dump(mode="json", round_trip=True)
    assert options.route.endpoint_path == "/v1/chat/completions"
    for field, replacement in (
        ("endpoint_origin", "https://dashscope.aliyuncs.com"),
        ("endpoint_path", "/compatible-mode/v1/chat/completions"),
        ("thinking", False),
    ):
        crossed = json.loads(canonical_json(value))
        crossed["route"][field] = replacement
        with pytest.raises(ValueError):
            module.ExecutionOptions.model_validate_json(canonical_json(crossed))


def test_gemini_d_materializer_uses_reference_templates_and_runtime_context() -> None:
    module = _load_module()
    options = _gemini_options(module)
    for stage in ("D_COMPILE", "D_REVIEW"):
        identity = next(row.identity for row in options.identities if row.stage == stage)
        lock, raw = module._template(stage, identity)
        assert lock.path.endswith("_references_v1.txt")
        assert b"semantic" in raw
        assert module._schema(stage, identity).artifacts[1].enforcing_module.endswith(
            "g3_bounded_model_execution.py"
        )


def test_gemini_d_capacity_grid_selects_only_exact_active_windows(
    published_base_oracle,
) -> None:
    module = _load_module()
    request = published_base_oracle
    material_ids = tuple(sorted({
        material_id
        for binding in request.entity_bindings
        for material_id in binding.source_material_ids
    }))
    options = _gemini_options(module, material_ids)
    capacity = tuple(row for row in options.calls if row.stage == "D_COMPILE")
    active = module._active_gemini_d_compile_options(options, request)
    windows = module.runtime.derive_gemini_d_compile_windows(request)

    assert len(capacity) == 300
    assert len(active) == len(windows)
    assert tuple(row.ordinal for row in active) == tuple(range(len(active)))
    assert tuple((row.window_id, row.material_ids) for row in active) == tuple(
        (window["window_id"], tuple(window["material_ids"])) for window in windows
    )
    assert {row.call_id for row in active} <= {row.call_id for row in capacity}
    assert module._chain(options).stages[1].max_calls == 300

    changed = options.model_dump(mode="json", round_trip=True)
    d_row = next(row for row in changed["calls"] if row["stage"] == "D_COMPILE")
    d_row["window_id"] = "window_" + "f" * 64
    with pytest.raises(ValueError, match="capacity grid"):
        module.ExecutionOptions.model_validate_json(canonical_json(changed))


def test_gemini_d_active_windows_render_as_exact_stage_calls(
    published_base_oracle,
) -> None:
    module = _load_module()
    request = published_base_oracle
    material_ids = tuple(sorted({
        material_id
        for binding in request.entity_bindings
        for material_id in binding.source_material_ids
    }))
    options = _gemini_options(module, material_ids)
    identity = next(
        row.identity for row in options.identities if row.stage == "D_COMPILE"
    )
    active = module._active_gemini_d_compile_options(options, request)
    windows = module.runtime.derive_gemini_d_compile_windows(request)
    contexts = {
        call.call_id: module.batch_json_bytes_830_g3(
            module.runtime.render_gemini_d_compile_window_context(
                identity, request, window
            )
        )
        for call, window in zip(active, windows, strict=True)
    }
    request_raw = canonical_json(request.model_dump(mode="json", round_trip=True))
    parts = module._stage_fixed(
        options,
        "D_COMPILE",
        module._chain(options),
        context_raws=contexts,
        typed=[(
            "batch-concept-compile-request.830.g3.v1",
            "batch-concept-compile-request.json",
            request_raw,
        )],
        configured=active,
    )
    assert tuple(
        (call.call_id, call.ordinal, call.window_id, call.material_ids)
        for call in parts["calls"]
    ) == tuple(
        (call.call_id, call.ordinal, call.window_id, call.material_ids)
        for call in active
    )
    assert len(parts["calls"]) == len(windows)
    assert len(parts["calls"]) < module._chain(options).stages[1].max_calls


def test_options_file_accepts_canonical_json_and_rejects_whitespace(
    tmp_path: Path,
) -> None:
    module = _load_module()
    options = _options(module)
    raw = canonical_json(options.model_dump(mode="json", round_trip=True))
    path = tmp_path / "options.json"
    path.write_bytes(raw)
    parsed, copied = module._options(path)
    assert parsed == options
    assert copied == raw
    path.write_bytes(raw + b"\n")
    with pytest.raises(ValueError, match="noncanonical"):
        module._options(path)


def test_frozen_indented_sources_are_semantically_read_without_rewrite() -> None:
    module = _load_module()
    g2, catalog, catalog_raw, profile_raw = module._frozen_sources()
    assert g2.contract == "concept-candidate-bundle.830.g2.v1"
    assert len(catalog.entries) == 11
    assert hashlib.sha256(catalog_raw).hexdigest() == module.FROZEN[module.CATALOG_PATH]
    assert hashlib.sha256(profile_raw).hexdigest() == module.FROZEN[module.PROFILE_PATH]


def test_atomic_package_has_private_files_and_never_overwrites(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "package"
    module._atomic_package(output, {"nested/value.json": b"{}"})
    assert (output / "nested/value.json").read_bytes() == b"{}"
    assert os.stat(output / "nested/value.json").st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="exists"):
        module._atomic_package(output, {"nested/value.json": b"different"})


def test_import_rows_are_fixed_content_addressed_and_tamper_evident() -> None:
    module = _load_module()
    raw = b"{}"
    digest = hashlib.sha256(raw).hexdigest()
    rows = module._install_rows({("contract.v1", "value.json", digest): raw})
    assert rows == [
        {
            "contract": "contract.v1",
            "source": f"install/sha256/{digest}/value.json",
            "destination": f"/var/lib/insurancekb/run-admission/sha256/{digest}/value.json",
            "sha256": digest,
            "bytes": 2,
        }
    ]
    with pytest.raises(ValueError, match="hash"):
        module._install_rows({("contract.v1", "value.json", "0" * 64): raw})


def test_d_state_gate_allows_only_predecessor_and_rejects_current(tmp_path: Path) -> None:
    module = _load_module()
    module.gateway.G3_LEDGER_ROOT = str(tmp_path)
    module._reject_current_or_later("a" * 64, "D_COMPILE")
    current = tmp_path / "chains" / ("a" * 64) / "stage-results" / "D_COMPILE"
    current.mkdir(parents=True)
    with pytest.raises(ValueError, match="current or later"):
        module._reject_current_or_later("a" * 64, "D_COMPILE")


@pytest.mark.parametrize("gemini", [False, True])
def test_c_plan_uses_current_typed_renderer_and_passes_production_validators(gemini: bool) -> None:
    module = _load_module()
    fixture_path = SCRIPT.parents[4] / "harness/tests/test_batch_entity_resolution_830_g3.py"
    fixture_spec = importlib.util.spec_from_file_location("g3_materializer_fixture", fixture_path)
    assert fixture_spec is not None and fixture_spec.loader is not None
    fixture = importlib.util.module_from_spec(fixture_spec)
    sys.modules[fixture_spec.name] = fixture
    fixture_spec.loader.exec_module(fixture)
    options = _options(module)
    if gemini:
        options = _legacy_gemini_options(module)
    entry = fixture._entry(material_id="material-1", text="fixed source witness")
    corpus = fixture._corpus(entry)
    existing = fixture._existing()
    policy = fixture._policy()
    page = G3NativePageProjectionV1(
        block_ref="opaque-1",
        material_id=entry.material_id,
        revision_id=entry.blocks[0].revision_id,
        block_id=entry.blocks[0].block_id,
        page_number=entry.blocks[0].page_number,
        page_width=100.0,
        page_height=100.0,
        text=entry.blocks[0].text,
        boxes=(),
    )
    native = G3NativePageProjectionSetV1(
        contract="g3-native-page-projections.830.v1", pages=(page,)
    )
    _, catalog, _, _ = module._frozen_sources()
    configured = next(
        row
        for row in options.calls
        if row.stage == "C_CLASSIFY" and "material-1" in row.material_ids
    )
    call_view = type(
        "CallView",
        (),
        {
            "call_id": configured.call_id,
            "window_id": configured.window_id,
            "material_ids": configured.material_ids,
        },
    )()
    contexts = module._c_contexts(
        corpus, native, existing, policy, catalog, (call_view,), options.identities[0].identity,
    )
    typed = [
        (
            "batch-corpus.830.g3.v1",
            "batch-corpus.json",
            canonical_json(corpus.model_dump(mode="json")),
        ),
        (
            "batch-resolution-policy.830.g3.v1",
            "batch-resolution-policy.json",
            canonical_json(policy.model_dump(mode="json")),
        ),
        (
            "schema-pack-catalog.830.g3.v1",
            "catalog.json",
            canonical_json(catalog.model_dump(mode="json")),
        ),
        (
            "existing-entities.830.g3.v1",
            "existing-entities.json",
            canonical_json(existing.model_dump(mode="json")),
        ),
        (
            "g3-native-page-projections.830.v1",
            "g3-native-page-projections.json",
            canonical_json(native.model_dump(mode="json")),
        ),
    ]
    chain = module._chain(options)
    parts = module._stage_fixed(options, "C_CLASSIFY", chain, context_raws=contexts, typed=typed)
    materials = module._authorized_materials(corpus, native)
    parent = module._parent(
        options,
        chain,
        corpus.space_id,
        materials,
        parts["manifest"].manifest_hash,
        hashlib.sha256(parts["preview"]).hexdigest(),
    )
    seed_raw = canonical_json(
        {
            "contract": "g3-protocol-seed-artifact.830.v1",
            "material_expectations": [],
            "expected_coverage_codes": ["disposition:MATCH"],
            "quality_authority": False,
        }
    )
    seed = module._hashed(
        module.G3ProtocolSeedLockV1,
        "g3-protocol-seed.830.v1",
        "golden_slice_hash",
        contract="g3-protocol-seed-lock.830.v1",
        seed_artifact=module._ref(
            "g3-protocol-seed-artifact.830.v1",
            seed_raw,
            "protocol-seed-artifact.json",
        ),
        denominator_material_ids=("material-1",),
        expected_coverage_codes=("disposition:MATCH",),
        quality_authority=False,
    )
    plan = module._plan(options, chain, parent, "1" * 64, seed, "C_CLASSIFY", parts)
    artifacts = {}
    for contract, _, raw in typed:
        artifacts.setdefault(contract, []).append(raw)
    rebuilt, index, preview = _render_g3_stage_contexts(
        plan=plan,
        parent=parent,
        artifacts=artifacts,
        template_bytes=parts["template_raw"],
    )
    assert rebuilt == contexts
    assert index == parts["index"]
    assert preview == parts["preview"]


def _local_fake_builder_artifacts(artifacts: dict[str, bytes]) -> dict[str, bytes]:
    """Convert synthetic witnesses to the current local SOURCE contract for unit tests."""
    from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as entity
    from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3

    current = dict(artifacts)
    acquisition = json.loads(current["source-acquisition-bundle.json"])
    corpus = entity.BatchCorpusV1.model_validate_json(current["batch-corpus.json"])
    entries = []
    renamed = {}
    for row, entry in zip(acquisition["materials"], corpus.entries, strict=True):
        for artifact in row["facts"]["source_http"]["artifacts"]:
            label = artifact["label"]
            if "chunks-" in label:
                suffix = ("after-" + label if label.startswith("old-") else "current-" + label)
                name = "local-completion--" + suffix + ".json"
                renamed[artifact["artifact"]] = name
                artifact["label"] = "local-completion:" + suffix
                artifact["artifact"] = name
        row["facts"]["source_http"]["artifacts"].sort(key=lambda item: item["label"])
        row["acquisition_receipt_sha256"] = hashlib.sha256(canonical_json(row["facts"])).hexdigest()
        provenance_payload = entity._payload(entry.provenance, "declaration_sha256")
        provenance_payload["acquisition_receipt_sha256"] = row["acquisition_receipt_sha256"]
        provenance = entity._hashed(entity.SourceProvenanceV1,
            object_type="source-provenance.830.g3.v1", hash_field="declaration_sha256",
            payload=provenance_payload)
        entry_payload = entity._payload(entry, "entry_sha256")
        entry_payload["provenance"] = provenance
        entries.append(entity._hashed(entity.CorpusEntryV1,
            object_type="corpus-entry.830.g3.v1", hash_field="entry_sha256", payload=entry_payload))
    for artifact in acquisition["source_artifact_manifest"]:
        artifact["artifact"] = renamed.get(artifact["artifact"], artifact["artifact"])
    # The legacy fake builder deliberately omitted its global HTTP manifest.
    acquisition["source_artifact_manifest"] = sorted([
        {"artifact": artifact["artifact"], "sha256": artifact["response_sha256"], "size": artifact["size"]}
        for row in acquisition["materials"] for artifact in row["facts"]["source_http"]["artifacts"]
    ], key=lambda row: row["artifact"])
    payload = entity._payload(corpus, "corpus_sha256")
    payload["entries"] = tuple(entries)
    rebuilt = entity._hashed(entity.BatchCorpusV1, object_type=corpus.contract,
        hash_field="corpus_sha256", payload=payload)
    current["batch-corpus.json"] = batch_json_bytes_830_g3(rebuilt)
    current["source-acquisition-bundle.json"] = canonical_json(acquisition)
    result = json.loads(current["builder-result.json"])
    result["design_sha256"] = "93d43e9638b008ebfb38fcbda8fc4a0e9568b068905612328c395bd9ec92482f"
    result["source_runner_sha256"] = "d10d0a8e4fd4b130131a3326cceaa6e44e9ae6eda789dec798dabe955c46809f"
    for name, output in result["outputs"].items():
        output.update(sha256=hashlib.sha256(current[name]).hexdigest(), bytes=len(current[name]))
    current["builder-result.json"] = canonical_json(result)
    return current


def _pagination_rows(material_id: str, pages: int):
    family = "after-old" if material_id in ("g3-material-01", "g3-material-02", "g3-material-03", "g3-material-04") else "current"
    return [{"label": f"local-completion:{family}-chunks-{material_id}-{page}",
             "artifact": f"local-completion--{family}-chunks-{material_id}-{page}.json",
             "response_sha256": hashlib.sha256(str(page).encode()).hexdigest(), "size": 10}
            for page in range(1, pages + 1)]


@pytest.mark.parametrize(("material_id", "count", "pages"), (
    ("g3-material-01", 162, 2), ("g3-material-01", 100, 1),
    ("g3-material-07", 101, 2), ("g3-material-21", 2, 1),
    ("g3-material-01", 1001, 11),
))
def test_source_page_receipts_bind_http_pages_not_w1_rows(material_id, count, pages):
    module = _load_module()
    rows = _pagination_rows(material_id, pages)
    module._validate_chunk_page_receipts(material_id, count,
        sorted(rows, key=lambda row: row["label"]), [row["response_sha256"] for row in rows])


@pytest.mark.parametrize("mutation", (
    "missing", "swapped", "padded", "wrong-hash", "wrong-origin", "wrong-basename",
    "duplicate-ordinal", "skipped-ordinal", "extra-page", "unqualified", "foreign-material",
))
def test_source_page_receipts_reject_inconsistent_pagination(mutation):
    module = _load_module()
    rows = _pagination_rows("g3-material-01", 2)
    hashes = [row["response_sha256"] for row in rows]
    if mutation == "missing":
        rows.pop()
        hashes.pop()
    elif mutation == "swapped":
        hashes.reverse()
    elif mutation == "padded":
        hashes = [hashes[0]] * 162
    elif mutation == "wrong-hash":
        hashes[0] = "f" * 64
    elif mutation == "wrong-origin":
        rows[0]["label"] = rows[0]["label"].replace("local-completion:", "processing-parent:")
    elif mutation == "wrong-basename":
        rows[0]["artifact"] = "foreign.json"
    elif mutation == "duplicate-ordinal":
        rows[1] = dict(rows[0])
    elif mutation == "skipped-ordinal":
        rows[1]["label"] = rows[1]["label"].removesuffix("2") + "3"
    elif mutation == "extra-page":
        rows = _pagination_rows("g3-material-01", 3)
        hashes = [row["response_sha256"] for row in rows]
    elif mutation == "unqualified":
        rows[0]["label"] = rows[0]["label"].removeprefix("local-completion:")
    else:
        rows[0]["label"] = rows[0]["label"].replace("material-01", "material-02")
    with pytest.raises(ValueError, match="pagination"):
        module._validate_chunk_page_receipts("g3-material-01", 162, rows, hashes)


@pytest.mark.parametrize("mutation", ("missing", "hash", "size"))
def test_source_http_artifacts_require_exact_global_manifest(full_fake_builder_artifacts, mutation):
    module = _load_module()
    artifacts = full_fake_builder_artifacts
    acquisition = json.loads(artifacts["source-acquisition-bundle.json"])
    row = acquisition["source_artifact_manifest"][0]
    if mutation == "missing":
        acquisition["source_artifact_manifest"].pop(0)
    elif mutation == "hash":
        row["sha256"] = "0" * 64
    else:
        row["size"] += 1
    corpus = module._corpus_json(artifacts["batch-corpus.json"], "fixture")
    native = module._native_json(artifacts["g3-native-page-projections.json"], "fixture")
    with pytest.raises(ValueError, match="HTTP artifact manifest mismatch"):
        module._validate_source_acquisition(acquisition, corpus, native)


def test_cfg39_ninth_field_batch_has_distinct_reserved_capacity():
    module = _load_module()
    options = _gemini_review_options(module, ("material-1",))
    windows = tuple({
        "primary_material_id": "material-1", "material_ids": ("material-1",),
        "entity_slot": 1, "entity_id": "entity-second",
        "kind": "ENTITY_SYNTHESIS" if index == 0 else "FIELDS",
        "window_id": "window_" + f"{index + 1:064x}",
    } for index in range(10))
    active = module._active_gemini_d_options(options, "D_COMPILE", windows)
    assert len(active) == 10
    assert len({row.call_id for row in active}) == 10
    assert tuple(row.ordinal for row in active) == tuple(range(10))
    assert tuple(row.window_id for row in active) == tuple(row["window_id"] for row in windows)


@pytest.mark.parametrize("boundary", ["builder", "review"])
def test_native_and_corpus_decode_once_per_validation_boundary(
    tmp_path: Path, full_fake_builder_artifacts: dict[str, bytes], monkeypatch,
    boundary: str,
) -> None:
    module = _load_module()
    if boundary == "builder":
        directory = _write_full_fake_builder(tmp_path, full_fake_builder_artifacts)
    else:
        directory = _full_fake_review_package(module, tmp_path, full_fake_builder_artifacts)
    counts = {"native": 0, "corpus": 0}
    for label, function_name in (("native", "_native_json"), ("corpus", "_corpus_json")):
        original = getattr(module, function_name)
        def counted(*args, _label=label, _original=original, **kwargs):
            counts[_label] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, function_name, counted)
    if boundary == "builder":
        module._builder(directory)
    else:
        module._review_package(directory)
    assert counts == {"native": 1, "corpus": 1}


def test_product_d_inputs_avoid_classification_preview(monkeypatch, published_base_oracle):
    module = _load_module()
    assert hasattr(module, 'materialize_product_d_inputs'), 'no direct product D materializer'
    from types import SimpleNamespace
    from insurance_harness.model_policy import ModelIdentity
    identity = ModelIdentity(provider='g3-user-gateway', family='gemini', deployment_id='gemini-3.7-flash-medium', role='extract', policy_version='g3-user-gemini-gateway-v1')
    options = SimpleNamespace(identities=(SimpleNamespace(stage='D_COMPILE', identity=identity),), calls=())
    captured = {}
    def fixed(*args, **kwargs):
        captured.update(kwargs)
        return {'artifacts': (), 'calls': ()}
    monkeypatch.setattr(module, '_stage_fixed', fixed)
    monkeypatch.setattr(module, '_plan', lambda *args, **kwargs: 'plan')
    monkeypatch.setattr(module, '_review_package', lambda *args: pytest.fail('old review package path'))
    monkeypatch.setattr(module, '_derive_c', lambda *args: pytest.fail('classification rerender'))
    windows = module.runtime.derive_gemini_d_compile_windows(published_base_oracle)
    configured = tuple(SimpleNamespace(call_id=f'call-{i}', stage='D_COMPILE', ordinal=i, window_id=w['window_id'], material_ids=w['material_ids']) for i,w in enumerate(windows))
    result = module.materialize_product_d_inputs(options=options, chain=None, parent=None, parent_digest='1'*64, protocol_seed=None, request=published_base_oracle, configured=configured, prior_terminal_sha='2'*64)
    assert result['plan'] == 'plan'
    assert len(captured['context_raws']) == len(windows)
    assert [row[0] for row in captured['typed']] == ['batch-concept-compile-request.830.g3.v1']
    assert all('g3-native-page-projections' not in c for c,_,_ in captured['typed'])


def test_v2_options_validate_actual_product_windows_without_capacity_grid():
    module = _load_module()
    wire = _legacy_gemini_options(module).model_dump(mode='json')
    wire['contract'] = 'g3-product-model-execution-options.830.v2'
    compiled = next(row for row in wire['calls'] if row['stage'] == 'D_COMPILE')
    compiled.update(window_id='window-product-a', material_ids=['material-1'])
    wire['calls'].append({**compiled, 'call_id': 'product-second', 'ordinal': 1, 'window_id': 'window-product-b'})
    value = module.ExecutionOptions.model_validate_json(canonical_json(wire))
    assert len([row for row in value.calls if row.stage == 'D_COMPILE']) == 2
    wire['calls'][-1]['ordinal'] = 0
    with pytest.raises(ValueError, match='product'):
        module.ExecutionOptions.model_validate_json(canonical_json(wire))

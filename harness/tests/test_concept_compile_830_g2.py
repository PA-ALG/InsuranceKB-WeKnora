from __future__ import annotations

import importlib
import importlib.util
import json

import pytest


def api():
    name = "insurance_harness.knowledge_compiler.concept_compile_830_g2"
    assert importlib.util.find_spec(name) is not None, "G2-R1: no independent compile/review bundle"
    return importlib.import_module(name)


def request(g):
    return g.CompileRequest(
        request_id="req-a",
        tenant_id=1,
        raw_kb_id="raw-a",
        wiki_kb_id="wiki-a",
        schema_identity="fixture-schema",
        profile_identity="fixture-profile",
        entity_versions={"entity-a": "v1"},
        space_id="space-a",
        policy_identity="g2-initial-80-60.v1",
        sources=(
            g.SourceBlock(
                tenant_id=1,
                space_id="space-a",
                raw_kb_id="raw-a",
                knowledge_id="knowledge-a",
                parse_attempt=1,
                revision_id="r1",
                source_hash="a" * 64,
                parse_hash="b" * 64,
                parser_identity="native-v1",
                block_id="p1",
                page_number=1,
                text="被保险人就是受保险合同保障的人。",
                source_type="DOCUMENT",
            ),
        ),
        required_fields={"entity-a": ("eligibility", "unobserved")},
    )


def compiler(g):
    return g.ExtractCompiler(
        definitions=(
            g.DefinitionRule(
                canonical_key="insured",
                sense_key="insurance",
                title="被保险人",
                revision_id="r1",
                block_id="p1",
                start=0,
                end=len("被保险人就是受保险合同保障的人。"),
            ),
        ),
        fields=(
            g.FieldRule(
                entity_id="entity-a",
                field_key="eligibility",
                revision_id="r1",
                block_id="p1",
                start=0,
                end=len("被保险人就是受保险合同保障的人。"),
                concept_key="insured",
            ),
        ),
    )


def test_separate_compiler_reviewer_records_and_manifest_are_replayable():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    checked = fixture_reviewer(g, out.output).review(req, out.output, run_id="review-a")
    bundle = g.assemble_bundle(req, out, checked)
    assert out.execution.context_hash != checked.execution.context_hash
    assert out.execution.run_id != checked.execution.run_id
    assert len(bundle.page_manifest.members) == 5  # definition, 2 fields, overview, free_wiki
    assert any("受保险合同保障" in x.content for x in bundle.page_manifest.members)
    assert bundle.fields[1].state == "unknown"
    assert bundle.fields[1].attempted
    assert g.CandidateBundle.model_validate_json(bundle.model_dump_json()) == bundle


def test_reviewer_rejects_changed_value_without_generator_self_scoring():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    bad = out.output.model_copy(
        update={
            "definitions": tuple(
                d.model_copy(update={"body": "所有费用均无条件报销"})
                for d in out.output.definitions
            )
        }
    )
    checked = fixture_reviewer(g, out.output).review(req, bad, run_id="review-b")
    assert checked.output.decision == "REJECT"
    assert "NOT_EXACT_EXTRACTION" in checked.output.reasons
    with pytest.raises(ValueError):
        g.assemble_bundle(req, out.model_copy(update={"output": bad}), checked)


def test_compiler_and_reviewer_can_be_replaced_independently():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="rule-compile")

    class Transport:
        def __init__(self, wire):
            self.wire = wire
            self.calls = []

        def complete(self, system, user):
            self.calls.append((system, user))
            return self.wire

    transport = Transport(out.output.model_dump_json())
    llm = g.LLMCompiler(transport, "approved-model-identity")
    other = llm.compile(req, run_id="llm-compile")
    reviewer = fixture_reviewer(g, out.output)
    checked = reviewer.review(req, other.output, run_id="rule-review")
    review_transport = Transport(checked.output.model_dump_json())
    other_checked = g.LLMReviewer(review_transport, "approved-model-identity").review(
        req, other.output, run_id="llm-review"
    )
    first = g.assemble_bundle(req, out, checked)
    second = g.assemble_bundle(req, other, other_checked)
    assert first.page_manifest.contract == second.page_manifest.contract
    assert first.page_manifest.members == second.page_manifest.members
    assert transport.calls[0][0] != review_transport.calls[0][0]
    assert "compiler_execution" not in json.loads(review_transport.calls[0][1])
    assert other.execution.raw_output == out.output.model_dump_json()


def test_candidate_binding_and_complete_required_fields_fail_closed():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    checked = fixture_reviewer(g, out.output).review(req, out.output, run_id="review-a")
    with pytest.raises(ValueError):
        g.assemble_bundle(
            req,
            out,
            checked.model_copy(
                update={"execution": checked.execution.model_copy(update={"run_id": "compile-a"})}
            ),
        )
    missing = out.output.model_copy(update={"fields": out.output.fields[:1]})
    with pytest.raises(ValueError):
        g.assemble_bundle(req, out.model_copy(update={"output": missing}), checked)


def test_pending_rejected_and_duplicate_are_audit_only():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    audited = out.output.model_copy(
        update={
            "audit": out.output.audit
            + (
                g.AuditDisposition(key="ad", disposition="reject", reason="NO_EVIDENCE"),
                g.AuditDisposition(key="uncertain", disposition="pending", reason="NEEDS_HUMAN"),
                g.AuditDisposition(key="repeat", disposition="duplicate", reason="SAME_IDENTITY"),
            )
        }
    )
    rec = g.record_output("compile-a", "template.v1", g.compiler_context(req), audited)
    out = g.CompileResult(output=audited, execution=rec)
    checked = fixture_reviewer(g, out.output).review(req, audited, run_id="review-a")
    bundle = g.assemble_bundle(req, out, checked)
    assert len(bundle.audit) == len(compiler(g).compile(req, run_id="baseline").output.audit) + 3
    assert not any(x.title in {"ad", "uncertain", "repeat"} for x in bundle.page_manifest.members)


def test_reloaded_bundle_rejects_member_content_and_review_tampering():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    bundle = g.assemble_bundle(
        req, out, fixture_reviewer(g, out.output).review(req, out.output, run_id="review-a")
    )
    wire = json.loads(bundle.model_dump_json())
    wire["page_manifest"]["members"][0]["content"] = "tampered"
    with pytest.raises(ValueError):
        g.CandidateBundle.model_validate(wire)
    wire = json.loads(bundle.model_dump_json())
    wire["review_result"]["execution"]["context_hash"] = "f" * 64
    with pytest.raises(ValueError):
        g.CandidateBundle.model_validate(wire)


def test_orphan_definition_and_unknown_entity_rejected_before_review():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    orphan = out.output.model_copy(
        update={
            "fields": tuple(f.model_copy(update={"concept_ids": ()}) for f in out.output.fields)
        }
    )
    result = fixture_reviewer(g, out.output).review(req, orphan, run_id="review-a")
    assert result.output.decision == "REJECT"
    assert "ORPHAN_CONCEPT" in result.output.reasons


def fixture_reviewer(g, output):
    score = g.ValueScore(
        business_value=25,
        reuse=20,
        evidence_quality=20,
        definability=15,
        novel_identity=10,
        name_stability=10,
    )
    return g.ExtractReviewer(scores={d.concept_id: score for d in output.definitions})


def test_independent_page_score_is_required_and_cannot_be_offset_by_evidence():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    checked = g.ExtractReviewer().review(req, out.output, run_id="review-a")
    assert checked.output.decision == "NEEDS_HUMAN"
    with pytest.raises(ValueError):
        g.assemble_bundle(req, out, checked)
    low = g.ValueScore(
        business_value=25,
        reuse=20,
        evidence_quality=20,
        definability=14,
        novel_identity=0,
        name_stability=0,
    )
    checked = g.ExtractReviewer(scores={out.output.definitions[0].concept_id: low}).review(
        req, out.output, run_id="review-b"
    )
    assert checked.output.decision == "NEEDS_HUMAN"
    with pytest.raises(ValueError):
        g.assemble_bundle(req, out, checked)
    with pytest.raises(ValueError):
        g.ValueScore(
            business_value=26,
            reuse=20,
            evidence_quality=20,
            definability=15,
            novel_identity=10,
            name_stability=10,
        )


def test_scoped_source_and_existing_expert_definition_cannot_be_rebound():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    foreign = req.model_copy(update={"space_id": "space-b"})
    with pytest.raises(ValueError, match="CROSS_SPACE_SOURCE"):
        g.validate_output(foreign, out.output)
    expert = out.output.definitions[0].model_copy(update={"origin": "EXPERT_REVISION_RECORD"})
    req = req.model_copy(update={"existing_definitions": (expert,)})
    changed = out.output.model_copy(update={"request_hash": req.request_hash})
    with pytest.raises(ValueError, match="PROTECTED_DEFINITION_REPLACED"):
        g.validate_output(req, changed)


def test_disposition_must_cover_every_member_without_ghost_admission():
    g = api()
    req = request(g)
    out = compiler(g).compile(req, run_id="compile-a")
    for audit in (
        (),
        out.output.audit
        + (g.AuditDisposition(key="ghost", disposition="new_page", reason="ADMIT"),),
    ):
        changed = out.output.model_copy(update={"audit": audit})
        with pytest.raises(ValueError, match="DISPOSITION_MEMBER_MISMATCH"):
            g.validate_output(req, changed)


def test_existing_snapshot_supports_reuse_without_changing_definition_body_hash():
    g = api()
    req = request(g)
    initial = compiler(g).compile(req, run_id="compile-a")
    d = initial.output.definitions[0]
    assert d.definition_hash == d.model_copy(update={"aliases": ("受保人",)}).definition_hash
    req = req.model_copy(
        update={
            "existing_definitions": initial.output.definitions,
            "existing_fields": initial.output.fields,
            "existing_pages": (),
            "existing_entity_versions": {"entity-a": "v1"},
        }
    )
    out = g.ExtractCompiler(definitions=(), fields=compiler(g).fields).compile(
        req, run_id="compile-b"
    )
    assert any(a.key == d.concept_id and a.disposition == "alias_link" for a in out.output.audit)
    assert g.ExtractReviewer().review(req, out.output, run_id="review-b").output.decision == "PASS"


def test_free_wiki_page_has_independent_admission_and_source_bound_member():
    g = api()
    req = request(g)
    first = compiler(g).compile(req, run_id="compile-a")
    definition = first.output.definitions[0]
    page = g.FreeWikiPage(
        space_id=req.space_id,
        entity_id="entity-a",
        stable_key="insured-note",
        title="被保险人说明",
        body=definition.body,
        evidence=definition.evidence,
        concept_ids=(definition.concept_id,),
        entity_version="v1",
    )
    key = g.free_page_id(page)
    output = first.output.model_copy(
        update={
            "pages": (page,),
            "audit": first.output.audit
            + (
                g.AuditDisposition(
                    key=key, disposition="new_page", reason="INDEPENDENT_REUSABLE_NOTE"
                ),
            ),
        }
    )
    compiled = g.CompileResult(
        output=output,
        execution=g.record_output("compile-a", "fixture-compiler", g.compiler_context(req), output),
    )
    reviewer = fixture_reviewer(g, output)
    reviewer.scores[key] = next(iter(reviewer.scores.values()))
    checked = reviewer.review(req, output, run_id="review-a")
    bundle = g.assemble_bundle(req, compiled, checked)
    member = next(m for m in bundle.page_manifest.members if m.kind == "free_wiki_item")
    assert member.member_id == key and member.content == page.body
    assert bundle.page_manifest.audit == output.audit
    without = output.model_copy(update={"audit": first.output.audit})
    with pytest.raises(ValueError, match="DISPOSITION_MEMBER_MISMATCH"):
        g.validate_output(req, without)


@pytest.mark.parametrize("version", ["", "v0", "v2"])
def test_generated_and_existing_members_bind_exact_entity_version(version):
    g = api()
    req = request(g)
    first = compiler(g).compile(req, run_id="compile-version")
    assert all(f.entity_version == req.entity_versions[f.entity_id] for f in first.output.fields)
    for index in range(len(first.output.fields)):
        fields = list(first.output.fields)
        fields[index] = fields[index].model_copy(update={"entity_version": version})
        with pytest.raises(ValueError, match="ENTITY_VERSION_MISMATCH"):
            g.validate_output(req, first.output.model_copy(update={"fields": tuple(fields)}))
        stale = req.model_copy(
            update={
                "existing_definitions": first.output.definitions,
                "existing_fields": tuple(fields),
                "existing_entity_versions": {"entity-a": "v1"},
            }
        )
        with pytest.raises(ValueError, match="EXISTING_ENTITY_VERSION_MISMATCH"):
            g.CompileRequest.model_validate(stale)
    d = first.output.definitions[0]
    page = g.FreeWikiPage(
        space_id=req.space_id,
        entity_id="entity-a",
        stable_key="note",
        title="Note",
        body=d.body,
        evidence=d.evidence,
        entity_version=version,
    )
    with pytest.raises(ValueError, match="ENTITY_VERSION_MISMATCH"):
        g.validate_output(req, first.output.model_copy(update={"pages": (page,)}))
    with pytest.raises(ValueError, match="EXISTING_ENTITY_VERSION_MISMATCH"):
        g.CompileRequest.model_validate(
            req.model_copy(
                update={"existing_pages": (page,), "existing_entity_versions": {"entity-a": "v1"}}
            )
        )


def human_review_case(g, total=66, decision="PASS"):
    req = request(g)
    compiled = compiler(g).compile(req, run_id="compile-human")
    remaining = total
    values = []
    for ceiling in (25, 20, 20, 15, 10, 10):
        value = min(remaining, ceiling)
        values.append(value)
        remaining -= value
    score = g.ValueScore(
        **dict(
            zip(
                (
                    "business_value",
                    "reuse",
                    "evidence_quality",
                    "definability",
                    "novel_identity",
                    "name_stability",
                ),
                values,
                strict=True,
            )
        )
    )
    checked = g.ReviewOutput(
        request_hash=req.request_hash,
        output_hash=compiled.output.output_hash,
        decision=decision,
        page_scores={compiled.output.definitions[0].concept_id: score},
        reasons=("Independent review retained without score adjustment",),
    )
    review = g.ReviewResult(
        output=checked,
        execution=g.record_output(
            "review-human",
            "independent-fixture-reviewer",
            g.review_context(req, compiled.output),
            checked,
        ),
    )
    return req, compiled, review


@pytest.mark.parametrize("total", [60, 66, 79, 80])
@pytest.mark.parametrize("decision", ["PASS", "NEEDS_HUMAN"])
def test_human_bundle_keeps_raw_score_and_freezes_whole_pending_set(total, decision):
    g = api()
    req, compiled, checked = human_review_case(g, total, decision)
    bundle = g.assemble_human_review_bundle(req, compiled, checked)
    assert bundle.contract == "concept-candidate-bundle.830.g2.v2"
    assert bundle.admission.status == "NEEDS_HUMAN"
    expected = (compiled.output.definitions[0].concept_id,) if total < 80 else ()
    assert bundle.admission.pending_page_ids == expected
    assert bundle.review_result == checked
    assert bundle.review_result.execution.raw_output == checked.execution.raw_output
    assert bundle.page_manifest == g.project_members(req, compiled.output)
    assert g.HumanReviewCandidateBundle.model_validate_json(bundle.model_dump_json()) == bundle
    if total < 80 or decision != "PASS":
        with pytest.raises(ValueError):
            g.assemble_bundle(req, compiled, checked)


@pytest.mark.parametrize("total,decision", [(59, "PASS"), (66, "REJECT")])
def test_human_bundle_does_not_override_low_score_or_rejection(total, decision):
    g = api()
    with pytest.raises(ValueError):
        g.assemble_human_review_bundle(*human_review_case(g, total, decision))


def test_human_bundle_rejects_missing_score_and_pending_set_tampering():
    g = api()
    req, compiled, checked = human_review_case(g)
    missing = checked.output.model_copy(update={"page_scores": {}})
    missing_review = g.ReviewResult(
        output=missing,
        execution=g.record_output(
            "missing-score",
            "independent-fixture-reviewer",
            g.review_context(req, compiled.output),
            missing,
        ),
    )
    with pytest.raises(ValueError):
        g.assemble_human_review_bundle(req, compiled, missing_review)
    bundle = g.assemble_human_review_bundle(req, compiled, checked)
    for pending in ([], ["unrelated"], list(bundle.admission.pending_page_ids) * 2):
        wire = bundle.model_dump(mode="json")
        wire["admission"]["pending_page_ids"] = pending
        wire["candidate_hash"] = g.digest(
            "candidate-bundle", {k: v for k, v in wire.items() if k != "candidate_hash"}
        )
        with pytest.raises(ValueError, match="ADMISSION"):
            g.HumanReviewCandidateBundle.model_validate(wire)


def test_llm_raw_review_cannot_omit_contract_default_or_repeat_keys():
    g = api()
    req, compiled, checked = human_review_case(g)
    wire = checked.output.model_dump(mode="json")
    del wire["contract"]
    malformed = [
        json.dumps(wire),
        checked.output.model_dump_json().replace(
            '"decision":"PASS"',
            '"decision":"PASS","decision":"PASS"',
            1,
        ),
    ]
    for raw in malformed:

        class Transport:
            def __init__(self, response):
                self.response = response

            def complete(self, system, user):
                return self.response

        with pytest.raises(ValueError, match="RAW_OUTPUT"):
            g.LLMReviewer(Transport(raw), "fake-local").review(
                req, compiled.output, run_id="bad-wire"
            )


@pytest.mark.parametrize(
    "location,key", [("bundle", "contract"), ("admission", "contract"), ("admission", "status")]
)
def test_human_wire_cannot_hide_missing_admission_fields_with_defaults(location, key):
    g = api()
    bundle = g.assemble_human_review_bundle(*human_review_case(g))
    wire = bundle.model_dump(mode="json")
    del (wire if location == "bundle" else wire["admission"])[key]
    with pytest.raises(ValueError):
        g.HumanReviewCandidateBundle.model_validate(wire)

"""Deterministic escaped static HTML renderer for an OpenSpec077 dossier."""

from __future__ import annotations

from html import escape

from insurance_harness.canonical import canonical_bytes
from insurance_harness.knowledge_compiler.review_dossier import (
    DossierFactV1,
    ReviewDossierV1,
)


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _fact_html(value: DossierFactV1, label: str) -> str:
    candidate = value.field_candidate
    evidence_rows = "".join(
        "<li>"
        f"source_revision={_text(evidence.source_revision_id)}; "
        f"parse_attempt={_text(evidence.parse_attempt_id)}; "
        f"parsed_document={_text(evidence.parsed_document_hash)}; "
        f"parse_manifest={_text(evidence.parse_manifest_hash)}; "
        f"type={_text(evidence.locator.subject_type)}; "
        f"ref={_text(evidence.locator.subject_ref)}; "
        f"page={_text(evidence.locator.page_number)}; "
        f"parents={_text(','.join(evidence.locator.parent_refs))}; "
        f"content={_text(evidence.locator.content_snapshot)}; "
        f"content_sha256={_text(evidence.locator.content_snapshot_sha256)}; "
        f"quote={_text(evidence.quote_snapshot)}; "
        f"quote_sha256={_text(evidence.quote_snapshot_sha256)}; "
        f"value_sha256={_text(evidence.value_snapshot_sha256)}; "
        f"support_product={_text(evidence.support_scope.product_version_id)}; "
        f"support_subject={_text(evidence.support_scope.subject_id)}; "
        f"support_conditions={_text(','.join(evidence.support_scope.condition_ids))}"
        "</li>"
        for evidence in candidate.evidence
    )
    value_json = canonical_bytes(
        None if candidate.value is None else candidate.value.model_dump(mode="python")
    ).decode("utf-8")
    return (
        f"<section><h4>{_text(label)}: {_text(candidate.field_id)}</h4>"
        f"<p>fact={_text(value.fact.fact_hash)}; "
        f"verification={_text(value.verification_hash)}; "
        f"verification_status={_text(value.verification_result.status)}; "
        f"candidate={_text(value.candidate_snapshot_hash)}; "
        f"state={_text(value.fact.state)}; "
        f"fact_value_sha256={_text(value.fact.value_hash)}; "
        f"value={_text(value_json)}</p>"
        f"<ul>{evidence_rows}</ul></section>"
    )


def render_review_dossier_html(dossier: ReviewDossierV1) -> str:
    """Render one review surface with no controls, scripts, or external resources."""

    exact = ReviewDossierV1.model_validate(
        dossier.model_dump(mode="python", exclude_computed_fields=True)
    )
    counts = exact.counts
    changes = "".join(
        "<article>"
        f"<h3>{_text(change.field_id)} — {_text(change.category)} "
        f"({_text(change.raw_action)})</h3>"
        f"<p>change={_text(change.change_item_hash)}; reason={_text(change.reason)}; "
        f"retraction_proof={_text(change.retraction_proof_hash)}</p>"
        + "".join(
            _fact_html(fact, "prior") for fact in change.prior_facts
        )
        + (
            ""
            if change.incoming_fact is None
            else _fact_html(change.incoming_fact, "incoming")
        )
        + "</article>"
        for change in exact.changes
    )
    review_items = "".join(
        f"<li>{_text(item.field_id)}: {_text(','.join(item.reasons))}; "
        f"item={_text(item.review_item_hash)}</li>"
        for item in exact.review_items
    )
    repairs = "".join(
        "<li>"
        f"resolution={_text(item.resolution_hash)}; "
        f"parent_verification={_text(item.parent_verification_hash)}; "
        f"repair_plan={_text(item.repair_plan_hash)}"
        "<ul>"
        + "".join(
            f"<li>result field={_text(result.field_id)}; "
            f"status={_text(result.status)}; "
            f"reasons={_text(','.join(result.reason_codes))}; "
            f"candidate={_text(result.candidate_snapshot_hash)}</li>"
            for result in item.results
        )
        + "".join(
            f"<li>gap field={_text(gap.field_id)}; "
            f"reasons={_text(','.join(gap.reason_codes))}</li>"
            for gap in item.gaps
        )
        + "".join(
            f"<li>review field={_text(review.field_id)}; "
            f"reason={_text(review.reason_code)}; "
            f"parent={_text(review.parent_verification_hash)}</li>"
            for review in item.review_items
        )
        + "</ul></li>"
        for item in exact.repair_resolutions
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Candidate human review dossier</title></head><body>"
        "<main><h1>Complete Candidate human review dossier</h1>"
        f"<p>authority={_text(exact.authority)}; "
        f"upstream={_text(exact.upstream_authority)}</p>"
        f"<p>candidate={_text(exact.candidate_hash)}; "
        f"batch={_text(exact.human_batch_hash)}; dossier={_text(exact.dossier_hash)}</p>"
        f"<p>add={counts.add}; update={counts.update}; conflict={counts.conflict}; "
        f"retract={counts.retract}; high_risk={counts.high_risk}; "
        f"repair={counts.repair}; gap={counts.gap}</p>"
        f"<section><h2>Changes</h2>{changes}</section>"
        f"<section><h2>Named-human review requirements</h2><ul>{review_items}</ul></section>"
        f"<section><h2>Repair and gap custody</h2><ul>{repairs}</ul></section>"
        "</main></body></html>"
    )

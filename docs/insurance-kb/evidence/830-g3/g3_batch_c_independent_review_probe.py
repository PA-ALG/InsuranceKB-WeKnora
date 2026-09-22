import json
import runpy
import sys
from pathlib import Path

WORKTREE = Path("/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation")
sys.path.insert(0, str(WORKTREE / "harness/src"))
ns = runpy.run_path(str(WORKTREE / "harness/tests/test_batch_entity_resolution_830_g3.py"))
g = ns["g"]
catalog = ns["catalog"].__wrapped__()


def expect(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


# Normalized approved-alias competition must not CREATE under another code.
existing_entity = g.ExistingEntityV1(
    entity_id="serving-alias-space",
    entity_version="version-alias-space",
    product_id=None,
    product_version_id=None,
    issuer="平安保险",
    name="别名正式名",
    product_code="OLD-ALIAS",
    version_label="2025",
    filing_or_registration=g.VersionAnchorV1(kind="registration_number", value="OLD-REG"),
    approved_aliases=(g.ApprovedAliasV1(value="竞 争 产品", approval_receipt_sha256="f" * 64),),
    identity_evidence_sha256s=("e" * 64,),
)
entry = ns["_entry"](
    material_id="probe-alias-normalized",
    text="平安保险 竞争产品 产品代码 NEW-ALIAS 登记编号 NEW-REG 版本 2026 医疗保险 官方条款",
)
alias_result = ns["_resolve"](
    catalog,
    (entry,),
    (({"proposal_ref": "p", "name": "竞争产品", "product_code": "NEW-ALIAS", "filing": "NEW-REG"},),),
    existing=ns["_existing"](existing_entity),
)
alias_child = alias_result.decisions[0].children[0]
expect(alias_child.disposition == "NEEDS_CONFIRM", "normalized alias competition stays human")
expect("AMBIGUOUS_IDENTITY" in alias_child.reason_codes, "normalized alias competition reason")


# A same-key row with a mis-purposed identity evidence ID must not contribute to the good candidate.
good = ns["_entry"](
    material_id="probe-good",
    text="平安保险 证据隔离产品 产品代码 ISO1 登记编号 ISO-REG 版本 2026 医疗保险 官方条款",
)
bad = ns["_entry"](
    material_id="probe-bad",
    text="平安保险 证据隔离产品 产品代码 ISO1 登记编号 ISO-REG 版本 2026 医疗保险 官方条款",
)
corpus = ns["_corpus"](bad, good)
binding = ns["_model_binding"](corpus, bad, good)
good_proposal = ns["_material_proposal"](
    good, binding, entities=({"proposal_ref": "good", "name": "证据隔离产品", "product_code": "ISO1", "filing": "ISO-REG"},)
)
bad_proposal = ns["_material_proposal"](
    bad, binding, entities=({"proposal_ref": "bad", "name": "证据隔离产品", "product_code": "ISO1", "filing": "ISO-REG"},)
)
bad_entity = bad_proposal.entities[0].model_copy(
    update={"identity_evidence_ids": ("probe-bad-bad-classification",)}
)
bad_values = bad_proposal.model_dump(mode="python", exclude={"proposal_sha256"})
bad_values["entities"] = (bad_entity,)
bad_proposal = ns["_new"](
    g.MaterialProposalV1,
    "material-proposal.830.g3.v1",
    "proposal_sha256",
    **bad_values,
)
isolation_result = g.resolve_batch(
    catalog=catalog,
    corpus=corpus,
    proposals=ns["_proposal_batch"](corpus, (binding,), (bad_proposal, good_proposal)),
    existing_entities=ns["_existing"](),
    policy=ns["_policy"](),
)
by_material = {item.material_id: item for item in isolation_result.decisions}
good_candidate = by_material["probe-good"].children[0].entity_candidate
expect(by_material["probe-bad"].disposition == "QUARANTINE", "mis-purposed identity evidence quarantines row")
expect(good_candidate is not None, "eligible peer retains candidate")
expect(all(item.startswith("probe-good-") for item in good_candidate.evidence_ids), "bad-row evidence excluded from candidate")


# A self-consistently rehashed MULTI wire cannot reuse one child's evidence for another identity.
multi_entry = ns["_entry"](
    material_id="probe-multi-wire",
    text="平安保险 产品甲 产品代码 MA 登记编号 RA 版本 2026 产品乙 产品代码 MB 登记编号 RB 医疗保险 官方条款",
)
multi = ns["_resolve"](
    catalog,
    (multi_entry,),
    ((
        {"proposal_ref": "a", "name": "产品甲", "product_code": "MA", "filing": "RA"},
        {"proposal_ref": "b", "name": "产品乙", "product_code": "MB", "filing": "RB"},
    ),),
)
wire = multi.model_dump(mode="json")
first, second = wire["decisions"][0]["children"]
second["evidence_ids"] = list(first["evidence_ids"])
second["entity_candidate"]["evidence_ids"] = list(first["evidence_ids"])
wire = ns["_rehash_resolution_wire"](wire)
try:
    g.validate_batch(json.dumps(wire, ensure_ascii=False))
except g.BatchEntityResolutionError as exc:
    expect(exc.reason_code == "COMPILED_BATCH_INVALID", "shared MULTI evidence rejected after full rehash")
else:
    raise AssertionError("shared MULTI evidence was accepted")


# Observed typography may differ when its normalized anchor remains identical.
format_entry = ns["_entry"](
    material_id="probe-observed-format",
    text="平安保险 格式产品 产品代码 FMT1 登记编号 FMT-REG 版本 2026 医疗保险 官方条款",
)
formatted = ns["_resolve"](
    catalog,
    (format_entry,),
    (({"proposal_ref": "p", "name": "格式产品", "product_code": "FMT1", "filing": "FMT-REG"},),),
)
wire = formatted.model_dump(mode="json")
wire["decisions"][0]["children"][0]["entity_candidate"]["name"] = {
    "observed_value": "格 式 产品",
    "normalized_value": "格式产品",
}
wire = ns["_rehash_resolution_wire"](wire)
validated = g.validate_batch(json.dumps(wire, ensure_ascii=False))
expect(validated.decisions[0].disposition == "CREATE", "normalized-equal observed formatting remains valid")

print("PASS 4 independent scenarios / 8 assertions")

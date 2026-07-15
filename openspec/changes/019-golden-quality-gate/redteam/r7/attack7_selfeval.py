"""Attack: validate._check_self_eval uses evaluate(records, usable) where pred=usable.
Verify disputed records (disputed-only, same-key twin, bad-value disputed) cannot
break the Q1.4 self-eval==1.0 requirement, nor sneak a key into the metric.
"""
from datetime import UTC, datetime

from insurance_harness.goldenset.validate import _check_self_eval
from insurance_harness.goldenset.records import GoldenRecord, Evidence

_AT = datetime(2026, 7, 14, tzinfo=UTC)


def _rec(product, field_id, value, tri="present", *, disputed=False, ev=True):
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=[Evidence(page=1, quote=value)] if (value and ev) else [],
        annotator_model="m", schema_version="v1.1+x", created_at=_AT, disputed=disputed,
    )


scenarios = {
    "clean_no_disputed": [_rec(f"P{i}", "f1", f"v{i}") for i in range(3)],
    "with_disputed_only": [_rec("P0", "f1", "v0"),
                           _rec("D0", "f1", "争议", disputed=True)],
    "disputed_absent_only": [_rec("P0", "f1", "v0"),
                             _rec("D0", "f1", None, "absent_explicitly", disputed=True)],
    "same_key_disputed_twin_diff_value": [
        _rec("P0", "f1", "正确", "present"),
        _rec("P0", "f1", "争议不同值", "present", disputed=True)],
    "disputed_no_evidence": [_rec("P0", "f1", "v0"),
                             _rec("D0", "f1", "争议", disputed=True, ev=False)],
    "all_disputed_one_usable": [_rec("P0", "f1", "v0"),
                                *[_rec(f"D{i}", "f2", "x", disputed=True) for i in range(3)]],
}

# self-eval WITHOUT dataset_root and require_evidence=False -> only P/R/F1 checked.
allok = True
for name, recs in scenarios.items():
    chk = _check_self_eval(recs, dataset_root=None, require_evidence=False)
    print(f"  {name}: passed={chk.passed}  detail={chk.detail}")
    if not chk.passed:
        allok = False

print("\n" + ("SELF-EVAL ROBUST to disputed (all P/R/F1=1.0)"
              if allok else "!!! SELF-EVAL BROKEN by some disputed shape"))

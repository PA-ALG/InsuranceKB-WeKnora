"""Attack: can a disputed-key prediction with evidence inflate/deflate evidence_accuracy?

evaluate global evidence filters excluded_only; build_profile per-field evidence
excludes disputed-only keys. We mock extract_pages and probe both directions
(good quote -> inflate; bad quote -> deflate) for KNOWN and UNKNOWN disputed fields.
"""
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import insurance_harness.goldenset.pdf as pdfmod
from insurance_harness.goldenset.eval import evaluate
from insurance_harness.goldenset.profile import build_profile
from insurance_harness.goldenset.baseline import RunFingerprint
from insurance_harness.goldenset.records import GoldenRecord, Evidence

_AT = datetime(2026, 7, 14, tzinfo=UTC)
_ART = "a" * 64

# page text contains GOOD* quotes; NOT any BAD* quote
_PAGE_TEXT = "GOODU GOODD GOODK OTHERTEXT"


class _Pg:
    def __init__(self, n, t):
        self.page_no = n
        self.text = t


def _fp():
    return RunFingerprint(git_sha="abc", schema_version="v1.1+x", model_id="m1",
                          prompt_version="p1", template_profile="t1", source_profile="s1",
                          golden_release_hash="a" * 64)


def _rec(product, field_id, value, tri="present", *, quote=None, disputed=False, evidence=True):
    ev = []
    if evidence and value:
        ev = [Evidence(page=1, quote=quote if quote is not None else value)]
    return GoldenRecord(
        product_id=product, product_name=f"产品{product}", doc="d.pdf",
        field_id=field_id, field_name=field_id, value=value, tri_state=tri,
        evidence=ev, annotator_model="m", schema_version="v1.1+x",
        created_at=_AT, disputed=disputed,
    )


def metrics(golden, pred, root):
    ev = evaluate(golden, pred, dataset_root=root)
    prof = build_profile(golden, pred, _fp(), artifact_sha256=_ART, dataset_root=root)
    fld = {fid: m.evidence_accuracy for fid, m in prof.fields.items()}
    return {
        "global_evidence(eval)": ev.evidence_accuracy,
        "global_evidence(profile)": prof.global_metrics.evidence_accuracy,
        "per_field_evidence": fld,
    }


def run():
    pdfmod.extract_pages = lambda _p: [_Pg(1, _PAGE_TEXT)]  # monkeypatch
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    # products used: U0 (usable), D0 (disputed) -> need dirs+pdf for each product_name
    for prod in ("U0", "D0"):
        d = root / f"产品{prod}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "d.pdf").write_text("x", encoding="utf-8")

    fails = []

    # ---- Case 1: base evidence PERFECT (1.0); disputed pred with BAD quote must NOT deflate.
    g = [_rec("U0", "f1", "GOODU", quote="GOODU")]
    p = [_rec("U0", "f1", "GOODU", quote="GOODU")]
    before = metrics(g, p, root)
    # append disputed-only known-field f1, pred present with a BAD (unverifiable) quote
    g2 = g + [_rec("D0", "f1", "GOODD", quote="GOODD", disputed=True)]
    p2 = p + [_rec("D0", "f1", "编造", quote="BADQUOTE")]
    after = metrics(g2, p2, root)
    print("Case1 base(perfect) + disputed known-field pred w/ BAD quote:")
    print("  before:", before)
    print("  after :", after)
    if before != after:
        fails.append(("case1_deflate_known", before, after))

    # ---- Case 2: base evidence FAILING (0.0); disputed pred with GOOD quote must NOT inflate.
    g = [_rec("U0", "f1", "GOODU", quote="MISSINGQUOTE")]  # base quote not on page -> 0/1
    p = [_rec("U0", "f1", "GOODU", quote="MISSINGQUOTE")]
    before = metrics(g, p, root)
    g2 = g + [_rec("D0", "f1", "GOODD", quote="GOODD", disputed=True)]
    p2 = p + [_rec("D0", "f1", "编造", quote="GOODD")]  # good quote -> would inflate if counted
    after = metrics(g2, p2, root)
    print("\nCase2 base(failing 0.0) + disputed known-field pred w/ GOOD quote:")
    print("  before:", before)
    print("  after :", after)
    if before != after:
        fails.append(("case2_inflate_known", before, after))

    # ---- Case 3: disputed UNKNOWN field, pred present with good/bad quote.
    g = [_rec("U0", "f1", "GOODU", quote="GOODU")]
    p = [_rec("U0", "f1", "GOODU", quote="GOODU")]
    before = metrics(g, p, root)
    g2 = g + [_rec("D0", "fZZ", "GOODD", quote="GOODD", disputed=True)]
    p2 = p + [_rec("D0", "fZZ", "编造", quote="BADQUOTE")]
    after = metrics(g2, p2, root)
    print("\nCase3 base + disputed UNKNOWN-field pred w/ BAD quote:")
    print("  before:", before)
    print("  after :", after)
    if before != after:
        fails.append(("case3_unknown", before, after))

    print("\n" + ("EVIDENCE INVARIANT HELD" if not fails
                  else f"!!! EVIDENCE INVARIANT VIOLATED: {[f[0] for f in fails]}"))
    for name, b, a in fails:
        print(f"  {name}: before={b} after={a}")
    return fails


if __name__ == "__main__":
    run()

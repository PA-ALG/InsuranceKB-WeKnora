"""PV-1 review R6 (written by Claude): the attribution policy version marks the PV-1 rules.

S5b-1 §2.1: any rule change bumps the policy version, so a recorded decision tells which rules
made it. Decisions made before keep their own policy_ref.
"""

from insurance_harness.identity.attribution import attribute, load_attribution_policy
from insurance_harness.ingest.uploads import attribute_uploads
from tests.identity.test_attribution import registered, upload
from tests.ingest.upload_helpers import Pages, entry, raw, registry
from tests.ingest.version_helpers import POLICY, rich_v1

NEW = "attribution-policy@2026-11-01.4"  # PV-3 (and its review) bumped it on top of PV-1


def test_the_policy_version_names_the_new_version_rule() -> None:
    policy = load_attribution_policy()
    assert policy.policy_ref == NEW != POLICY
    assert "PV-1" in policy.basis and "NEW_VERSION" in policy.basis
    head = upload("1828", "terms").head.replace("174号", "999号", 1)
    versioned = attribute(upload("1828", "terms", sha256="e" * 64, head=head), [registered("1828")])
    assert (versioned.outcome, versioned.policy_ref) == ("NEW_VERSION", NEW)


def test_recorded_decisions_keep_the_policy_they_were_made_under() -> None:
    value = rich_v1()
    before = [d.attribution.policy_ref for d in value.decisions]
    source = raw("1814", "brochure", knowledge_id="k-1814-brochure2", sha256="f" * 64)
    reader = Pages(heads={"k-1814-brochure2": upload("1814", "brochure").head}, sources=[source])
    run = attribute_uploads(value, [source], reader)
    assert [d.attribution.policy_ref for d in run.registry.decisions][: len(before)] == before
    assert all(p == POLICY for p in before)
    unchanged = attribute_uploads(registry(p1828=entry("1828", "terms")), [], Pages())
    assert unchanged.registry.decisions == []

"""Recording and expiring material-level method uses during a run (SK-1 Spec §3).

A run reads each judged material's pages once; this module decides, for a v2 registry only,
whether the material is a sales-method material, records its method use beside whatever its
product attribution concluded, and turns what would be a quarantine into a METHOD_MATERIAL. It
also expires records whose source revision is no longer the listed one. The product side —
entries, their materials and roles, the source map — is never touched here.
"""

from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from insurance_harness.catalog.sales_taxonomy import SalesTaxonomy, load_sales_taxonomy
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.weknora_pages import SourcePagesError
from insurance_harness.identity.attribution import Attribution, AttributionPolicy
from insurance_harness.identity.method_signals import BLOCK_SCHEME, MethodHits, detect
from insurance_harness.ingest.method_use_model import LIVE, MethodUse, check_method_uses
from insurance_harness.ingest.raw_sources import RawSource, UnfinishedSource, material_pages
from insurance_harness.ingest.registry import V2, ProductRegistry
from insurance_harness.ingest.source_map import PageReader

_JUDGED = frozenset({"QUARANTINE", "METHOD_MATERIAL", "SUPPLEMENT", "NEEDS_CONFIRM"})
_ENDED = frozenset({"IGNORED", "DETACHED"})  # a material that no longer takes part (Spec §3.1)


def expired(use: MethodUse, reason: str) -> MethodUse:
    """The record, expired: kept for audit, never revived."""
    data = use.model_dump() | {"state": "invalidated", "invalidated_reason": reason}
    return MethodUse.model_validate(data | {"settlement": None, "editing": False})


def expire_method_uses(
    registry: ProductRegistry,
    sources: Sequence[RawSource],
    unfinished: Sequence[UnfinishedSource] = (),
) -> None:
    """Expire, in place, the live records the completed listing no longer supports (Spec §3.4):
    another revision listed, not listed at all (a material still being parsed is not gone), or
    the material ignored by a person. A record whose answer is being carried out (it has a
    settlement) is left as it is until `confirm` completes it (Spec §4.3)."""
    listed = {s.knowledge_id: (s.parse_attempt, s.sha256) for s in sources}
    parsing = {u.knowledge_id for u in unfinished}
    ignored = {d.knowledge_id for d in registry.decisions if d.attribution.outcome == "IGNORED"}
    kept = []
    for use in registry.method_uses:
        reason = None
        if use.state in LIVE and use.settlement is None:
            if use.knowledge_id in ignored:
                reason = "ignored"
            elif use.knowledge_id in listed and listed[use.knowledge_id] != use.triple[1:]:
                reason = "source_revised"
            elif use.knowledge_id not in listed and use.knowledge_id not in parsing:
                reason = "withdrawn"
        kept.append(expired(use, reason) if reason else use)
    registry.method_uses = kept


def expire_material(registry: ProductRegistry, knowledge_id: str, reason: str) -> bool:
    """Expire, in place, a material's live record (a detach, Spec §3.4); True when one was live."""
    found = False
    kept = []
    for use in registry.method_uses:
        if use.knowledge_id == knowledge_id and use.state in LIVE:
            use, found = expired(use, reason), True
        kept.append(use)
    registry.method_uses = kept
    return found


class MethodStep:
    """One run's method decisions: detected once per material, recorded beside the product one."""

    def __init__(
        self,
        registry: ProductRegistry,
        pages: Mapping[str, Sequence[PageText]],
        policy: AttributionPolicy,
        taxonomy: SalesTaxonomy | None = None,
    ) -> None:
        self.registry, self.pages, self.policy = registry, pages, policy
        self.taxonomy = taxonomy or load_sales_taxonomy()
        self._hits: dict[tuple[str, int, str], MethodHits | None] = {}

    def hits(self, source: RawSource, attribution: Attribution) -> MethodHits | None:
        """The material's method blocks, if it may be a method material (Spec §3.1)."""
        if self.registry.contract != V2 or not self._eligible(source, attribution):
            return None
        if self._settled(source):
            return None
        return self._detect(source, self.pages.get(source.knowledge_id, ()))

    def backfill(self, sources: Sequence[RawSource], reader: PageReader) -> None:
        """Registered sales materials without a method use for their listed revision — attached
        before SK-1, or by a person — are detected too, once per run (Spec §3.1); pages this run
        already read are not read again, and unreadable ones are tried again next run."""
        if self.registry.contract != V2:
            return
        held = {
            m.knowledge_id: (m.parse_attempt, m.sha256, m.role)
            for product in self.registry.products.values()
            for m in product.materials
        }
        for source in sources:
            known = held.get(source.knowledge_id)
            if (
                known is None
                or known[:2] != (source.parse_attempt, source.sha256)
                or known[2] not in self.policy.brand_roles
                or self._settled(source)
            ):
                continue
            try:
                pages = self.pages.get(source.knowledge_id) or material_pages(
                    reader, self.registry.space_id, source
                )
            except SourcePagesError:
                continue
            hits = self._detect(source, pages)
            if hits is not None:
                self._add(source, hits)

    def _settled(self, source: RawSource) -> bool:
        """Already recorded for this revision, or the material no longer takes part."""
        ended = {
            d.knowledge_id for d in self.registry.decisions if d.attribution.outcome in _ENDED
        }
        triple = (source.knowledge_id, source.parse_attempt, source.sha256)
        return source.knowledge_id in ended or any(
            u.triple == triple for u in self.registry.method_uses
        )

    def _detect(self, source: RawSource, pages: Sequence[PageText]) -> MethodHits | None:
        triple = (source.knowledge_id, source.parse_attempt, source.sha256)
        if triple not in self._hits:
            try:
                self._hits[triple] = detect(pages, self.taxonomy)
            except ValueError:  # pages the segmentation refuses: no method use, fail closed
                self._hits[triple] = None
        return self._hits[triple]

    def conclude(self, source: RawSource, attribution: Attribution) -> Attribution:
        """A quarantine of a material with method blocks — found now, or recorded live for this
        very revision by an earlier run — is a METHOD_MATERIAL (Spec §3.3)."""
        if attribution.outcome != "QUARANTINE":
            return attribution
        triple = (source.knowledge_id, source.parse_attempt, source.sha256)
        live = any(u.triple == triple and u.state in LIVE for u in self.registry.method_uses)
        eligible = self.registry.contract == V2 and self._eligible(source, attribution)
        if eligible and (live or self.hits(source, attribution) is not None):
            update = {"outcome": "METHOD_MATERIAL", "reason": "method_material"}
            return Attribution.model_validate(attribution.model_dump() | update)
        return attribution

    def record(self, source: RawSource, attribution: Attribution) -> bool:
        """Record, in place, the material's method use; True when a record was added."""
        hits = self.hits(source, attribution)
        if hits is None:
            return False
        self._add(source, hits)
        return True

    def _add(self, source: RawSource, hits: MethodHits) -> None:
        """Every label the blocks hit is the machine's; with none, a person chooses (§3.2)."""
        use = MethodUse(
            knowledge_id=source.knowledge_id,
            parse_attempt=source.parse_attempt,
            sha256=source.sha256,
            file_name=source.file_name,
            block_scheme=BLOCK_SCHEME,
            block_ids=hits.block_ids,
            signals=hits.signals,
            label_hits=hits.label_hits,
            taxonomy_version=hits.taxonomy_version,
            evidence_digest=hits.evidence_digest,
            state="active" if hits.labels else "awaiting_scope",
            categories=hits.labels,
            decided_by="machine" if hits.labels else None,
        )
        uses = [*self.registry.method_uses, use]
        check_method_uses(uses)  # one record per revision, one live record per material
        self.registry.method_uses = uses

    def _eligible(self, source: RawSource, attribution: Attribution) -> bool:
        """Sales and training materials, and Office files of no recognised role: where S11c and
        PV-3 look for brands. Terms, brochures and rate tables never are (Spec §3.1)."""
        if attribution.outcome not in _JUDGED:
            return False
        if attribution.role in self.policy.brand_roles:
            return True
        extension = PurePosixPath(source.file_name).suffix.casefold()
        office = {e.casefold() for e in self.policy.brand_extensions}
        return attribution.role is None and extension in office

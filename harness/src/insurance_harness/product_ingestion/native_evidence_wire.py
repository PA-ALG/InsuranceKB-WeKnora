"""Protocol-independent exact evidence-ref binding; mutates only a private copy."""

from typing import Any


def bind_evidence_refs(expanded: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> None:
    for kind in ("definitions", "pages"):
        for row in expanded[kind]:
            if "evidence" in row:
                raise ValueError("native admission wire must select segment refs only")
            segments = row["content_provenance"]["segments"]
            selected: set[str] = set()
            for segment in segments:
                refs = segment["evidence_refs"]
                if (
                    not isinstance(refs, list)
                    or any(not isinstance(r, str) for r in refs)
                    or len(refs) != len(set(refs))
                    or not set(refs) <= catalog.keys()
                    or refs != [r for r in catalog if r in refs]
                    or "evidence_indexes" in segment
                ):
                    raise ValueError("native admission wire invalid evidence refs")
                if bool(refs) != (segment["origin"] == "SOURCE_SUPPORTED"):
                    raise ValueError("native admission wire origin mismatch")
                selected.update(refs)
            refs = [ref for ref in catalog if ref in selected]
            row["evidence"] = [catalog[ref] for ref in refs]
            for segment in segments:
                segment["evidence_indexes"] = [refs.index(r) for r in segment.pop("evidence_refs")]

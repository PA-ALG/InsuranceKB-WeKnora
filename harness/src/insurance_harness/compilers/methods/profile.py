"""The method presentation profile (SK-3 Spec §1, §2.2).

The platform knows method knowledge only from published data: a profile that serves the cards'
entity type whatever its labels, declares knowledge_class "method" and carries the copy readers
give methods. It is generated from the method cards, so its titles are the cards' titles, and it
travels with the method members that need it (compile.py).
"""

import hashlib
import json

from insurance_harness.bundle.canonical import member_digest
from insurance_harness.bundle.client import Release
from insurance_harness.catalog.method_cards import MethodCards
from insurance_harness.contracts.knowledge import PresentationProfile

SECTION = "method"


def method_profile(cards: MethodCards) -> PresentationProfile:
    shown = cards.presentation
    content = {
        "profile_id": cards.entity_type,
        "profile_version": cards.version,
        "profile_sha256": "0" * 64,
        "schema_pack_id": cards.review_pack,
        "display_name": shown.display_name,
        "sections": [
            {
                "section_key": SECTION,
                "display_name": shown.display_name,
                "fields": [
                    {
                        "field_key": card.predicate,
                        "short_title": card.title,
                        "description": card.definition,
                    }
                    for card in cards.cards
                ],
            }
        ],
        "entity_types": [cards.entity_type],
        "knowledge_class": "method",
        "reading_note": shown.reading_note,
        "notices": dict(shown.notices),
    }
    draft = PresentationProfile.model_validate(content)
    canonical = json.dumps(
        draft.model_dump(mode="json", exclude={"profile_sha256"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    content["profile_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return PresentationProfile.model_validate(content)


def profile_needed(profile: PresentationProfile, active: Release | None) -> bool:
    """Whether a candidate must carry the profile: the Active release lacks this exact one."""
    slug = f"presentation/{profile.profile_id}"
    digest = member_digest(profile.model_dump(mode="json"))
    live = {m.logical_slug: m.member_digest for m in active.members} if active else {}
    return live.get(slug) != digest

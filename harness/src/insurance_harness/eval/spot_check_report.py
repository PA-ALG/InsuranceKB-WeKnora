"""Count spot-check verdicts per pack and advise on the review policy (RV4 Spec §2.3).

usage: python -m insurance_harness.eval.spot_check_report --space S [--release R] [--submit]
       [--policy FILE] [--out FILE]

Reads the Space's samples and their latest verdicts with the platform API key
(HARNESS_WEKNORA_BASE_URL / HARNESS_WEKNORA_API_KEY). A sample's pack is its stratum before "/".
Per pack: samples, decided, correct, incomplete, wrong; precision = (correct + incomplete) /
decided, since an incomplete value is not a wrong one (S2c); and its 95% Wilson lower bound. Once
at least the pack's `minimum` samples are decided, a lower bound under its `target` advises
"raise_threshold_or_revoke", otherwise "ok"; fewer decided samples give "insufficient". The
advice is never applied: people decide, and the review policy changes by version. Wrong items form
the correction list (slug, release, reviewer, note), written to --out with the counts.

--submit --release R samples release R against its own base release and submits the picks; the
platform keeps samples it already has, so this is safe to repeat after a failed publish-time
submission.

Exit 0 with one summary line; exit 2 with one line {"stopped": <code>}, never a path or a key.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, NoReturn

from insurance_harness.bundle.client import PlatformClient, PlatformError, Sample
from insurance_harness.catalog.spot_check import (
    SpotCheckPolicy,
    SpotCheckPolicyError,
    load_spot_check_policy,
)
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV
from insurance_harness.review.spot_check import sample

Z_95 = 1.959963984540054
SAMPLES_PER_CALL = 500  # the platform's batch limit


class _Stop(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _Stop("INVALID_ARGUMENTS")


def wilson_lower_bound(successes: int, total: int, z: float = Z_95) -> float:
    if total == 0:
        return 0.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - margin) / denominator


def _pack_counts(samples: list[Sample], policy: SpotCheckPolicy) -> dict[str, dict[str, Any]]:
    by_pack: dict[str, list[Sample]] = {}
    for item in samples:
        by_pack.setdefault(item.stratum.split("/", 1)[0], []).append(item)
    packs: dict[str, dict[str, Any]] = {}
    for pack, items in sorted(by_pack.items()):
        outcomes = Counter(item.verdict.outcome for item in items if item.verdict)
        decided = sum(outcomes.values())
        good = outcomes["correct"] + outcomes["incomplete"]
        rule = policy.for_pack(pack)
        lower = wilson_lower_bound(good, decided)
        if decided == 0 or decided < rule.minimum:
            advice = "insufficient"
        else:
            advice = "raise_threshold_or_revoke" if lower < rule.target else "ok"
        packs[pack] = {
            "samples": len(items),
            "decided": decided,
            "correct": outcomes["correct"],
            "incomplete": outcomes["incomplete"],
            "wrong": outcomes["wrong"],
            "precision": good / decided if decided else None,
            "lower_bound": round(lower, 4) if decided else None,
            "target": rule.target,
            "advice": advice,
        }
    return packs


def _corrections(samples: list[Sample]) -> list[dict[str, str]]:
    return [
        {
            "slug": item.logical_slug,
            "release_id": item.release_id,
            "reviewer": item.verdict.reviewer,
            "note": item.verdict.note,
        }
        for item in samples
        if item.verdict and item.verdict.outcome == "wrong"
    ]


def _submit(client: PlatformClient, space: str, release_id: str, policy: SpotCheckPolicy) -> int:
    released = client.release(space, release_id)
    base = client.release(space, released.base_release_id) if released.base_release_id else None
    # Sample only the releases asked for: a sample drawn from another version would be bound to
    # this one, and a wrong base would hide what this release changed.
    if released.id != release_id or (base is not None and base.id != released.base_release_id):
        raise _Stop("RELEASE_MISMATCH")
    picks = [(pick.slug, pick.stratum) for pick in sample(released, base, policy)]
    submitted = 0
    for start in range(0, len(picks), SAMPLES_PER_CALL):
        batch = picks[start : start + SAMPLES_PER_CALL]
        submitted += len(client.submit_samples(space, release_id, batch))
    return submitted


def _replace(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument("--space", required=True)
        parser.add_argument("--release")
        parser.add_argument("--submit", action="store_true")
        parser.add_argument("--policy", type=Path)
        parser.add_argument("--out", type=Path)
        args = parser.parse_args(argv)
        if args.submit and not args.release:
            raise _Stop("INVALID_ARGUMENTS")
        policy = load_spot_check_policy(args.policy)
        base_url, api_key = os.environ.get(BASE_URL_ENV), os.environ.get(API_KEY_ENV)
        if not base_url or not api_key:
            raise _Stop("PLATFORM_UNCONFIGURED")
        client = PlatformClient(base_url, api_key)
        summary: dict[str, Any] = {}
        if args.submit:
            summary["submitted"] = _submit(client, args.space, args.release, policy)
        samples = client.samples(args.space, release_id=args.release)
        packs, corrections = _pack_counts(samples, policy), _corrections(samples)
        summary = {"packs": packs, "corrections": len(corrections), **summary}
        if args.out is not None:
            report = {"packs": packs, "corrections": corrections}
            _replace(args.out, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (_Stop, SpotCheckPolicyError, PlatformError) as error:
        print(json.dumps({"stopped": error.code}))
        return 2
    except OSError:
        print(json.dumps({"stopped": "OUT_UNWRITABLE"}))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

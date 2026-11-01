"""SK-1 acceptance (written by Claude): method questions are pushed in batches the platform takes.

Spec docs/design/slices/SK-1-方法用途登记与方法材料归属.md §4.1, §7 item 6 (r4; Codex review R2).
The platform takes at most 200 items and 512 KiB of body per submission; method questions are split
by both limits, as product questions are, each batch's items matched to its own questions. A batch
that fails ends the command with a code but keeps what earlier batches settled, and a rerun asks
nothing twice. Through the real `uploads.main(["confirm", ...])` with an HTTP fake. Texts are
invented.
"""

from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.client import (
    MAX_CONFIRMATION_BYTES,
    MAX_CONFIRMATIONS,
    confirmation_body,
)
from insurance_harness.ingest.method_confirmations import SUBJECT_PREFIX, method_question
from insurance_harness.ingest.registry import ProductRegistry, load_registry, save_registry
from insurance_harness.ingest.uploads import main
from tests.ingest.confirmation_platform import PREFIX, FakePlatform
from tests.ingest.method_helpers import v2
from tests.ingest.test_method_confirmations import NO_LABEL
from tests.ingest.test_method_uses import judged, only_use


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", "http://weknora.test")
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")


class CountingPlatform(FakePlatform):
    """The fake platform, also recording each submission's body size; one may be refused."""

    def __init__(self) -> None:
        super().__init__()
        self.bodies: list[int] = []
        self.refuse_submission: int | None = None  # the n-th submission (1-based) gets a 503

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == PREFIX:
            self.bodies.append(len(request.content))
            if self.refuse_submission == len(self.bodies):
                return httpx.Response(503, json={"success": False, "code": "SERVICE_UNAVAILABLE"})
        return super().handle(request)


def waiting(count: int, name: str = "家庭保障销售方法课程") -> ProductRegistry:
    """`count` method materials without any label: each one is asked."""
    decks = {
        f"k-{n:03d}": (f"{name}{n:03d}.pptx", NO_LABEL, f"{n + 1:064x}") for n in range(count)
    }
    return judged(v2(), decks)


def confirm(path: Path, platform: FakePlatform) -> int:
    return main(["confirm", "--registry", str(path)], transport=platform.transport())


def method_items(platform: FakePlatform) -> list[str]:
    return [i for i, item in platform.items.items() if item["subject"].startswith(SUBJECT_PREFIX)]


def test_more_than_200_questions_go_in_several_batches(tmp_path: Path, environment: None) -> None:
    path, platform = tmp_path / "registry.json", CountingPlatform()
    save_registry(waiting(MAX_CONFIRMATIONS + 1), path)
    assert confirm(path, platform) == 0
    assert len(method_items(platform)) == MAX_CONFIRMATIONS + 1
    assert len(platform.bodies) == 2


def test_large_questions_are_split_by_body_size(tmp_path: Path, environment: None) -> None:
    long_name = "家庭保障与客户经营销售方法课程讲义" * 9  # a long file name: a large question
    one = waiting(1, long_name)
    size = len(confirmation_body([method_question(only_use(one, "k-000"))]))
    count = MAX_CONFIRMATION_BYTES // size + 2  # more than one body holds, fewer than 200 items
    assert count < MAX_CONFIRMATIONS
    path, platform = tmp_path / "registry.json", CountingPlatform()
    save_registry(waiting(count, long_name), path)
    assert confirm(path, platform) == 0
    assert len(method_items(platform)) == count
    assert len(platform.bodies) == 2
    assert max(platform.bodies) <= MAX_CONFIRMATION_BYTES
    assert max(platform.bodies) > MAX_CONFIRMATION_BYTES - 2 * size  # the first batch is full


def test_a_failed_batch_keeps_what_earlier_batches_settled_and_a_rerun_repeats_nothing(
    tmp_path: Path, environment: None
) -> None:
    path, platform = tmp_path / "registry.json", CountingPlatform()
    save_registry(waiting(MAX_CONFIRMATIONS + 1), path)
    assert confirm(path, platform) == 0
    first = next(i for i in method_items(platform) if platform.items[i]["subject"].endswith("000"))
    platform.answer(first, "add:medical_insurance")  # a question of the first batch
    platform.refuse_submission = len(platform.bodies) + 2  # this run's second batch fails
    assert confirm(path, platform) == 1
    use = only_use(load_registry(path), "k-000")
    assert (use.state, use.decided_by) == ("active", "person")
    assert use.categories == ("medical_insurance",)
    platform.refuse_submission = None
    assert confirm(path, platform) == 0
    assert len(method_items(platform)) == MAX_CONFIRMATIONS + 2  # plus k-000's next step only

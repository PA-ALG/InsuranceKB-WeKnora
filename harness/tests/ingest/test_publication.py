"""S5b-4b acceptance (protected, written by Claude): one run compiles what changed, scores what was
recompiled and publishes what was not published yet, within per-run send caps.

Spec docs/design/slices/S5b-4b-登记表产品的编译发布编排.md §3–§6. The compile, review and publish
commands are replaced by fakes that record their arguments and write what the real ones write;
the platform's Active release is a fake too.
"""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from insurance_harness.bundle.client import PlatformClient
from insurance_harness.compilers.schema_fields import prompt, publish, publish_changes
from insurance_harness.compilers.schema_fields.cards import cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval import compile_run, review_run
from insurance_harness.ingest.publication import PublicationReport, plan, run_publication
from insurance_harness.ingest.registry import ProductRegistry, RegistryError, save_registry
from insurance_harness.ingest.uploads import main
from tests.ingest.upload_helpers import SPACE, entry, registry

BASE = "http://weknora.test"


def materials_of(current: ProductRegistry, product: str) -> dict[str, str]:
    return {  # identity -> recorded role: a current output carries both (S5b-6)
        f"{m.knowledge_id}:{m.parse_attempt}:{m.sha256}": m.role
        for m in current.products[product].materials
    }


def write_output(
    root: Path,
    current: ProductRegistry,
    product: str,
    *,
    materials: list[str] | None = None,
    version: str | None = None,
    pack: str | None = None,
) -> None:
    output = CompileOutput(
        pack_id=pack or current.products[product].schema_pack_id,
        entity_id=product,
        model="deepseek-flash",
        cards_version=version or cards_version(), value_protocol=prompt.VALUE_PROTOCOL_VERSION,
        materials=sorted(materials_of(current, product)) if materials is None else materials,
        material_roles=materials_of(current, product) if materials is None else None)
    (root / product).mkdir(parents=True, exist_ok=True)
    (root / product / "output.json").write_text(output.model_dump_json(), encoding="utf-8")


def digest(root: Path, product: str) -> str:
    return hashlib.sha256((root / product / "output.json").read_bytes()).hexdigest()


def spend(root: Path, sends: int) -> None:
    """Record sends the way models.durable does: a baseline line, then one line per reservation."""
    root.mkdir(parents=True, exist_ok=True)
    budget = root / "budget.jsonl"
    if not budget.exists():
        budget.write_text(json.dumps({"baseline": 0}) + "\n", encoding="utf-8")
    with budget.open("a", encoding="utf-8") as stream:
        stream.write('{"reserved":1}\n' * sends)


def option(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def values(argv: list[str], name: str) -> list[str]:
    start = argv.index(name) + 1
    end = next((i for i in range(start, len(argv)) if argv[i].startswith("--")), len(argv))
    return argv[start:end]


class Commands:
    """Fake compile, review and publish commands."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, current: ProductRegistry) -> None:
        self.current = current
        self.calls: list[tuple[str, list[str]]] = []
        self.compile_stop: str | None = None
        self.stop_after: int = 0  # products a stopping compile still writes first
        self.review_stop: str | None = None
        self.publish_failures: dict[str, str] = {}
        self.routes: dict[str, str] = {}
        self.unchanged: set[str] = set()
        monkeypatch.setattr(compile_run, "main", self.compile)
        monkeypatch.setattr(review_run, "main", self.review)
        monkeypatch.setattr(publish, "main", lambda argv: self.publish("first", argv))
        monkeypatch.setattr(publish_changes, "main", lambda argv: self.publish("changes", argv))

    def named(self, kind: str) -> list[list[str]]:
        return [argv for name, argv in self.calls if name == kind]

    def compile(self, argv: list[str]) -> int:
        self.calls.append(("compile", argv))
        root, products = Path(option(argv, "--run-root")), values(argv, "--products")
        if self.compile_stop:
            for product in products[: self.stop_after]:
                write_output(root, self.current, product)
            print(json.dumps({"stopped": self.compile_stop, "products": []}))
            return 2
        spend(root, 3 * len(products))
        for product in products:
            write_output(root, self.current, product)
        runs = [
            {
                "product_id": p,
                "display_name": p,
                "pack_id": "pack",
                "reused": False,
                "calls": 3,
                "fields": 0,
            }
            for p in products
        ]
        print(json.dumps({"products": runs, "sent": 0}))
        return 0

    def review(self, argv: list[str]) -> int:
        self.calls.append(("review", argv))
        root, products = Path(option(argv, "--run-root")), values(argv, "--products")
        if self.review_stop:
            print(json.dumps({"stopped": self.review_stop}))
            return 2
        spend(root, len(products))
        for product in products:
            (root / product).mkdir(parents=True, exist_ok=True)
            scores = {"reviewer": "flash@test", "reviewed_at": "2026-10-25T10:00:00Z", "scores": {}}
            (root / product / "scores.json").write_text(json.dumps(scores), encoding="utf-8")
        # The real summary lists {product, scored, reused} objects (review R1).
        scored = [{"product": p, "scored": 1, "reused": False} for p in products]
        print(json.dumps({"products": scored}))
        return 0

    def publish(self, kind: str, argv: list[str]) -> int:
        self.calls.append((kind, argv))
        product = option(argv, "--product")
        if product in self.publish_failures:
            print(json.dumps({"stopped": self.publish_failures[product]}))
            return 2
        if kind == "changes" and "--dry-run" in argv:
            outcome = {"product": product, "dry_run": True, "no_changes": product in self.unchanged}
            print(json.dumps(outcome))
            return 0
        if kind == "changes" and product in self.unchanged:
            print(json.dumps({"product": product, "no_changes": True}))
            return 0
        print(json.dumps({"product": product, "review": self.routes.get(product, "human")}))
        return 0


class Active:
    """The platform's Active release, holding Claims of the given products."""

    def __init__(self, products: set[str]) -> None:
        self.products = products
        self.requests: list[tuple[str, str]] = []

    def client(self) -> PlatformClient:
        return PlatformClient(BASE, "key", transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        assert (request.method, request.url.path) == (
            "GET",
            f"/api/v1/enterprise/spaces/{SPACE}/releases/active",
        )
        if not self.products:
            return httpx.Response(404, json={"success": False, "code": "RELEASE_NOT_FOUND"})
        members = [
            {
                "kind": "claim",
                "logical_slug": f"{p}/waiting_period",
                "member_digest": "d" * 64,
                "payload": {"subject_ref": p},
                "evidence_refs": [],
                "access_scope": "space",
            }
            for p in sorted(self.products)
        ]
        return httpx.Response(
            200, json={"success": True, "data": {"id": "rel-1", "epoch": 1, "members": members}}
        )


def two_products() -> ProductRegistry:
    return registry(p1818=entry("1818", "terms", "brochure"), p1828=entry("1828", "terms"))


def stored(tmp_path: Path, current: ProductRegistry) -> Path:
    path = tmp_path / "registry.json"
    save_registry(current, path)
    return path


def published(run: Path, name: str = "published.json") -> dict[str, str]:
    path = run / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def record_published(run: Path, entries: dict[str, str]) -> None:
    run.mkdir(parents=True, exist_ok=True)
    (run / "published.json").write_text(json.dumps(entries), encoding="utf-8")


def publish_run(
    tmp_path: Path,
    current: ProductRegistry,
    active: Active,
    *,
    compile_max_sent: int = 30,
    review_max_sent: int = 10,
    dry_run: bool = False,
    products: list[str] | None = None,
    seed_from: tuple[Path, ...] | list[Path] = (),
) -> PublicationReport:
    return run_publication(
        stored(tmp_path, current),
        tmp_path / "run",
        client=active.client(),
        stage_config=tmp_path / "stages.json",
        compile_max_sent=compile_max_sent,
        review_max_sent=review_max_sent,
        dry_run=dry_run,
        products=products,
        seed_from=seed_from,
    )


# 1. Plan ----------------------------------------------------------------------------------------


def test_the_plan_compiles_what_changed_and_publishes_what_is_not_published(tmp_path: Path) -> None:
    current = registry(
        p1814=entry("1814", "terms"),
        p1818=entry("1818", "terms", "brochure"),
        p1826=entry("1826", "terms"),
        p1828=entry("1828", "terms"),
        p1830=entry("1830", "terms"),
    )
    run = tmp_path / "run"
    compiled = run / "compile"
    write_output(compiled, current, "1818", materials=["k-old:1:" + "0" * 64])
    write_output(compiled, current, "1826", version="draft-older")
    write_output(compiled, current, "1828")
    write_output(compiled, current, "1830")
    record_published(run, {"1828": digest(compiled, "1828"), "1830": "f" * 64})
    result = plan(current, run)
    assert result.compile == ["1814", "1818", "1826"]
    assert result.publish == ["1814", "1818", "1826", "1830"]
    limited = plan(current, run, products=["1828", "1830"])
    assert (limited.compile, limited.publish) == ([], ["1830"])


# 2. Compile -------------------------------------------------------------------------------------


def test_only_changed_products_are_compiled_within_the_per_run_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    run = tmp_path / "run"
    write_output(run / "compile", current, "1828")
    record_published(run, {"1828": digest(run / "compile", "1828")})
    spend(run / "compile", 8)
    commands = Commands(monkeypatch, current)
    report = publish_run(tmp_path, current, Active({"1828"}), compile_max_sent=30)
    [argv] = commands.named("compile")
    assert values(argv, "--products") == ["1818"]
    assert (option(argv, "--max-sent"), option(argv, "--stage")) == ("38", "schema_fields")
    assert (option(argv, "--registry"), option(argv, "--run-root")) == (
        str(tmp_path / "registry.json"),
        str(run / "compile"),
    )
    assert (report.compiled, report.compile_sent) == (["1818"], 3)


def test_a_stopped_compile_ends_the_run_before_scoring_or_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = Commands(monkeypatch, two_products())
    commands.compile_stop = "BUDGET_EXCEEDED"
    report = publish_run(tmp_path, two_products(), Active(set()))
    assert report.stopped == "BUDGET_EXCEEDED"
    assert [name for name, _ in commands.calls] == ["compile"]
    assert published(tmp_path / "run") == {}


# 3. Scoring -------------------------------------------------------------------------------------


def test_products_without_current_scores_are_scored_and_a_failed_scoring_still_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    run = tmp_path / "run"
    write_output(run / "compile", current, "1828")  # current but never scored: score it too (R1)
    commands = Commands(monkeypatch, current)
    commands.review_stop = "BUDGET_EXCEEDED"
    report = publish_run(tmp_path, current, Active(set()), review_max_sent=10)
    [argv] = commands.named("review")
    assert values(argv, "--products") == ["1818", "1828"]
    assert (option(argv, "--compile-root"), option(argv, "--run-root")) == (
        str(run / "compile"),
        str(run / "review"),
    )
    assert (option(argv, "--stage"), option(argv, "--max-sent")) == ("review", "10")
    assert report.review_stopped == "BUDGET_EXCEEDED"
    first = commands.named("first")
    assert [option(a, "--product") for a in first] == ["1818", "1828"]
    assert all("--scores" not in a for a in first)


# 4. Publishing ----------------------------------------------------------------------------------


def test_first_or_change_publishing_follows_active_and_success_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    run = tmp_path / "run"
    commands = Commands(monkeypatch, current)
    commands.routes = {"1818": "machine"}
    report = publish_run(tmp_path, current, Active({"1828"}))
    [dry] = [a for a in commands.named("changes") if "--dry-run" in a]
    assert option(dry, "--product") == "1828" and "--scores" not in dry
    [first] = commands.named("first")
    [changes] = [a for a in commands.named("changes") if "--dry-run" not in a]
    assert (option(first, "--product"), option(changes, "--product")) == ("1818", "1828")
    for argv, product in ((first, "1818"), (changes, "1828")):
        assert "--route" in argv
        assert option(argv, "--registry") == str(tmp_path / "registry.json")
        assert option(argv, "--run-root") == str(run / "compile")
        assert option(argv, "--scores") == str(run / "review" / product / "scores.json")
    assert report.routes == {"1818": "machine", "1828": "human"}
    assert published(run) == {p: digest(run / "compile", p) for p in ("1818", "1828")}
    assert published(run, "scored.json") == published(run)


def test_a_failed_publish_does_not_stop_the_others_and_is_retried_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    run = tmp_path / "run"
    commands = Commands(monkeypatch, current)
    commands.publish_failures = {"1818": "SERVICE_UNAVAILABLE"}
    report = publish_run(tmp_path, current, Active(set()))
    assert report.failed == {"1818": "SERVICE_UNAVAILABLE"}
    assert list(published(run)) == ["1828"]
    commands.publish_failures = {}
    commands.calls.clear()
    again = publish_run(tmp_path, current, Active({"1828"}))
    assert [name for name, _ in commands.calls] == ["first"]
    assert again.routes == {"1818": "human"}
    assert sorted(published(run)) == ["1818", "1828"]


def test_unchanged_content_is_recorded_as_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = two_products()
    run = tmp_path / "run"
    for product in ("1818", "1828"):
        write_output(run / "compile", current, product)
    commands = Commands(monkeypatch, current)
    commands.unchanged = {"1818", "1828"}
    report = publish_run(tmp_path, current, Active({"1818", "1828"}))
    assert commands.named("compile") == [] and commands.named("review") == []
    assert commands.named("first") == [] and len(commands.named("changes")) == 2
    assert all("--dry-run" in argv for argv in commands.named("changes"))
    assert report.routes == {"1818": "unchanged", "1828": "unchanged"}
    assert sorted(published(run)) == ["1818", "1828"]


# 5. Dry run -------------------------------------------------------------------------------------


def test_a_dry_run_only_plans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    current = two_products()
    run = tmp_path / "run"
    write_output(run / "compile", current, "1828")
    commands = Commands(monkeypatch, current)
    active = Active(set())
    dry = publish_run(tmp_path, current, active, dry_run=True)
    assert (commands.calls, active.requests, published(run)) == ([], [], {})
    assert (dry.planned_compile, dry.planned_publish) == (["1818"], ["1818", "1828"])
    assert (dry.compiled, dry.routes) == ([], {})
    real = publish_run(tmp_path, current, active)
    assert (real.planned_compile, real.planned_publish) == (
        dry.planned_compile,
        dry.planned_publish,
    )


# 6. Seeding -------------------------------------------------------------------------------------


def test_matching_earlier_outputs_are_seeded_and_others_are_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = registry(
        p1818=entry("1818", "terms", "brochure"),
        p1826=entry("1826", "terms"),
        p1828=entry("1828", "terms"),
    )
    seed = tmp_path / "earlier"
    write_output(seed, current, "1818")
    write_output(seed, current, "1826", materials=["k-old:1:" + "0" * 64])
    write_output(seed, current, "1828", pack="another_pack")
    commands = Commands(monkeypatch, current)
    dry = publish_run(tmp_path, current, Active(set()), dry_run=True, seed_from=[seed])
    assert dry.planned_compile == ["1826", "1828"]
    assert not (tmp_path / "run" / "compile" / "1818").exists()
    publish_run(tmp_path, current, Active(set()), seed_from=[seed])
    [argv] = commands.named("compile")
    assert values(argv, "--products") == ["1826", "1828"]
    assert (tmp_path / "run" / "compile" / "1818" / "output.json").read_bytes() == (
        seed / "1818" / "output.json"
    ).read_bytes()


# 7. Report and command --------------------------------------------------------------------------


def test_an_unknown_product_stops_before_any_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = Commands(monkeypatch, two_products())
    with pytest.raises(RegistryError) as failure:
        publish_run(tmp_path, two_products(), Active(set()), products=["9999"])
    assert failure.value.code == "PRODUCT_UNKNOWN"
    assert commands.calls == []


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_WEKNORA_BASE_URL", BASE)
    monkeypatch.setenv("HARNESS_WEKNORA_API_KEY", "key")


def command(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "publish",
        "--registry",
        str(tmp_path / "registry.json"),
        "--run-root",
        str(tmp_path / "run"),
        "--stage-config",
        str(tmp_path / "stages.json"),
        *extra,
    ]


def test_the_command_reports_without_paths_and_keeps_the_registry_lock(
    tmp_path: Path,
    environment: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    current = two_products()
    stored(tmp_path, current)
    commands = Commands(monkeypatch, current)
    active = Active(set())
    assert main(command(tmp_path), transport=httpx.MockTransport(active.handle)) == 0
    output = capsys.readouterr().out.strip().splitlines()[-1]
    report = json.loads(output)
    assert report["compiled"] == ["1818", "1828"]
    assert str(tmp_path) not in output
    lock = tmp_path / "registry.json.lock"
    lock.write_text("")
    commands.calls.clear()
    assert main(command(tmp_path), transport=httpx.MockTransport(active.handle)) == 3
    assert "REGISTRY_BUSY" in capsys.readouterr().err
    assert commands.calls == []
    lock.unlink()
    commands.compile_stop = "BUDGET_EXCEEDED"
    record_published(tmp_path / "run", {})
    (tmp_path / "run" / "compile" / "1818" / "output.json").unlink()
    assert main(command(tmp_path), transport=httpx.MockTransport(active.handle)) == 1
    captured = capsys.readouterr()
    assert "BUDGET_EXCEEDED" in captured.out + captured.err


def test_the_command_needs_its_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HARNESS_WEKNORA_BASE_URL", raising=False)
    monkeypatch.delenv("HARNESS_WEKNORA_API_KEY", raising=False)
    stored(tmp_path, two_products())
    commands = Commands(monkeypatch, two_products())
    assert main(command(tmp_path)) == 2
    assert "CONFIGURATION_MISSING" in capsys.readouterr().err
    assert commands.calls == []

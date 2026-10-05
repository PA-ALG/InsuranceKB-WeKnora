"""Export the public contracts, or check their byte-for-byte consistency."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from pydantic import BaseModel

from insurance_harness.contracts.bundle import (
    CONTRACT_VERSION,
    BundleMember,
    CandidateBundle,
    ReviewPlan,
)
from insurance_harness.contracts.compile import (
    CompileResult,
    CompileTask,
    GapTask,
    PageText,
    ReviewItem,
)
from insurance_harness.contracts.knowledge import (
    Claim,
    Entity,
    Evidence,
    ExpertRevision,
    Locator,
    QAItem,
    Relation,
    SchemaSnapshot,
)

SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
CONTRACT_URI = "https://pa-alg.github.io/InsuranceKB-WeKnora/contracts/"
DEFAULT_DESTINATION = Path(__file__).resolve().parents[4] / "contracts"
MODELS: tuple[type[BaseModel], ...] = (
    Evidence, Locator, Entity, Claim, Relation, QAItem, ExpertRevision, SchemaSnapshot,
    PageText, CompileTask, CompileResult, GapTask, ReviewItem,
    CandidateBundle, BundleMember, ReviewPlan,
)
README = f'''# Generated contracts

contract_version: "{CONTRACT_VERSION}"

These JSON Schemas are generated from `insurance_harness.contracts`.
From `harness/`, run `uv run python -m insurance_harness.contracts.export`
to regenerate, or append `--check` to check schema bytes without writing.
Do not edit the generated schemas. G9 reports every changed, missing or extra
schema as a violation, with no per-file baseline allowance.

Pydantic validators also enforce cross-field rules (locator required fields,
offset ordering and Claim states). JSON Schema provides structural validation;
consumers must additionally enforce platform and source-verification invariants.
'''


def schema_filename(model: type[BaseModel]) -> str:
    """Keep acronyms together: QAItem becomes qa_item, not q_a_item."""
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", model.__name__)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower() + ".schema.json"


def write_generated(path: Path, content: str) -> None:
    """Replace the directory entry without following an existing file symlink."""
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
        temporary_path = Path(out.name)
        try:
            out.write(content)
            out.close()
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)


def export(destination: Path) -> list[Path]:
    """Write deterministic schemas only beneath destination, sorted by name."""
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for model in sorted(MODELS, key=schema_filename):
        filename = schema_filename(model)
        schema = model.model_json_schema()
        schema["$schema"] = SCHEMA_URI
        schema["$id"] = CONTRACT_URI + filename
        path = destination / filename
        write_generated(
            path, json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
        paths.append(path)
    write_generated(destination / "README.md", README)
    return paths


def check(destination: Path) -> list[str]:
    """Report changed, missing and extra schemas without modifying destination."""
    with TemporaryDirectory(prefix="contract-export-") as temporary:
        expected = {path.name: path.read_bytes() for path in export(Path(temporary))}
        actual = {path.name: path for path in destination.glob("*.schema.json")}
        return sorted(
            name
            for name in expected.keys() | actual.keys()
            if name not in expected
            or name not in actual
            or not actual[name].is_file()
            or expected[name] != actual[name].read_bytes()
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check without writing any files")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    if args.check:
        drift = check(args.destination)
        for filename in drift:
            print(filename)
        return int(bool(drift))
    export(args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

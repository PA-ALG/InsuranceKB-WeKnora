"""WeKnora adoption tool contracts: shared target identities, manifests and check inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml

REPOSITORY = "https://github.com/Tencent/WeKnora.git"
TARGET_COMMIT = "f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7"
TARGET_TREE = "de9e8951de64824a2f654d8ff5ace37fe5672b23"
RELEASE_COMMIT = "c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb"
CAPABILITY_COMMIT = "80a5003cc99a427098afe184eee6601916d3d156"
MANIFEST = {
    "schema_version": 1,
    "repository": REPOSITORY,
    "commit": TARGET_COMMIT,
    "tree": TARGET_TREE,
    "release_ancestor": {"tag": "v0.7.1", "commit": RELEASE_COMMIT},
    "required_capability_commits": [CAPABILITY_COMMIT],
    "official_migration_head": 134,
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_CONTRACT = REPOSITORY_ROOT / "deploy" / "upstream" / "weknora-plugin-contract.yaml"


def _write_manifest(tmp_path: Path, value: object = MANIFEST) -> Path:
    path = tmp_path / "target.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _replace(value: dict[str, object], **changes: object) -> dict[str, object]:
    return {**value, **changes}


def _write_yaml(tmp_path: Path, name: str, value: object) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _contract_value() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        yaml.safe_load(PLUGIN_CONTRACT.read_text(encoding="utf-8")),
    )

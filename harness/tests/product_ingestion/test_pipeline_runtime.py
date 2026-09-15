from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr
from sqlalchemy import create_engine, event

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import ClaimedJob, JobState, JobStore
from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.product_ingestion.composition import compose_product_worker
from insurance_harness.product_ingestion.discovery import DISCOVERY_PROMPT, DISCOVERY_REVIEW_PROMPT
from insurance_harness.product_ingestion.models import (
    FieldOutcomeKind,
    ProductRunState,
    ProductScope,
)
from insurance_harness.product_ingestion.pipeline import (
    FIELD_PROMPT,
    IDENTITY_PROMPT,
    build_product_pipeline,
)
from insurance_harness.product_ingestion.platform import _canonical as _source_canonical
from insurance_harness.product_ingestion.progression import admit_uploads
from insurance_harness.product_ingestion.signing import canonical
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "harness/tests/fixtures/batch_concept_compile_830_g3"
CATALOG = ROOT / "docs/insurance-kb/evidence/830-g3/catalog/catalog.json"
PROFILE_CONFIRMATION = ROOT / "docs/insurance-kb/evidence/830-g3/profile-user-confirmation.json"
BASE_CANDIDATE = FIXTURES / "platform-incremental-candidate.json"
TITLE = "平安测试（2026）两全保险"
ISSUER = "中国平安人寿保险股份有限公司"
PRODUCT_CODE = "1818"
FILING = "平安人寿〔2026〕两全保险999号"
VERSION = "2026"
SOURCE_KEY = Ed25519PrivateKey.from_private_bytes(bytes([9]) * 32)
SCOPE = ProductScope(
    tenant_id="10003",
    space_id="a8751a40-83ce-55c8-a160-079b283483ca",
    raw_knowledge_base_id="b1f1764c-443d-46b8-98e3-d5aa5e55eb42",
    wiki_knowledge_base_id="8d5695de-f255-42d5-9a41-042ba86e97b9",
)
FILES = ("保险条款.pdf", "产品说明书.pdf", "费率表.pdf")
ROLES = ("terms", "brochure", "rate_table")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.model_dump(mode="json"),
    ).encode()


def _signed(kind: str, body: dict) -> dict:
    contract = f"g3-platform-{kind}-snapshot.830.v1"
    domain = f"weknora.{contract}"
    unsigned = json.loads(_json({**body, "contract": contract}))
    digest = _sha(contract.encode() + b"\0" + _source_canonical(unsigned))
    snapshot = {**unsigned, "snapshot_sha256": digest}
    signature = SOURCE_KEY.sign(domain.encode() + b"\0" + digest.encode())
    envelope = {
        "contract": f"g3-platform-signed-{kind}-snapshot.830.v1",
        "snapshot": snapshot,
        "authority": {
            "contract": "g3-platform-snapshot-authority.830.v1",
            "domain": domain,
            "key_id": "source-current",
            "payload_sha256": digest,
            "signature": base64.b64encode(signature).decode(),
        },
    }
    return json.loads(_json(envelope))


def _published_snapshot(candidate, *, release_id: str, activation_epoch: int) -> dict:
    request = candidate.request
    base = request.base_request
    versions = {row.entity_id: row.entity_version for row in request.entity_bindings}
    members = tuple(
        {
            "kind": row.kind,
            "logical_slug": row.member_id,
            "revision_id": candidate.candidate_hash,
            "member_digest": compiler._batch_sha256("batch-concept-member.830.g3.v1", row),
        }
        for row in candidate.page_manifest.members
    )
    body = {
        "scope": {
            "tenant_id": int(SCOPE.tenant_id),
            "space_id": SCOPE.space_id,
            "raw_kb_id": SCOPE.raw_knowledge_base_id,
            "wiki_kb_id": SCOPE.wiki_knowledge_base_id,
        },
        "release_id": release_id,
        "activation_epoch": activation_epoch,
        "preparation_id": "fixture-preparation-" + candidate.candidate_hash[:16],
        "candidate_sha256": candidate.candidate_hash,
        "manifest_digest": candidate.page_manifest.members_sha256,
        "published_projection_contract": "g3-platform-published-projection.830.v1",
        "published_projection": {
            "contract": "g3-platform-published-projection.830.v1",
            "origin_contract": "published-batch-read-projection.830.g3.v2",
            "parent": {
                "release_id": base.base_release_id,
                "activation_epoch": base.base_activation_epoch,
            },
            "sources": base.sources,
            "catalog": {
                "catalog_id": request.catalog.catalog_id,
                "catalog_version": request.catalog.catalog_version,
                "catalog_sha256": request.catalog.catalog_sha256,
            },
            "entity_bindings": request.entity_bindings,
            "entity_versions": versions,
            "definitions": candidate.compile_result.output.definitions,
            "fields": candidate.compile_result.output.fields,
            "pages": candidate.compile_result.output.pages,
            "page_members": candidate.page_manifest.members,
            "navigation_assignments": candidate.navigation_assignments,
            "candidate_hash": candidate.candidate_hash,
        },
        "members": members,
    }
    return _signed("base", body)


def _base_snapshot() -> tuple[dict, object]:
    candidate = compiler.validate_batch_candidate(BASE_CANDIDATE.read_bytes())
    return (
        _published_snapshot(
            candidate, release_id="release-five-product-fixture", activation_epoch=9
        ),
        candidate,
    )


def _source_snapshot(ordinal: int, *, conflicting: bool = False) -> dict:
    title = "平安冲突（2026）两全保险" if conflicting and ordinal == 1 else TITLE
    role_heading = ("保险条款", "产品说明书", "费率表")[ordinal]
    heading = f"《{title}》年交费率表" if ordinal == 2 else f"{title}{role_heading}"
    text = f"{heading}\n{ISSUER}\n产品代码：{PRODUCT_CODE}\n{FILING}\n版本：{VERSION}\n"
    raw_text = text.encode()
    file_sha = _sha(f"fixture-pdf-{ordinal}".encode())
    parser_sha = _sha(b"fixture-native-parser-v1")
    native = _json(
        {
            "source_sha256": file_sha,
            "markdown_sha256": _sha(raw_text),
            "parser_identity_sha256": parser_sha,
            "pages": [
                {
                    "page_number": 1,
                    "global_codepoint_start": 0,
                    "global_codepoint_end": len(text),
                    "page_text_sha256": _sha(raw_text),
                    "width_points": "595",
                    "height_points": "842",
                    "bboxes": [
                        {
                            "global_codepoint_start": index,
                            "global_codepoint_end": index + 1,
                            "bbox": [10_000 + index, 10_000, 10_001 + index, 20_000],
                        }
                        for index, char in enumerate(text)
                        if not char.isspace()
                    ],
                }
            ],
        }
    )
    knowledge_id = f"knowledge-new-{ordinal}"
    revision = _sha(f"revision-{ordinal}".encode())
    manifest = _sha(f"manifest-{ordinal}".encode())
    chunk_id = f"block-{ordinal}"
    body = {
        "scope": {
            "tenant_id": int(SCOPE.tenant_id),
            "space_id": SCOPE.space_id,
            "raw_kb_id": SCOPE.raw_knowledge_base_id,
            "wiki_kb_id": SCOPE.wiki_knowledge_base_id,
        },
        "receipt": {
            "contract": "knowledge-revision-source.v1",
            "knowledge_id": knowledge_id,
            "parse_attempt": 1,
            "revision_source_id": revision,
            "file_sha256": file_sha,
            "object_sha256": file_sha,
            "size": len(raw_text),
            "mime_type": "application/pdf",
            "page_count": 1,
            "manifest_algorithm": "weknora.chunk_manifest.v1",
            "manifest_digest": manifest,
            "chunk_count": 1,
            "binding_digest": _sha(f"binding-{ordinal}".encode()),
            "retention_state": "pinned",
        },
        "parser_identity_sha256": parser_sha,
        "native_capture_sha256": _sha(native),
        "markdown": text,
        "native": {
            "SchemaVersion": "fixture-native-v1",
            "SourceSHA256": file_sha,
            "RawSHA256": file_sha,
            "SanitizedSHA256": _sha(native),
            "SanitizedJSON": base64.b64encode(native).decode(),
        },
        "chunks": [
            {
                "id": chunk_id,
                "index": 0,
                "content": text,
                "content_sha256": _sha(raw_text),
            }
        ],
        "chunk_page_mappings": [
            {
                "chunk_id": chunk_id,
                "status": "EXACT_BLOCK",
                "source_page_number": 1,
                "block_global_start": 0,
                "block_global_end": len(text),
                "page_spans": [
                    {
                        "page_number": 1,
                        "block_codepoint_start": 0,
                        "block_codepoint_end": len(text),
                        "global_codepoint_start": 0,
                        "global_codepoint_end": len(text),
                    }
                ],
            }
        ],
    }
    return _signed("source", body)


def _trusted_files(tmp_path: Path, base_candidate) -> dict:
    policy = base_candidate.request.resolution_inputs.policy.model_dump(
        mode="json", exclude={"policy_sha256"}
    )
    policy["rules"][0]["material_roles"] = ["brochure", "rate_table", "terms"]
    policy["rules"][0]["provenance_kinds"] = ["user_supplied_document"]
    policy["policy_sha256"] = compiler._batch_sha256("batch-resolution-policy.830.g3.v1", policy)
    values = {
        "catalog": CATALOG.read_bytes(),
        "profile_confirmation": PROFILE_CONFIRMATION.read_bytes(),
        "resolution_policy": _json(policy),
    }
    result = {}
    for name, raw in values.items():
        path = tmp_path / f"{name}.json"
        path.write_bytes(raw)
        result[name] = {"path": str(path), "sha256": _sha(raw), "max_bytes": len(raw)}
    return result


def _settings(tmp_path: Path, base_candidate) -> ShellSettings:
    expires = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    runtime = {
        "contract": "product-ingestion-runtime.830.v1",
        "trusted_files": _trusted_files(tmp_path, base_candidate),
        "pump": {"page_size": 50, "event_limit": 100, "poll_interval_seconds": 0.01},
        "bindings": [
            {
                "scope": SCOPE.model_dump(mode="json"),
                "platform": {
                    "base_url": "http://platform.fixture",
                    "machine_key": "fixture-machine-secret",
                    "timeout_seconds": 5,
                    "max_response_bytes": 16 * 1024 * 1024,
                },
                "source_authorities": [
                    {
                        "key_id": "source-current",
                        "public_key_b64": base64.b64encode(
                            SOURCE_KEY.public_key().public_bytes_raw()
                        ).decode(),
                    }
                ],
                "model": {
                    "scope": SCOPE.model_dump(mode="json"),
                    "endpoint": "http://model.fixture/v1/chat/completions",
                    "api_key": "fixture-model-secret",
                    "model": "gemini-3.7-flash-medium",
                    "policy_version": "g3-user-gemini-gateway-v1",
                    "expires_at": expires,
                    "templates": [
                        {
                            "template_id": "identity-v1",
                            "role": "classify",
                            "purpose": "g3-batch-resolution",
                            "run_schema_version": "830-g3-v1",
                            "prompt_sha256": _sha(IDENTITY_PROMPT),
                            "max_context_bytes": 8 * 1024 * 1024,
                            "max_output_tokens": 8192,
                        },
                        {
                            "template_id": "field-v1",
                            "role": "extract",
                            "purpose": "g3-field-extraction",
                            "run_schema_version": "830-g3-v1",
                            "prompt_sha256": _sha(FIELD_PROMPT),
                            "max_context_bytes": 8 * 1024 * 1024,
                            "max_output_tokens": 8192,
                        },
                        *[
                            {
                                "template_id": template_id,
                                "role": role,
                                "purpose": purpose,
                                "run_schema_version": "830-g3-v1",
                                "prompt_sha256": _sha(prompt),
                                "max_context_bytes": 8 * 1024 * 1024,
                                "max_output_tokens": 8192,
                            }
                            for template_id, role, purpose, prompt in (
                                ("discovery-v1", "extract", "g3-open-discovery", DISCOVERY_PROMPT),
                                (
                                    "discovery-review-v1",
                                    "verify",
                                    "g3-open-discovery-review",
                                    DISCOVERY_REVIEW_PROMPT,
                                ),
                            )
                        ],
                    ],
                    "field_template_id": "field-v1",
                    "max_request_bytes": 12 * 1024 * 1024,
                    "max_response_bytes": 8 * 1024 * 1024,
                    "timeout_seconds": 5,
                },
                "automation": {
                    "scope": SCOPE.model_dump(mode="json"),
                    "mode": "ISOLATED_NOT_FOR_PRODUCTION",
                    "principal_id": "api_tenant:10003",
                    "api_key_id": 7,
                    "policy_id": "fixture-product-automation",
                    "policy_version": "1",
                    "policy_sha256": "a" * 64,
                    "capabilities": ["activate", "create-draft", "review"],
                    "expires_at": expires,
                    "decision_signer_key_id": "fixture-decision",
                    "decision_private_key_b64": base64.b64encode(bytes([1]) * 32).decode(),
                    "publish_signer_key_id": "fixture-publish",
                    "publish_private_key_b64": base64.b64encode(bytes([2]) * 32).decode(),
                },
            }
        ],
    }
    return ShellSettings(
        postgres_dsn=SecretStr("postgresql+psycopg://unused/test"),
        principal_space_ids=(SCOPE.space_id,),
        worker_id="fixture-worker",
        worker_space_ids=(SCOPE.space_id,),
        worker_local_concurrency=1,
        # The fixture uses SQLite, whose schema reflection and heartbeat writes
        # cannot overlap. Production PostgreSQL retains the normal short heartbeat.
        heartbeat_interval_seconds=500,
        lease_seconds=600,
        job_max_attempts=3,
        job_backoff_seconds=(0,),
        product_ingestion_enabled=True,
        product_ingestion_scopes_json=SecretStr(_json([SCOPE.model_dump(mode="json")]).decode()),
        product_ingestion_runtime_json=SecretStr(_json(runtime).decode()),
    )


class FixtureModel:
    def __init__(self):
        self.identity_requests: list[dict] = []
        self.field_requests: list[dict] = []
        self.discovery_requests: list[dict] = []
        self.discovery_review_requests: list[dict] = []
        self.fail_one_field = True

    @staticmethod
    def _identity(content: dict) -> dict:
        materials = []
        for material in content["materials"]:
            locator = material["blocks"][0]["evidence_locator_refs"][0]["locator_ref"]
            evidence = [
                {
                    "evidence_ref": ref,
                    "entity_ref": None if purpose == "material_role" else "entity",
                    "purpose": purpose,
                    "field_key": None,
                    "locator_ref": locator,
                }
                for ref, purpose in (
                    ("classification", "classification"),
                    ("issuer", "issuer"),
                    ("material-role", "material_role"),
                    ("name", "name"),
                    ("product-code", "product_code"),
                    ("version", "version"),
                )
            ]
            materials.append(
                {
                    "material_id": material["material_id"],
                    "material_role": ROLES[int(material["material_id"].rsplit("-", 1)[1])],
                    "material_role_evidence_refs": ["material-role"],
                    "entities": [
                        {
                            "entity_ref": "entity",
                            "issuer": ISSUER,
                            "name": "平安冲突（2026）两全保险"
                            if "平安冲突" in material["blocks"][0]["text"]
                            else TITLE,
                            "product_code": PRODUCT_CODE,
                            "version_label": VERSION,
                            "filing_or_registration": {
                                "kind": "filing_number",
                                "value": FILING,
                            },
                            "identity_confidence": "1.000000",
                            "identity_evidence_refs": [
                                "issuer",
                                "name",
                                "product-code",
                                "version",
                            ],
                            "labels": [
                                {
                                    "taxonomy_label": "endowment_insurance",
                                    "confidence": "1.000000",
                                    "evidence_refs": ["classification"],
                                }
                            ],
                            "primary_label": "endowment_insurance",
                            "valid_from": None,
                            "valid_through": None,
                        }
                    ],
                    "evidence": evidence,
                }
            )
        return {
            "contract": "g3-batch-resolution-semantic-references.local.v1",
            "materials": materials,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        envelope = json.loads(request.content)
        content = json.loads(envelope["messages"][1]["content"])
        if content.get("contract") == "g3-c-classify-prompt-context.830.v1":
            self.identity_requests.append(envelope)
            semantic = self._identity(content)
        elif content.get("contract") == "product-discovery-context.830.v1":
            self.discovery_requests.append(envelope)
            semantic = {
                "contract": "product-discovery-proposal.830.v1",
                "proposal": {
                    "contract": "g3-d-compile-semantic-references.local.v1",
                    "transformation": "EXTRACT",
                    "definitions": [],
                    "fields": [],
                    "pages": [],
                },
                "dispositions": [],
            }
        elif content.get("contract") == "product-discovery-review-context.830.v1":
            self.discovery_review_requests.append(envelope)
            semantic = {
                "contract": "product-discovery-review.830.v1",
                "review": {
                    "request_hash": content["request_hash"],
                    "output_hash": content["output_hash"],
                    "decision": "PASS",
                    "reasons": ["fixture bounded independent review"],
                    "page_scores": {},
                },
                "disposition_checks": [],
            }
        else:
            assert content["contract"] == "product-field-window-request.v2"
            self.field_requests.append(envelope)
            fields = []
            for index, task in enumerate(content["field_targets"]):
                invalid = self.fail_one_field and len(self.field_requests) == 1 and index == 0
                fields.append(
                    {
                        "field_ref": task["field_ref"],
                        "state": "present" if invalid else "unknown",
                        "value": "未核验格式值" if invalid else None,
                        "unknown_reason": None if invalid else "材料未提供该字段",
                        "evidence": [],
                        "concept_refs": [],
                        "conditions": [],
                        "exceptions": [],
                        "valid_time": "",
                        "audit_reason": "仅按当前材料抽取",
                    }
                )
            self.fail_one_field = False
            semantic = {
                "contract": "g3-d-compile-semantic-references.local.v1",
                "transformation": "EXTRACT",
                "definitions": [],
                "fields": fields,
                "pages": [],
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _json(semantic).decode()}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )


class FixturePlatform:
    def __init__(self, base: dict, *, conflict: bool = False):
        self.base = base
        self.sources = tuple(_source_snapshot(i, conflicting=conflict) for i in range(3))
        self.current = {
            "release_id": base["snapshot"]["release_id"],
            "activation_epoch": base["snapshot"]["activation_epoch"],
        }
        self.candidate = None
        self.preparation = None
        self.source_captures = 0
        self.activations = 0

    def _data(self, value, status=200):
        return httpx.Response(status, json={"success": True, "data": value})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        prefix = (
            f"/api/v1/knowledgebase/{SCOPE.wiki_knowledge_base_id}/wiki/"
            f"release-scopes/{SCOPE.space_id}/raw/{SCOPE.raw_knowledge_base_id}"
        )
        assert path.startswith(prefix)
        suffix = path[len(prefix) :]
        if suffix.startswith("/platform/uploads/"):
            ordinal = int(suffix.rsplit("/", 1)[1])
            run_id = suffix.split("/platform/uploads/", 1)[1].rsplit("/", 1)[0]
            return self._data(
                {
                    "contract": "g3-platform-upload-snapshot.830.v1",
                    "run_id": run_id,
                    "ordinal": ordinal,
                    "knowledge_id": f"knowledge-new-{ordinal}",
                    "file_name": FILES[ordinal],
                    "parse_attempt": 1,
                    "parse_status": "completed",
                }
            )
        if suffix.startswith("/platform/sources/"):
            ordinal = int(suffix.split("knowledge-new-", 1)[1].split("/", 1)[0])
            self.source_captures += 1
            return self._data(self.sources[ordinal])
        if suffix == "/current":
            return self._data(self.current)
        if suffix.startswith("/platform/bases/"):
            return self._data(self.base)
        if suffix == "/platform/preparations":
            value = json.loads(request.content)
            if "transfer" in value:
                from tests.product_ingestion.test_candidate_transfer import decode_transfer_fixture

                bundle = decode_transfer_fixture(value["transfer"], self.base["snapshot"])
            else:
                bundle = value["bundle"]
            self.candidate = compiler.validate_batch_candidate(_json(bundle))
            preparation_id = value["preparation_id"]
            self.preparation = {
                "tenant_id": int(SCOPE.tenant_id),
                "space_id": SCOPE.space_id,
                "raw_kb_id": SCOPE.raw_knowledge_base_id,
                "wiki_kb_id": SCOPE.wiki_knowledge_base_id,
                "preparation_id": preparation_id,
                "status": "draft",
                "preparation_digest": _sha(request.content),
                "candidate_digest": self.candidate.candidate_hash,
                "manifest_digest": self.candidate.page_manifest.members_sha256,
                "ready_receipt_digest": "d" * 64,
                "review_policy_id": "e" * 64,
                "expected_release_id": self.current["release_id"],
                "expected_activation_epoch": self.current["activation_epoch"],
                "created_at": datetime.now(UTC).isoformat(),
            }
            return self._data(self.preparation)
        if suffix.endswith("/review"):
            return self._data(
                {
                    **self.preparation,
                    "status": "ready",
                    "review_decision_digest": _sha(request.content),
                }
            )
        if suffix == "/platform/activate":
            value = json.loads(request.content)
            authorization_raw = canonical(value["authorization"])
            authorization = value["authorization"]
            self.activations += 1
            self.current = {
                "release_id": f"release-product-{self.activations}",
                "activation_epoch": authorization["expected_activation_epoch"] + 1,
            }
            self.base = _published_snapshot(
                self.candidate,
                release_id=self.current["release_id"],
                activation_epoch=self.current["activation_epoch"],
            )
            return self._data(
                {
                    "tenant_id": int(SCOPE.tenant_id),
                    "space_id": SCOPE.space_id,
                    "raw_kb_id": SCOPE.raw_knowledge_base_id,
                    "wiki_kb_id": SCOPE.wiki_knowledge_base_id,
                    "nonce": authorization["nonce"],
                    "authorization_digest": _sha(authorization_raw),
                    "previous_release_id": authorization["expected_release_id"],
                    **self.current,
                }
            )
        assert self.candidate is not None
        members = {
            row.member_id: row
            for row in self.candidate.page_manifest.members
            if row.owner_id
            in {
                binding.entity_id
                for binding in self.candidate.request.entity_bindings
                if binding.display_name == TITLE
            }
        }
        if suffix.endswith("/search"):
            return self._data(
                [
                    {
                        "kind": row.kind,
                        "logical_slug": row.member_id,
                        "revision_id": self.candidate.candidate_hash,
                        "payload": row.payload,
                    }
                    for row in members.values()
                    if row.kind == "entity_overview"
                ]
            )
        if "/schema/concept-pages/" in suffix and "/citations/" not in suffix:
            member_id = suffix.split("/schema/concept-pages/", 1)[1]
            row = members[member_id]
            return self._data(
                {
                    "contract": "concept-page-read.830.g2.v1",
                    "read_mode": "pinned",
                    **self.current,
                    "candidate_hash": self.candidate.candidate_hash,
                    "space_id": SCOPE.space_id,
                    "raw_kb_id": SCOPE.raw_knowledge_base_id,
                    "wiki_kb_id": SCOPE.wiki_knowledge_base_id,
                    "member": row.model_dump(mode="json"),
                    "related_members": [],
                    "citations": [],
                }
            )
        raise AssertionError(f"unexpected platform request: {request.method} {suffix}")


async def _compose(settings, session_factory, platform, model):
    captured = {}

    def factory(context):
        captured["context"] = context
        return build_product_pipeline(context)

    result = compose_product_worker(
        settings=settings,
        lifecycle=Lifecycle(),
        session_factory=session_factory,
        pipeline_factory=factory,
    )
    service = captured["context"].bindings[SCOPE.space_id]
    await service.platform.client.aclose()
    service.platform.client = httpx.AsyncClient(
        base_url="http://platform.fixture",
        headers={"X-API-Key": "fixture-machine-secret", "Accept": "application/json"},
        transport=httpx.MockTransport(platform),
    )
    model_client = httpx.AsyncClient(
        base_url="http://model.fixture", transport=httpx.MockTransport(model)
    )
    service.model_executor._client = model_client
    return result, captured["context"], model_client


def _sqlite_engine(path: Path):
    # WAL lets the real heartbeat/read transactions coexist with P1's atomic
    # domain writes in the SQLite fixture, matching PostgreSQL's nonblocking reads.
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 120}, future=True)

    @event.listens_for(engine, "connect")
    def pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=120000")
        cursor.close()

    return engine


async def _step(runtime, jobs):
    await runtime.pump.tick()
    claimed = jobs.claim(space_ids=(SCOPE.space_id,), worker_id="fixture-worker")
    if isinstance(claimed, ClaimedJob):
        await runtime.worker.process_job(claimed.job)
        return True
    return False


async def _finish(runtime, context, jobs, run_id, *, limit=160):
    for _ in range(limit):
        await _step(runtime, jobs)
        value = context.store.get_run(scope=SCOPE, run_id=run_id)
        if value.state in {
            ProductRunState.SUCCEEDED,
            ProductRunState.PARTIAL_SUCCESS,
            ProductRunState.FAILED,
            ProductRunState.NEEDS_CONFIRMATION,
        }:
            return value
    pytest.fail("durable product pipeline did not reach a terminal state")


@pytest.mark.asyncio
async def test_real_pipeline_restarts_without_resend_then_retries_only_failed_field(tmp_path):
    base, base_candidate = _base_snapshot()
    settings = _settings(tmp_path, base_candidate)
    engine = _sqlite_engine(tmp_path / "pipeline.db")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    jobs = JobStore(session_factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, session_factory, platform, model)
    run = context.store.create_run(
        scope=SCOPE, idempotency_key="new-product", expected_upload_count=3
    )
    admit_uploads(context.store, SCOPE, run.run_id)

    original_prepare = context.artifacts.prepare_artifact_writes
    interrupted = False
    discovery_interrupted = False

    def fail_after_recording(**kwargs):
        nonlocal interrupted, discovery_interrupted
        if not discovery_interrupted and any(
            row.artifact_kind == "discovery_summary" for row in kwargs["drafts"]
        ):
            discovery_interrupted = True
            raise RuntimeError("fixture crash after durable discovery/review recording")
        if not interrupted and any(row.artifact_kind == "identity" for row in kwargs["drafts"]):
            interrupted = True
            raise RuntimeError("fixture crash after durable model recording")
        return original_prepare(**kwargs)

    context.artifacts.prepare_artifact_writes = fail_after_recording
    for _ in range(20):
        await _step(runtime, jobs)
        if interrupted:
            break
    assert interrupted and len(model.identity_requests) == 1, (
        runtime.issues,
        context.store.list_stages(scope=SCOPE, run_id=run.run_id),
    )
    identity_stage = next(
        row
        for row in context.store.list_stages(scope=SCOPE, run_id=run.run_id)
        if row.stage_key == "identity"
    )
    assert (
        jobs.get_job(space_id=SCOPE.space_id, job_id=identity_stage.job_id).state
        is JobState.RETRY_WAIT
    )

    await runtime.close()
    await model_client.aclose()
    runtime, context, model_client = await _compose(settings, session_factory, platform, model)
    original_prepare = context.artifacts.prepare_artifact_writes
    context.artifacts.prepare_artifact_writes = fail_after_recording
    terminal = await _finish(runtime, context, jobs, run.run_id)

    assert discovery_interrupted, "fixture did not exercise discovery artifact crash"
    assert terminal.state is ProductRunState.PARTIAL_SUCCESS
    assert len(model.identity_requests) == 1, "recorded identity raw was sent again after restart"
    assert platform.source_captures == 3 and platform.activations == 1
    attempts = context.store.list_field_attempts(scope=SCOPE, run_id=run.run_id)
    failed = tuple(row for row in attempts if row.outcome is FieldOutcomeKind.EXTRACTION_FAILED)
    assert len(failed) == 1
    assert all(row.validated_result is None for row in failed)
    assert len(base_candidate.request.entity_bindings) == 5
    assert len(platform.candidate.request.entity_bindings) == 6
    assert platform.candidate.request.base_request.existing_fields == (
        base_candidate.compile_result.output.fields
    )
    assert {
        row.entity_id: row.entity_version for row in base_candidate.request.entity_bindings
    }.items() <= {
        row.entity_id: row.entity_version for row in platform.candidate.request.entity_bindings
    }.items()
    assert terminal.missing_count > 0
    assert len(model.discovery_requests) == 1, "permanent pipeline omitted open discovery"
    assert len(model.discovery_review_requests) == 1
    discovery = json.loads(
        context.artifacts.get_artifact(
            scope=SCOPE,
            run_id=run.run_id,
            artifact_kind="discovery_summary",
            artifact_key="product",
        ).payload
    )
    assert discovery["state"] == "EMPTY" and discovery["reused"] is False
    assert discovery["coverage"]["material_count"] == 3

    identity_calls_before = len(model.identity_requests)
    field_calls_before = len(model.field_requests)
    retry = context.store.retry_fields(
        scope=SCOPE,
        run_id=run.run_id,
        failed_attempt_ids=(failed[0].attempt_id,),
        idempotency_key="new-product-retry",
    )
    admit_uploads(context.store, SCOPE, retry.run_id)
    retry_terminal = await _finish(runtime, context, jobs, retry.run_id)
    retry_attempts = context.store.list_field_attempts(scope=SCOPE, run_id=retry.run_id)

    assert retry_terminal.state is ProductRunState.PARTIAL_SUCCESS
    assert len(model.identity_requests) == identity_calls_before
    assert len(model.field_requests) == field_calls_before + 1
    assert [
        row["field_key"]
        for row in json.loads(model.field_requests[-1]["messages"][1]["content"])["field_targets"]
    ] == [failed[0].field_key]
    assert {row.field_key for row in retry_attempts} == {failed[0].field_key}
    assert retry_attempts[0].outcome is FieldOutcomeKind.NOT_PROVIDED
    assert platform.source_captures == 3, "retry recaptured immutable source snapshots"
    retry_identity = json.loads(
        context.artifacts.get_artifact(
            scope=SCOPE,
            run_id=retry.run_id,
            artifact_kind="identity",
            artifact_key="product",
        ).payload
    )
    assert retry_identity["reused_from_run_id"] == run.run_id
    assert len(model.discovery_requests) == len(model.discovery_review_requests) == 1
    reused = json.loads(
        context.artifacts.get_artifact(
            scope=SCOPE,
            run_id=retry.run_id,
            artifact_kind="discovery_summary",
            artifact_key="product",
        ).payload
    )
    assert reused["state"] == "EMPTY" and reused["reused"] is True
    assert reused["reused_from_run_id"] == run.run_id

    await runtime.close()
    await model_client.aclose()
    engine.dispose()


@pytest.mark.asyncio
async def test_real_identity_conflict_terminates_after_one_classification(tmp_path):
    base, base_candidate = _base_snapshot()
    settings = _settings(tmp_path, base_candidate)
    engine = _sqlite_engine(tmp_path / "conflict.db")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    jobs = JobStore(session_factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base, conflict=True), FixtureModel()
    runtime, context, model_client = await _compose(settings, session_factory, platform, model)
    run = context.store.create_run(scope=SCOPE, idempotency_key="conflict", expected_upload_count=3)
    admit_uploads(context.store, SCOPE, run.run_id)

    terminal = await _finish(runtime, context, jobs, run.run_id, limit=40)

    assert terminal.state is ProductRunState.NEEDS_CONFIRMATION
    assert terminal.terminal_reason == "PRODUCT_IDENTITY_UNRESOLVED:AMBIGUOUS_IDENTITY"
    assert len(model.identity_requests) == 1 and not model.field_requests
    assert platform.activations == 0
    await runtime.close()
    await model_client.aclose()
    engine.dispose()


@pytest.mark.asyncio
async def test_legacy_field_retry_preserves_sealed_hash_and_role(tmp_path):
    from types import SimpleNamespace

    from sqlalchemy import update

    from insurance_harness.product_ingestion.tables import ProductMaterial

    base, base_candidate = _base_snapshot()
    settings = _settings(tmp_path, base_candidate)
    engine = _sqlite_engine(tmp_path / "legacy-retry.db")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    jobs = JobStore(session_factory, settings.job_runtime_config())
    platform, model = FixturePlatform(base), FixtureModel()
    runtime, context, model_client = await _compose(settings, session_factory, platform, model)
    run = context.store.create_run(scope=SCOPE, idempotency_key="legacy", expected_upload_count=3)
    admit_uploads(context.store, SCOPE, run.run_id)
    for _ in range(12):
        await _step(runtime, jobs)
        if context.artifacts.list_artifacts(
            scope=SCOPE, run_id=run.run_id, artifact_kind="identity"
        ):
            break
    assert len(model.identity_requests) == 1 and not model.field_requests
    # Old successful routing sealed roles independently of classifier proposals.
    legacy_hash = "c" * 64
    with session_factory.begin() as session:
        session.execute(
            update(ProductMaterial)
            .where(ProductMaterial.run_id == run.run_id)
            .values(product_identity_sha256=legacy_hash)
        )
        session.execute(
            update(ProductMaterial)
            .where(
                ProductMaterial.run_id == run.run_id,
                ProductMaterial.knowledge_id == "knowledge-new-0",
            )
            .values(inferred_material_role="brochure")
        )
    original = context.store.get_run(scope=SCOPE, run_id=run.run_id)
    get = context.artifacts.get_artifact
    legacy_route = {
        "product_name": TITLE,
        "product_identity_sha256": legacy_hash,
        "route": {
            "primary_label": "endowment_insurance",
            "schema_pack_id": "schemapack_endowment_insurance",
        },
        "materials": [
            {"material_id": row.material_id, "material_type": row.source.inferred_material_role}
            for row in original.materials
        ],
    }

    def old_artifact(**kwargs):
        if kwargs["artifact_kind"] == "routing":
            return SimpleNamespace(payload=_json(legacy_route))
        return get(**kwargs)

    context.artifacts.get_artifact = old_artifact
    replay = SimpleNamespace(
        run_id=run.run_id, retry_of_run_id=run.run_id, materials=original.materials
    )
    ports = build_product_pipeline(context)
    output = await ports.stage_handlers["identity"](
        SCOPE, replay, SimpleNamespace(dependency_sha256="d" * 64), None
    )
    resolved = json.loads(
        next(row.payload for row in output.drafts if row.artifact_kind == "resolved_routing")
    )
    assert resolved["product_identity_sha256"] == legacy_hash
    assert (
        next(row for row in resolved["materials"] if row["knowledge_id"] == "knowledge-new-0")[
            "material_type"
        ]
        == "brochure"
    )
    assert len(model.identity_requests) == 1 and not model.field_requests
    assert context.store.get_run(scope=SCOPE, run_id=run.run_id).materials == original.materials
    await runtime.close()
    await model_client.aclose()
    engine.dispose()

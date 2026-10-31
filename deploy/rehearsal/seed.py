"""I3a minimal fresh install and smoke over HTTP, bound to the verified rehearsal instance.

`connect` binds first (stack.bind: owned VM, rehearsal context and compose project, a loopback port
live does not publish, the instance marker), so nothing is registered, configured or uploaded
anywhere else. The cached service key and state record the instance and tenant they were made for
and are refused anywhere else; reused models and knowledge bases must belong to that tenant.
Failures carry a fixed code and an HTTP status, never a response body. Materials are bound by
SHA-256: one product per rehearsal, its own files, each checked against the RAW listing's digest
before the source map names it. Model keys: DEEPSEEK_API_KEY (else HARNESS_SCHEMA_FIELDS_API_KEY)
and DASHSCOPE_API_KEY from the environment; nothing secret is printed.
"""

import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import private
import stack
from vm import Runner, Settings

OWNER_EMAIL = "owner@rehearsal.example.com"
SPACE_ID = "rehearsal-1"
RAW_KB, WIKI_KB = "企业知识-演练-原始材料", "企业知识-演练-wiki"
DEEPSEEK, DASHSCOPE = "https://api.deepseek.com/v1", "https://dashscope.aliyuncs.com"
# The production model set (blueprint §7.6): DeepSeek answers, Bailian embeds and reranks.
MODELS: list[dict[str, Any]] = [
    {"name": "deepseek-v4-flash", "type": "KnowledgeQA", "key": "deepseek",
     "parameters": {"base_url": DEEPSEEK, "provider": "deepseek",
                    "interface_type": "openai_compatible"}},
    {"name": "qwen3.7-text-embedding", "type": "Embedding", "key": "dashscope",
     "parameters": {"base_url": f"{DASHSCOPE}/compatible-mode/v1", "provider": "aliyun",
                    "embedding_parameters": {"dimension": 1024}}},
    {"name": "qwen3-rerank", "type": "Rerank", "key": "dashscope",
     "parameters": {"base_url": f"{DASHSCOPE}/api/v1/services/rerank/text-rerank/text-rerank",
                    "provider": "aliyun"}},
]
# Rehearsal-only review policy: admits the product's pack at threshold 0 so the machine route and
# its "机器审核" label are exercised end to end. The shipped policy admits no pack, so a real
# install routes every product to the human queue; never use it outside a throwaway rehearsal.
POLICY_VERSION = "rehearsal-i3a-1"
SOURCE_REF = re.compile(r"source:v1:([A-Za-z0-9][A-Za-z0-9_-]{0,127}):([0-9]+):[0-9a-f]{64}")
QUESTION = "{name}的投保年龄是多少？"
COMPILE_MAX_SENT, REVIEW_MAX_SENT = 4, 3
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_PASSWORD = re.compile(r"(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9]{8,32}")  # the App's policy (F5)


class Stop(Exception):
    """A fixed code, an HTTP status and at most a downstream code of the same shape."""

    def __init__(self, code: str, status: int | None = None, detail: object = None) -> None:
        self.code, self.status = code, status
        self.detail = detail if isinstance(detail, str) and _CODE.fullmatch(detail) else None
        super().__init__(code)

    def report(self) -> dict:
        report: dict[str, object] = {"stopped": self.code}
        if self.status is not None:
            report["status"] = self.status
        if self.detail:
            report["detail"] = self.detail
        return report


@dataclass(frozen=True)
class Context:
    settings: Settings
    run: Runner
    opener: stack.Opener
    instance: stack.Instance
    home: Path


def connect(settings: Settings, run: Runner, opener: stack.Opener) -> Context:
    instance = stack.bind(settings, run, opener)
    return Context(settings, run, opener, instance, private.private_dir(settings.home))


class Api:
    def __init__(self, ctx: Context, *, token: str = "", api_key: str = "") -> None:
        self.ctx, self.token, self.api_key = ctx, token, api_key

    def raw(self, method: str, path: str, data: bytes | None = None,
            content_type: str = "application/json", timeout: float = 60) -> tuple[int, bytes]:
        headers = {"Content-Type": content_type, "Accept-Language": "zh-CN"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return self.ctx.opener(method, self.ctx.instance.base + path, data, headers, timeout)

    def json(self, method: str, path: str, body: object = None, *, code: str,
             ok: tuple[int, ...] = (200, 201), timeout: float = 60) -> dict:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        status, payload = self.raw(method, path, data, timeout=timeout)
        if status not in ok:
            raise Stop(code, status)
        try:
            document = json.loads(payload) if payload else {}
        except ValueError:
            raise Stop("RESPONSE_INVALID", status) from None
        if not isinstance(document, dict):
            raise Stop("RESPONSE_INVALID", status)
        return document


def data(document: dict) -> object:
    return document.get("data", document)


def items(value: object) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise Stop("RESPONSE_INVALID")
    return value


def load_state(ctx: Context) -> dict:
    state = private.read_json(ctx.home, "state.json") or {}
    if state.get("instance_id", ctx.instance.instance_id) != ctx.instance.instance_id:
        raise Stop("STATE_FROM_OTHER_INSTANCE")
    state["instance_id"] = ctx.instance.instance_id
    return state


def save_state(ctx: Context, state: dict) -> None:
    private.write_json(ctx.home, "state.json", state)


def model_key(kind: str) -> str:
    names = {"deepseek": ("DEEPSEEK_API_KEY", "HARNESS_SCHEMA_FIELDS_API_KEY"),
             "dashscope": ("DASHSCOPE_API_KEY",)}[kind]
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    raise Stop("MODEL_KEY_MISSING")


def owner_login(ctx: Context) -> tuple[Api, int]:
    values = private.read_env(ctx.home, "secrets.env")
    if not _PASSWORD.fullmatch(values.get("OWNER_PASSWORD", "")):
        values["OWNER_PASSWORD"] = f"R7{secrets.token_hex(12)}"
        private.write_env(ctx.home, "secrets.env", values)
    api = Api(ctx)
    credentials = {"email": OWNER_EMAIL, "password": values["OWNER_PASSWORD"]}
    body = json.dumps(credentials).encode()
    status, payload = api.raw("POST", "/api/v1/auth/login", body)
    if status in (400, 401):  # not registered yet: the restart after `platform` closes it
        api.json("POST", "/api/v1/auth/register", {"username": "rehearsal-owner", **credentials},
                 code="REGISTER_FAILED")
        status, payload = api.raw("POST", "/api/v1/auth/login", body)
    if status != 200:
        raise Stop("LOGIN_FAILED", status)
    try:
        login = json.loads(payload)
        tenant = login.get("tenant") or login.get("active_tenant") or {}
        token, tenant_id = login["token"], int(tenant["id"])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise Stop("LOGIN_RESPONSE_INVALID") from None
    if not isinstance(token, str) or not token:
        raise Stop("LOGIN_RESPONSE_INVALID")
    return Api(ctx, token=token), tenant_id


def _service_key(ctx: Context, owner: Api, tenant: int) -> dict[str, str]:
    """The cached key only when it was issued by this instance, for this tenant, and still is."""
    service = private.read_env(ctx.home, "harness.env")
    if service:
        if (service.get("INSTANCE_ID") != ctx.instance.instance_id
                or service.get("TENANT_ID") != str(tenant)):
            raise Stop("CACHED_KEY_MISMATCH")
        listed = items(data(owner.json("GET", f"/api/v1/tenants/{tenant}/api-keys",
                                       code="API_KEYS_UNREADABLE")) or [])
        if not any(str(key.get("id")) == service.get("KEY_ID") for key in listed):
            raise Stop("CACHED_KEY_MISMATCH")
        return service
    created = data(owner.json("POST", f"/api/v1/tenants/{tenant}/api-keys",
                              {"name": "rehearsal-harness", "full_access": True},
                              code="API_KEY_CREATE_FAILED"))
    if not isinstance(created, dict) or not created.get("token") or created.get("id") is None:
        raise Stop("RESPONSE_INVALID")
    service = {"HARNESS_WEKNORA_API_KEY": str(created["token"]), "KEY_ID": str(created["id"]),
               "INSTANCE_ID": ctx.instance.instance_id, "TENANT_ID": str(tenant)}
    private.write_env(ctx.home, "harness.env", service)
    return service


def service_api(ctx: Context, state: dict) -> Api:
    service = private.read_env(ctx.home, "harness.env")
    if (not service.get("HARNESS_WEKNORA_API_KEY")
            or service.get("INSTANCE_ID") != ctx.instance.instance_id
            or service.get("TENANT_ID") != str(state.get("tenant_id"))):
        raise Stop("SERVICE_KEY_UNBOUND")
    return Api(ctx, api_key=service["HARNESS_WEKNORA_API_KEY"])


def _own(listed: list[dict], tenant: int) -> list[dict]:
    """Objects of this tenant; seeing another tenant's means the key is not the owner's."""
    if any(item.get("tenant_id") not in (tenant, 0) for item in listed):
        raise Stop("SERVICE_KEY_TENANT_MISMATCH")
    return [item for item in listed if item.get("tenant_id") == tenant]


def platform(ctx: Context) -> dict:
    state = load_state(ctx)
    owner, tenant = owner_login(ctx)
    if state.get("tenant_id", tenant) != tenant:
        raise Stop("STATE_FROM_OTHER_TENANT")
    service = _service_key(ctx, owner, tenant)
    api = Api(ctx, api_key=service["HARNESS_WEKNORA_API_KEY"])
    listed = _own(items(data(api.json("GET", "/api/v1/models", code="MODELS_UNREADABLE")) or []),
                  tenant)
    existing = {(m.get("name"), m.get("type")): m["id"] for m in listed}
    models = {}
    for spec in MODELS:
        model_id = existing.get((spec["name"], spec["type"]))
        if model_id is None:
            body = {"name": spec["name"], "display_name": spec["name"], "type": spec["type"],
                    "source": "remote", "description": "I3a rehearsal",
                    "parameters": {**spec["parameters"], "api_key": model_key(spec["key"])}}
            created = data(owner.json("POST", "/api/v1/models", body, code="MODEL_CREATE_FAILED"))
            model_id = created["id"] if isinstance(created, dict) else None
        if not isinstance(model_id, str) or not model_id:
            raise Stop("RESPONSE_INVALID")
        models[spec["type"]] = model_id
    # A new tenant's built-in quick-answer agent has no chat model, and a per-request model cannot
    # stand in for it (session_qa_helpers.resolveChatModelID): an install sets it once (F4).
    owner.json("PATCH", "/api/v1/agents/builtin-quick-answer",
               {"model_id": models["KnowledgeQA"]}, code="AGENT_UPDATE_FAILED")
    kbs = {kb.get("name"): kb["id"] for kb in _own(items(data(api.json(
        "GET", "/api/v1/knowledge-bases", code="KBS_UNREADABLE")) or []), tenant)}
    for name, summary in ((RAW_KB, ""), (WIKI_KB, models["KnowledgeQA"])):
        if name not in kbs:
            # RAW has no summary model: a per-upload summary would spend chat calls for nothing.
            body = {"name": name, "type": "document", "description": "I3a rehearsal",
                    "embedding_model_id": models["Embedding"], "summary_model_id": summary,
                    "chunking_config": {"chunk_size": 512, "chunk_overlap": 100},
                    "indexing_strategy": {"vector_enabled": True, "keyword_enabled": True,
                                          "wiki_enabled": False, "graph_enabled": False}}
            created = data(owner.json("POST", "/api/v1/knowledge-bases", body,
                                      code="KB_CREATE_FAILED"))
            if not isinstance(created, dict) or created.get("tenant_id") != tenant:
                raise Stop("RESPONSE_INVALID")
            kbs[name] = created["id"]
    space = {"tenant_id": tenant, "space_id": SPACE_ID, "raw_kb_id": kbs[RAW_KB],
             "wiki_kb_id": kbs[WIKI_KB]}
    # Read by the App at start (the seed command recreates it); the restart closes registration.
    private.write_env(ctx.home, "spaces.env", {
        "ENTERPRISE_SPACES": json.dumps([space], separators=(",", ":")),
        "DISABLE_REGISTRATION": "true"})
    state.update(tenant_id=tenant, models=models, space=space)
    save_state(ctx, state)
    return {"tenant_id": tenant, "models": sorted(models), "space": SPACE_ID}


def listing(api: Api, kb: str) -> list[dict]:
    query = "page=1&page_size=100&sort_by=created_at&sort_order=asc"
    document = api.json("GET", f"/api/v1/knowledge-bases/{kb}/knowledge?{query}",
                        code="RAW_LISTING_UNREADABLE")
    found = items(data(document) or [])
    if isinstance(document.get("total"), int) and document["total"] > len(found):
        raise Stop("RAW_LISTING_TOO_LARGE")
    return found


def multipart(path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    disposition = "Content-Disposition: form-data; name="
    head = (f'--{boundary}\r\n{disposition}"fileName"\r\n\r\n{path.name}\r\n'
            f'--{boundary}\r\n{disposition}"file"; filename="{path.name}"\r\n'
            "Content-Type: application/pdf\r\n\r\n").encode()
    return head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode(), boundary


def materials(ctx: Context, poll_seconds: float = 10, limit_seconds: float = 1800) -> dict:
    state = load_state(ctx)
    api, product = service_api(ctx, state), ctx.settings.product
    if state.get("product", product) != product:
        raise Stop("PRODUCT_MISMATCH")  # one product per rehearsal instance
    local: dict[str, Path] = {}
    for pdf in sorted(stack.product_dir(ctx.settings.repo, product).glob("*.pdf")):
        digest = stack.sha256_of(pdf)
        if digest in local:
            raise Stop("MATERIALS_DUPLICATE")
        local[digest] = pdf
    recorded: dict[str, str] = dict(state.get("materials") or {})
    if not local or (recorded and set(recorded) != set(local)):
        raise Stop("MATERIALS_CHANGED")
    raw = state["space"]["raw_kb_id"]
    present = listing(api, raw)
    by_id = {item.get("id"): item for item in present}
    started = time.time()
    for digest, pdf in local.items():
        if digest in recorded:
            if recorded[digest] not in by_id:
                raise Stop("MATERIAL_MISSING")
            continue
        same = [item["id"] for item in present if item.get("file_sha256") == digest]
        if len(same) > 1:
            raise Stop("MATERIAL_AMBIGUOUS")
        if same:
            recorded[digest] = same[0]  # this exact file, uploaded before its id was recorded
        else:
            body, boundary = multipart(pdf)
            status, payload = api.raw("POST", f"/api/v1/knowledge-bases/{raw}/knowledge/file",
                                      body, f"multipart/form-data; boundary={boundary}", 300)
            if status not in (200, 201):
                raise Stop("UPLOAD_FAILED", status)
            try:
                knowledge_id = json.loads(payload)["data"]["id"]
            except (ValueError, KeyError, TypeError):
                raise Stop("UPLOAD_RESPONSE_INVALID", status) from None
            recorded[digest] = str(knowledge_id)
        state.update(product=product, materials=recorded)
        save_state(ctx, state)
    expected = {knowledge_id: digest for digest, knowledge_id in recorded.items()}
    while True:
        by_id = {item.get("id"): item for item in listing(api, raw)}
        mine = [by_id.get(knowledge_id) for knowledge_id in expected]
        if any(item is None for item in mine):
            raise Stop("MATERIAL_MISSING")
        states = {item["parse_status"] for item in mine if item}
        if states & {"failed", "cancelled"}:
            raise Stop("PARSE_FAILED")
        if states == {"completed"}:
            break
        if time.time() - started > limit_seconds:
            raise Stop("PARSE_TIMEOUT")
        time.sleep(poll_seconds)
    entries = []
    for knowledge_id, digest in sorted(expected.items()):
        item = by_id[knowledge_id]
        if item.get("file_sha256") != digest:
            raise Stop("MATERIAL_DIGEST_MISMATCH")
        entries.append({"knowledge_id": knowledge_id,
                        "parse_attempt": item["current_parse_attempt"], "sha256": digest})
    run_dir = private.private_dir(ctx.home / "run")
    source_map = {"space_id": SPACE_ID, "products": {product: entries}}
    private.write_json(run_dir, "source-map.json", source_map)
    return {"materials": len(entries), "parse_seconds": round(time.time() - started)}


def harness(ctx: Context, module: str, *argv: str) -> dict:
    """Run one Harness command from this checkout against the bound instance; one JSON line."""
    state = load_state(ctx)
    env = {key: value for key, value in os.environ.items() if not key.startswith("HARNESS_")}
    env.update(HARNESS_WEKNORA_BASE_URL=ctx.instance.base,
               HARNESS_WEKNORA_API_KEY=service_api(ctx, state).api_key,
               HARNESS_SCHEMA_FIELDS_API_KEY=model_key("deepseek"))
    python = ctx.settings.repo / "harness/.venv/bin/python"
    done = ctx.run([str(python), "-m", module, *argv], env=env, timeout=3600)
    lines = [line for line in done.text.splitlines() if line.startswith("{")]
    try:
        result = json.loads(lines[-1]) if lines else {}
    except ValueError:
        result = {}
    if done.returncode != 0 or not isinstance(result, dict):
        detail = result.get("stopped") if isinstance(result, dict) else None
        raise Stop("HARNESS_STOPPED", detail=detail)
    return result


def sends(root: Path) -> int:
    path = root / "budget.jsonl"
    if not path.exists():
        return 0
    return sum('"reserved"' in line for line in path.read_text().splitlines())


def publish(ctx: Context) -> dict:
    state = load_state(ctx)
    product = ctx.settings.product
    if state.get("product") != product or not state.get("materials"):
        raise Stop("MATERIALS_NOT_READY")
    run_dir = private.private_dir(ctx.home / "run")
    registry, publication = run_dir / "registry.json", run_dir / "publication"
    if not registry.exists():
        harness(ctx, "insurance_harness.ingest.uploads", "seed", "--registry", str(registry),
                "--space", SPACE_ID, "--raw-kb", state["space"]["raw_kb_id"],
                "--source-map", str(run_dir / "source-map.json"), "--repo", str(ctx.settings.repo))
    stages = ctx.settings.repo / "harness/src/insurance_harness/models/stages.json"
    # The production path with the shipped policy: compile, independent review, route.
    report = harness(ctx, "insurance_harness.ingest.uploads", "publish",
                     "--registry", str(registry), "--run-root", str(publication),
                     "--stage-config", str(stages), "--compile-max-sent", str(COMPILE_MAX_SENT),
                     "--review-max-sent", str(REVIEW_MAX_SENT), "--products", product)
    if report.get("stopped") or report.get("review_stopped") or report.get("failed"):
        raise Stop("PUBLICATION_STOPPED", detail=report.get("stopped") or report.get(
            "review_stopped"))
    pack = json.loads(registry.read_text())["products"][product]["schema_pack_id"]
    policy = {"version": POLICY_VERSION, "admitted_packs": [pack],
              "thresholds": {pack: {"default": 0.0}}}
    private.write_json(run_dir, "review-policy.json", policy)
    machine = harness(ctx, "insurance_harness.compilers.schema_fields.publish",
                      "--run-root", str(publication / "compile"), "--product", product,
                      "--registry", str(registry), "--route",
                      "--review-policy", str(run_dir / "review-policy.json"),
                      "--scores", str(publication / "review" / product / "scores.json"))
    state["harness"] = {"shipped_route": report.get("routes", {}).get(product),
                        "human_candidate": report.get("candidates", {}).get(product),
                        "machine_route": machine.get("review"),
                        "release_id": machine.get("release_id")}
    save_state(ctx, state)
    return {**state["harness"], "compile_sent": sends(publication / "compile"),
            "review_sent": sends(publication / "review")}


def answer(api: Api, wiki_kb: str, question: str) -> str:
    session = data(api.json("POST", "/api/v1/sessions", {"title": "I3a rehearsal"},
                            code="SESSION_CREATE_FAILED"))
    session_id = session.get("id") if isinstance(session, dict) else None
    body = {"query": question, "knowledge_base_ids": [wiki_kb], "agent_enabled": False,
            "agent_id": "builtin-quick-answer", "disable_title": True, "channel": "api"}
    status, _ = api.raw("POST", f"/api/v1/knowledge-chat/{session_id}",
                        json.dumps(body, ensure_ascii=False).encode(), timeout=600)
    if status != 200:
        raise Stop("QUICK_ANSWER_FAILED", status)
    messages = items(data(api.json("GET", f"/api/v1/messages/{session_id}/load?limit=4",
                                   code="MESSAGES_UNREADABLE")) or [])
    replies = [m for m in messages if m.get("role") == "assistant"]
    return str(replies[-1].get("content") or "") if replies else ""


def smoke(ctx: Context) -> dict:
    state = load_state(ctx)
    api = service_api(ctx, state)
    health, _ = api.raw("GET", "/health")
    active = data(api.json("GET", f"/api/v1/enterprise/spaces/{SPACE_ID}/releases/active",
                           code="ACTIVE_UNREADABLE"))
    if not isinstance(active, dict):
        raise Stop("RESPONSE_INVALID")
    members = items(active.get("members") or [])
    kinds: dict[str, int] = {}
    for member in members:
        kinds[str(member.get("kind"))] = kinds.get(str(member.get("kind")), 0) + 1
    match = SOURCE_REF.search(json.dumps(members, ensure_ascii=False))
    if match is None:
        raise Stop("NO_SOURCE_REFERENCE")
    path = (f"/api/v1/enterprise/spaces/{SPACE_ID}/releases/{active['id']}"
            f"/sources/{match[1]}/attempts/{match[2]}/file")
    status, payload = api.raw("GET", path, timeout=120)
    queue = data(api.json("GET", f"/api/v1/enterprise/spaces/{SPACE_ID}/candidates",
                          code="QUEUE_UNREADABLE"))
    waiting = queue.get("items", []) if isinstance(queue, dict) else queue
    navigation = harness(ctx, "insurance_harness.catalog.publish_navigation", "--space",
                         SPACE_ID, "--dry-run").get("status")
    name = stack.product_dir(ctx.settings.repo, ctx.settings.product).name
    reply = answer(api, state["space"]["wiki_kb_id"], QUESTION.format(name=name))
    # The question asks for the entry age, so a real answer names one ("28天"/"70周岁"); an error
    # text (no chat model, key rejected) does not.
    cites_age = bool(re.search(r"\d+\s*(周岁|天)", reply))
    result = {"health": health,
              "active": {"release_id": active.get("id"), "epoch": active.get("epoch"),
                         "members": kinds},
              "source_file": {"status": status, "pdf": payload[:5] == b"%PDF-",
                              "bytes": len(payload)},
              "human_queue": len(waiting) if isinstance(waiting, list) else None,
              "navigation": navigation,
              "quick_answer": {"chars": len(reply), "cites_age": cites_age}}
    result["passed"] = all([health == 200, kinds.get("claim", 0) > 0, status == 200,
                            payload[:5] == b"%PDF-", navigation == "current", cites_age])
    return result

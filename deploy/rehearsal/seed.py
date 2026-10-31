"""I3a minimal fresh install: tenant, models, knowledge bases, Space, one public product, smoke.

Standard library only; rehearsal.sh runs it with python3 -I. Every step is idempotent: what exists
is found again by name or file digest and reused, so a failed run is simply run again.

    seed.py platform  --base URL --home DIR
    seed.py materials --base URL --home DIR --repo DIR --product ID
    seed.py harness   --base URL --home DIR --repo DIR --product ID
    seed.py smoke     --base URL --home DIR --repo DIR --product ID

Secrets (owner password, service API key) live in DIR with mode 600 and are never printed. Model
keys come from the environment: DEEPSEEK_API_KEY (else HARNESS_SCHEMA_FIELDS_API_KEY) and
DASHSCOPE_API_KEY. Each command prints one JSON line of non-secret results; any failure exits 2
with a short reason.
"""

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

OWNER_EMAIL = "owner@rehearsal.example.com"
SPACE_ID = "rehearsal-1"
RAW_KB, WIKI_KB = "企业知识-演练-原始材料", "企业知识-演练-wiki"
DEEPSEEK, DASHSCOPE = "https://api.deepseek.com/v1", "https://dashscope.aliyuncs.com"
# The production model set (blueprint §7.6): DeepSeek answers, Bailian embeds and reranks.
MODELS = [
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


class Stop(Exception):
    pass


def redact(text: str, home: Path) -> str:
    """Error text may quote a response; never let a known secret through."""
    known = [*read_env(home / "secrets.env").values(), *read_env(home / "harness.env").values()]
    known += [os.environ.get(name, "") for name in
              ("DEEPSEEK_API_KEY", "HARNESS_SCHEMA_FIELDS_API_KEY", "DASHSCOPE_API_KEY")]
    for value in sorted({v for v in known if len(v) >= 8}, key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = (line.rstrip("\n").partition("=") for line in path.read_text().splitlines())
    return {key: value for key, _, value in pairs if key}


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(text)


def write_env(path: Path, values: dict[str, str]) -> None:
    write_private(path, "".join(f"{key}={value}\n" for key, value in sorted(values.items())))


def load_state(home: Path) -> dict:
    path = home / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(home: Path, state: dict) -> None:
    write_private(home / "state.json", json.dumps(state, ensure_ascii=False, indent=1) + "\n")


class Api:
    """JSON over HTTP with either the owner's session token or the service API key."""

    def __init__(self, base: str, *, token: str = "", api_key: str = "") -> None:
        self.base, self.token, self.api_key = base.rstrip("/"), token, api_key

    def _headers(self, content_type: str) -> dict[str, str]:
        headers = {"Content-Type": content_type, "Accept-Language": "zh-CN"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def raw(self, method: str, path: str, data: bytes | None = None,
            content_type: str = "application/json", timeout: float = 60) -> tuple[int, bytes]:
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers=self._headers(content_type))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def json(self, method: str, path: str, body: object = None, ok: tuple[int, ...] = (200, 201),
             timeout: float = 60) -> dict:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        status, payload = self.raw(method, path, data, timeout=timeout)
        if status not in ok:
            raise Stop(f"{method} {path.split('?')[0]} -> HTTP {status}: {payload[:200]!r}")
        return json.loads(payload) if payload else {}


def data(document: dict) -> object:
    return document.get("data", document) if isinstance(document, dict) else document


def service_api(base: str, home: Path) -> Api:
    key = read_env(home / "harness.env").get("HARNESS_WEKNORA_API_KEY", "")
    if not key:
        raise Stop("run `seed platform` first")
    return Api(base, api_key=key)


def owner_login(base: str, home: Path) -> tuple[Api, int]:
    store = home / "secrets.env"
    values = read_env(store)
    # The App's policy: 8-32 characters with at least one letter and one digit.
    password = values.get("OWNER_PASSWORD", "")
    if not re.fullmatch(r"(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9]{8,32}", password):
        values["OWNER_PASSWORD"] = f"R7{secrets.token_hex(12)}"
        write_env(store, values)
    api = Api(base)
    credentials = {"email": OWNER_EMAIL, "password": values["OWNER_PASSWORD"]}
    # Register only the first time: the restart after `platform` closes registration.
    login = api.json("POST", "/api/v1/auth/login", credentials, ok=(200, 400, 401))
    if not login.get("token"):
        api.json("POST", "/api/v1/auth/register", {"username": "rehearsal-owner", **credentials})
        login = api.json("POST", "/api/v1/auth/login", credentials)
    tenant = login.get("tenant") or login.get("active_tenant") or {}
    if not login.get("token") or not tenant.get("id"):
        raise Stop("login returned no token or tenant")
    return Api(base, token=login["token"]), int(tenant["id"])


def model_key(kind: str) -> str:
    names = {"deepseek": ("DEEPSEEK_API_KEY", "HARNESS_SCHEMA_FIELDS_API_KEY"),
             "dashscope": ("DASHSCOPE_API_KEY",)}[kind]
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    raise Stop(f"model key missing: set {names[0]}")


def cmd_platform(args: argparse.Namespace) -> dict:
    home, state = args.home, load_state(args.home)
    owner, tenant = owner_login(args.base, home)
    service = read_env(home / "harness.env")
    if not service.get("HARNESS_WEKNORA_API_KEY"):
        created = data(owner.json("POST", f"/api/v1/tenants/{tenant}/api-keys",
                                  {"name": "rehearsal-harness", "full_access": True}))
        service = {"HARNESS_WEKNORA_API_KEY": created["token"]}
        write_env(home / "harness.env", service)
    api = Api(args.base, api_key=service["HARNESS_WEKNORA_API_KEY"])
    listed = data(api.json("GET", "/api/v1/models")) or []
    existing = {(m["name"], m["type"]): m["id"] for m in listed}
    models = {}
    for spec in MODELS:
        model_id = existing.get((spec["name"], spec["type"]))
        if model_id is None:
            body = {"name": spec["name"], "display_name": spec["name"], "type": spec["type"],
                    "source": "remote", "description": "I3a rehearsal",
                    "parameters": {**spec["parameters"], "api_key": model_key(spec["key"])}}
            model_id = data(owner.json("POST", "/api/v1/models", body))["id"]
        models[spec["type"]] = model_id
    # A fresh tenant's built-in quick-answer agent has no chat model, and a per-request model cannot
    # stand in for it (session_qa_helpers.resolveChatModelID): an install sets it once (finding F4).
    owner.json("PATCH", "/api/v1/agents/builtin-quick-answer", {"model_id": models["KnowledgeQA"]})
    kbs = {kb["name"]: kb["id"] for kb in data(api.json("GET", "/api/v1/knowledge-bases")) or []}
    for name, summary in ((RAW_KB, ""), (WIKI_KB, models["KnowledgeQA"])):
        if name not in kbs:
            # RAW has no summary model: a per-upload summary would spend chat calls for nothing.
            body = {"name": name, "type": "document", "description": "I3a rehearsal",
                    "embedding_model_id": models["Embedding"], "summary_model_id": summary,
                    "chunking_config": {"chunk_size": 512, "chunk_overlap": 100},
                    "indexing_strategy": {"vector_enabled": True, "keyword_enabled": True,
                                          "wiki_enabled": False, "graph_enabled": False}}
            kbs[name] = data(owner.json("POST", "/api/v1/knowledge-bases", body))["id"]
    space = {"tenant_id": tenant, "space_id": SPACE_ID, "raw_kb_id": kbs[RAW_KB],
             "wiki_kb_id": kbs[WIKI_KB]}
    # Read by the App at start (rehearsal.sh recreates it); the same restart closes registration.
    write_env(home / "spaces.env", {"ENTERPRISE_SPACES": json.dumps([space], separators=(",", ":")),
                                    "DISABLE_REGISTRATION": "true"})
    state.update(tenant_id=tenant, models=models, space=space)
    save_state(home, state)
    return {"tenant_id": tenant, "models": sorted(models), "space": SPACE_ID}


def listing(api: Api, kb: str) -> list[dict]:
    query = "page=1&page_size=100&sort_by=created_at&sort_order=asc"
    return data(api.json("GET", f"/api/v1/knowledge-bases/{kb}/knowledge?{query}")) or []


def multipart(path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    disposition = "Content-Disposition: form-data; name="
    head = (f'--{boundary}\r\n{disposition}"fileName"\r\n\r\n{path.name}\r\n'
            f'--{boundary}\r\n{disposition}"file"; filename="{path.name}"\r\n'
            "Content-Type: application/pdf\r\n\r\n").encode()
    return head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode(), boundary


def product_dir(repo: Path, product: str) -> Path:
    for meta in sorted((repo / "dataset/shouxian_product").glob("*/product_meta.json")):
        if json.loads(meta.read_text()).get("planCode") == product:
            return meta.parent
    raise Stop(f"product {product} not in dataset/shouxian_product")


def cmd_materials(args: argparse.Namespace) -> dict:
    state, api = load_state(args.home), service_api(args.base, args.home)
    raw = state["space"]["raw_kb_id"]
    listed = {item.get("file_name"): item for item in listing(api, raw)}
    started = time.time()
    for pdf in sorted(product_dir(args.repo, args.product).glob("*.pdf")):
        if pdf.name not in listed:
            body, boundary = multipart(pdf)
            status, payload = api.raw("POST", f"/api/v1/knowledge-bases/{raw}/knowledge/file", body,
                                      f"multipart/form-data; boundary={boundary}", timeout=300)
            if status not in (200, 201):
                raise Stop(f"upload {pdf.name} -> HTTP {status}: {payload[:200]!r}")
    while True:
        items = listing(api, raw)
        states = {item["parse_status"] for item in items}
        if states <= {"completed"} and items:
            break
        if states & {"failed", "cancelled"}:
            raise Stop(f"parse failed: {sorted(states)}")
        if time.time() - started > 1800:
            raise Stop("parse did not complete in 30 min")
        time.sleep(10)
    entries = [{"knowledge_id": item["id"], "parse_attempt": item["current_parse_attempt"]}
               for item in items]
    run = args.home / "run"
    run.mkdir(exist_ok=True)
    source_map = {"space_id": SPACE_ID, "products": {args.product: entries}}
    (run / "source-map.json").write_text(json.dumps(source_map, indent=1) + "\n")
    return {"materials": len(entries), "parse_seconds": round(time.time() - started)}


def harness(args: argparse.Namespace, module: str, *argv: str) -> dict:
    """Run one Harness command from this checkout; its single JSON line is the result."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("HARNESS_")}
    env.update(HARNESS_WEKNORA_BASE_URL=args.base,
               HARNESS_WEKNORA_API_KEY=service_api(args.base, args.home).api_key,
               HARNESS_SCHEMA_FIELDS_API_KEY=model_key("deepseek"))
    python = args.repo / "harness/.venv/bin/python"
    done = subprocess.run([str(python), "-m", module, *argv], cwd=args.repo / "harness", env=env,
                          capture_output=True, text=True, timeout=3600)
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    result = json.loads(lines[-1]) if lines else {}
    if done.returncode != 0:
        summary = json.dumps(result, ensure_ascii=False)[:300]
        raise Stop(f"{module} exit {done.returncode}: {summary}")
    return result


def sends(root: Path) -> int:
    path = root / "budget.jsonl"
    if not path.exists():
        return 0
    return sum('"reserved"' in line for line in path.read_text().splitlines())


def cmd_harness(args: argparse.Namespace) -> dict:
    state, run = load_state(args.home), args.home / "run"
    registry, publication = run / "registry.json", run / "publication"
    if not registry.exists():
        harness(args, "insurance_harness.ingest.uploads", "seed", "--registry", str(registry),
                "--space", SPACE_ID, "--raw-kb", state["space"]["raw_kb_id"],
                "--source-map", str(run / "source-map.json"), "--repo", str(args.repo))
    stages = args.repo / "harness/src/insurance_harness/models/stages.json"
    # The production path with the shipped policy: compile, independent review, route.
    report = harness(args, "insurance_harness.ingest.uploads", "publish",
                     "--registry", str(registry), "--run-root", str(publication),
                     "--stage-config", str(stages),
                     "--compile-max-sent", str(COMPILE_MAX_SENT),
                     "--review-max-sent", str(REVIEW_MAX_SENT), "--products", args.product)
    if report.get("stopped") or report.get("review_stopped") or report.get("failed"):
        raise Stop(f"publication stopped: {json.dumps(report, ensure_ascii=False)[:300]}")
    pack = json.loads(registry.read_text())["products"][args.product]["schema_pack_id"]
    policy = run / "review-policy.json"
    policy.write_text(json.dumps({"version": POLICY_VERSION, "admitted_packs": [pack],
                                  "thresholds": {pack: {"default": 0.0}}}) + "\n")
    machine = harness(args, "insurance_harness.compilers.schema_fields.publish",
                      "--run-root", str(publication / "compile"), "--product", args.product,
                      "--registry", str(registry), "--route", "--review-policy", str(policy),
                      "--scores", str(publication / "review" / args.product / "scores.json"))
    state["harness"] = {"shipped_route": report.get("routes", {}).get(args.product),
                        "human_candidate": report.get("candidates", {}).get(args.product),
                        "machine_route": machine.get("review"),
                        "release_id": machine.get("release_id")}
    save_state(args.home, state)
    return {**state["harness"], "compile_sent": sends(publication / "compile"),
            "review_sent": sends(publication / "review")}


def answer(api: Api, wiki_kb: str, question: str) -> str:
    session = data(api.json("POST", "/api/v1/sessions", {"title": "I3a rehearsal"}))["id"]
    body = {"query": question, "knowledge_base_ids": [wiki_kb], "agent_enabled": False,
            "agent_id": "builtin-quick-answer", "disable_title": True, "channel": "api"}
    status, payload = api.raw("POST", f"/api/v1/knowledge-chat/{session}",
                              json.dumps(body, ensure_ascii=False).encode(), timeout=600)
    if status != 200:
        raise Stop(f"knowledge-chat -> HTTP {status}: {payload[:200]!r}")
    messages = data(api.json("GET", f"/api/v1/messages/{session}/load?limit=4")) or []
    replies = [m for m in messages if m.get("role") == "assistant"]
    return (replies[-1].get("content") or "") if replies else ""


def cmd_smoke(args: argparse.Namespace) -> dict:
    state, api = load_state(args.home), service_api(args.base, args.home)
    status, _ = Api(args.base).raw("GET", "/health")
    result: dict[str, object] = {"health": status}
    active = data(api.json("GET", f"/api/v1/enterprise/spaces/{SPACE_ID}/releases/active"))
    members = active.get("members") or []
    kinds: dict[str, int] = {}
    for member in members:
        kinds[member["kind"]] = kinds.get(member["kind"], 0) + 1
    result["active"] = {"release_id": active["id"], "epoch": active["epoch"], "members": kinds}
    match = SOURCE_REF.search(json.dumps(members, ensure_ascii=False))
    if match is None:
        raise Stop("no source reference in Active")
    path = (f"/api/v1/enterprise/spaces/{SPACE_ID}/releases/{active['id']}"
            f"/sources/{match[1]}/attempts/{match[2]}/file")
    status, payload = api.raw("GET", path, timeout=120)
    result["source_file"] = {"status": status, "pdf": payload[:5] == b"%PDF-",
                             "bytes": len(payload)}
    queue = data(api.json("GET", f"/api/v1/enterprise/spaces/{SPACE_ID}/candidates"))
    result["human_queue"] = len(queue.get("items", queue) if isinstance(queue, dict) else queue)
    result["navigation"] = harness(args, "insurance_harness.catalog.publish_navigation",
                                   "--space", SPACE_ID, "--dry-run").get("status")
    name = product_dir(args.repo, args.product).name
    reply = answer(api, state["space"]["wiki_kb_id"], QUESTION.format(name=name))
    # The question asks for the entry age, so a real answer names one ("28天"/"70周岁"); an error
    # text (no chat model, key rejected) does not.
    cites_age = bool(re.search(r"\d+\s*(周岁|天)", reply))
    result["quick_answer"] = {"chars": len(reply), "cites_age": cites_age}
    checks = [result["health"] == 200, kinds.get("claim", 0) > 0, status == 200,
              result["source_file"]["pdf"], result["navigation"] == "current", cites_age]
    result["passed"] = all(checks)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["platform", "materials", "harness", "smoke"])
    parser.add_argument("--base", required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--product", default="1818")
    args = parser.parse_args()
    if args.command != "platform" and args.repo is None:
        parser.error("--repo is required")
    command = {"platform": cmd_platform, "materials": cmd_materials, "harness": cmd_harness,
               "smoke": cmd_smoke}[args.command]
    try:
        print(json.dumps(command(args), ensure_ascii=False))
    except (Stop, KeyError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        reason = redact(f"{type(error).__name__}: {error}", args.home)[:400]
        print(json.dumps({"stopped": reason}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One local native capture; no WeKnora upload/reparse, provider, or DB call."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
PARSER = "ddb9e3bcdcd20b629ae6ea032c8474ffd87008b8a28adf8c734adaa3a45cfdb6"
REMOTE = "/tmp/g3-native-02-supplement-5e2aef32"


def main():
    spec = importlib.util.spec_from_file_location("native_preflight", HERE / "native_preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SCRATCH = Path("/private/tmp/g3-native-02-supplement-5e2aef32")
    module.SCRATCH.mkdir(mode=0o700, exist_ok=True)
    receipt = HERE / "native-02-supplement-result.json"
    with receipt.open("x") as handle:
        json.dump({"status": "STARTED", "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "provider_calls": 0, "knowledge_uploads": 0, "knowledge_reparses": 0}, handle)
    raw = (ROOT / "dataset/version-materials/esb_zunxiang_596-1_shuomingshu.pdf").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    identity = json.loads(module.docker("inspect", "--format", '{"Image":{{json .Image}},"Id":{{json .Id}},"Running":{{json .State.Running}}}', module.CONTAINER))
    assert identity["Image"] == module.IMAGE and identity["Running"] is True
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        member = tarfile.TarInfo("g3-material-02.pdf")
        member.size, member.mode = len(raw), 0o600
        tar.addfile(member, io.BytesIO(raw))
    module.docker("exec", module.CONTAINER, "mkdir", REMOTE)
    module.docker("exec", "-i", module.CONTAINER, "tar", "xf", "-", "-C", REMOTE, data=archive.getvalue())
    source = '''import socket,pathlib,json,hashlib,gzip
def deny(*args,**kwargs): raise RuntimeError("NETWORK_DISABLED_IN_LOCAL_PREFLIGHT")
socket.socket.connect=deny
socket.socket.connect_ex=deny
from docreader.parser.pdf_parser import PDFParser
p=pathlib.Path("/tmp/g3-native-02-supplement-5e2aef32/g3-material-02.pdf")
raw=p.read_bytes()
assert hashlib.sha256(raw).hexdigest()=="5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
doc=PDFParser(file_name=p.name,file_type="pdf",pdf_native_structure_capture="builtin-pdfium-charbox-v1").parse_into_text(raw)
env=json.loads(doc.metadata["native_structure_artifact_v1"])
value={"metadata":env,"markdown":doc.content}
encoded=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
out=p.with_name("g3-material-02-native.json.gz")
out.write_bytes(gzip.compress(encoded,mtime=0))
print("G3_CAPTURE "+hashlib.sha256(out.read_bytes()).hexdigest(),flush=True)
'''
    log = module.docker("exec", "-i", module.CONTAINER, "python", "-", data=source.encode(), timeout=180)
    (module.SCRATCH / "parser.private.log").write_bytes(log)
    expected = next(line.removeprefix("G3_CAPTURE ") for line in log.decode().splitlines() if line.startswith("G3_CAPTURE "))
    capture = module.docker("exec", module.CONTAINER, "cat", REMOTE + "/g3-material-02-native.json.gz")
    assert hashlib.sha256(capture).hexdigest() == expected
    value = json.loads(gzip.decompress(capture)); env = value["metadata"]; native = env["sanitized_json"]
    canonical = json.dumps(native, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == env["sanitized_sha256"]
    assert native["source_sha256"] == SHA and native["parser_identity_sha256"] == PARSER
    assert hashlib.sha256(value["markdown"].encode()).hexdigest() == native["markdown_sha256"]
    assert len(native["pages"]) == 27
    output = HERE / "inputs/existing-native-captures/g3-material-02-native.json.gz"
    with output.open("xb") as handle:
        handle.write(capture)
    result = {"contract": "830-g3-native-02-supplement.v1", "status": "PASS", "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "container": identity, "material_id": "g3-material-02", "capture_path": str(output.relative_to(ROOT)), "capture_sha256": expected, "source_sha256": SHA, "canonical_native_sha256": env["sanitized_sha256"], "markdown_sha256": native["markdown_sha256"], "parser_identity_sha256": PARSER, "pages": 27, "provider_calls": 0, "knowledge_uploads": 0, "knowledge_reparses": 0, "db_writes": 0, "flow": "NOT RUN", "scope": "Actual local native capture only; current service source receipt still required"}
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

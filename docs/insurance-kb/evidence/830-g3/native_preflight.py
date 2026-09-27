"""Bounded local parser reuse; no uploads, source sealing, or provider calls."""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import subprocess
import tarfile

if not __debug__:
    raise RuntimeError("Optimized execution forbidden")

ROOT = pathlib.Path(__file__).resolve().parents[4]
EVIDENCE = pathlib.Path(__file__).resolve().parent
CORPUS = EVIDENCE / "corpus-files-v3.json"
EXPECTED_SET = "7fc60c849ca26dd038f94fa4b2d0af4cfe4aa3d8f330eb9d8c28eda39f1a3145"
IMAGE = "sha256:ac944d934fcd30c77e4ff28d19f1b4d6dd147012a6553c4678274c1f0be35868"
CONTAINER = "weknora-g2-594-docreader"
SCRATCH = pathlib.Path("/private/tmp/g3-native-preflight-7fc60c849ca2")
REMOTE = "/tmp/g3-native-preflight-7fc60c849ca2"


def docker(*args: str, data: bytes | None = None, timeout: int = 45) -> bytes:
    result = subprocess.run(
        ["colima", "ssh", "--profile", "default", "--", "sudo", "docker", *args],
        input=data, capture_output=True, timeout=timeout, check=False,
    )
    if result.returncode:
        (SCRATCH / "error.private.log").write_bytes(result.stdout + result.stderr)
        raise RuntimeError("Local parser preflight failed; private diagnostics retained")
    return result.stdout


def main() -> None:
    SCRATCH.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt_path = EVIDENCE / "native-preflight-result.json"
    if receipt_path.exists():
        raise RuntimeError("Preflight receipt already exists; no silent rerun")
    corpus = json.loads(CORPUS.read_text())
    wire = json.dumps(corpus["entries"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(wire).hexdigest() == corpus["file_set_sha256"] == EXPECTED_SET
    documents = [entry for entry in corpus["entries"] if entry["source_revision_status"] == "NOT_YET_CAPTURED"]
    assert len(documents) == 11
    identity = json.loads(docker("inspect", "--format", '{"Image":{{json .Image}},"Id":{{json .Id}},"State":{"Running":{{json .State.Running}}}}', CONTAINER))
    assert identity["Image"] == IMAGE and identity["State"]["Running"] is True
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for entry in documents:
            raw = (ROOT / entry["path"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == entry["file_sha256"]
            member = tarfile.TarInfo(entry["inventory_id"] + ".pdf")
            member.size, member.mode = len(raw), 0o600
            tar.addfile(member, io.BytesIO(raw))
    docker("exec", CONTAINER, "mkdir", "-p", REMOTE)
    docker("exec", "-i", CONTAINER, "tar", "xf", "-", "-C", REMOTE, data=archive.getvalue())
    source = '''import socket,pathlib,json,hashlib,gzip
def deny(*args,**kwargs): raise RuntimeError("NETWORK_DISABLED_IN_LOCAL_PREFLIGHT")
socket.socket.connect=deny
socket.socket.connect_ex=deny
from docreader.parser.pdf_parser import PDFParser
directory=pathlib.Path("/tmp/g3-native-preflight-7fc60c849ca2")
results=[]
for path in sorted(directory.glob("g3-material-*.pdf")):
 raw=path.read_bytes()
 doc=PDFParser(file_name=path.name,file_type="pdf",pdf_native_structure_capture="builtin-pdfium-charbox-v1").parse_into_text(raw)
 envelope=json.loads(doc.metadata["native_structure_artifact_v1"])
 content={"metadata":envelope,"markdown":doc.content}
 encoded=json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
 output=directory/(path.stem+"-native.json.gz")
 output.write_bytes(gzip.compress(encoded,mtime=0))
 row={"material_id":path.stem,"file_sha256":hashlib.sha256(raw).hexdigest(),"pages":len(envelope["sanitized_json"]["pages"]),"markdown_utf8_bytes":len(doc.content.encode()),"markdown_sha256":hashlib.sha256(doc.content.encode()).hexdigest(),"native_sha256":envelope["sanitized_sha256"],"parser_identity_sha256":envelope["sanitized_json"]["parser_identity_sha256"],"capture_file_sha256":hashlib.sha256(output.read_bytes()).hexdigest()}
 results.append(row)
 print("G3_DOCUMENT "+json.dumps(row),flush=True)
print("G3_RESULT "+json.dumps(results),flush=True)
'''
    output = docker("exec", "-i", CONTAINER, "python", "-", data=source.encode(), timeout=300)
    (SCRATCH / "parser.private.log").write_bytes(output)
    results = json.loads(next(line.removeprefix("G3_RESULT ") for line in output.decode().splitlines() if line.startswith("G3_RESULT ")))
    assert len(results) == 11
    expected = {entry["inventory_id"]: entry for entry in documents}
    for row in results:
        entry = expected[row["material_id"]]
        assert row["file_sha256"] == entry["file_sha256"] and row["pages"] == entry["pages"]
    capture_archive = docker("exec", CONTAINER, "tar", "czf", "-", "-C", REMOTE, *[row["material_id"] + "-native.json.gz" for row in results])
    (SCRATCH / "native-captures.tar.gz").write_bytes(capture_archive)
    capture_set = [{"material_id": row["material_id"], "capture_file_sha256": row["capture_file_sha256"]} for row in sorted(results, key=lambda row: row["material_id"])]
    capture_set_hash = hashlib.sha256(json.dumps(capture_set, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = {"contract": "830-g3-local-native-preflight.v1", "status": "PASS", "corpus_file_set_sha256": EXPECTED_SET, "container_id": identity["Id"], "image_id": IMAGE, "documents": results, "capture_set_sha256": capture_set_hash, "run_local_scratch_archive_sha256": hashlib.sha256(capture_archive).hexdigest(), "archive_hash_scope": "Exact bytes retained from this run, not a deterministic tar identity; use capture_set_sha256 for stable membership", "scratch_archive": str(SCRATCH / "native-captures.tar.gz"), "provider_calls": 0, "knowledge_uploads": 0, "source_revisions_created": 0, "db_writes": 0, "builds": 0, "network_disabled_in_parser_process": True, "flow": "NOT RUN", "meaning": "Actual existing local Docreader parse preflight only; not uploaded WeKnora SourceRevision or G3 batch outcome"}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "documents": len(results), "provider_calls": 0, "source_revisions_created": 0}))


if __name__ == "__main__":
    main()

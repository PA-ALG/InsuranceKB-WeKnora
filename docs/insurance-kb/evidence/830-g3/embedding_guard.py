"""One-run G3 upload boundary. No product service, credentials, or automatic retries."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import urllib.error
import urllib.request

UPSTREAM = 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings'
LIMIT = 11


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Guard:
    def __init__(self, ledger: Path, allowed: dict[str, dict[str, str]], manifest_sha: str, send=None):
        if len(allowed) != LIMIT or len({x['source_sha256'] for x in allowed.values()}) != LIMIT:
            raise ValueError('EXACT_ELEVEN_DISTINCT_SOURCES_REQUIRED')
        self.path = Path(ledger)
        try:
            reserved = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise RuntimeError('EXISTING_LEDGER_NO_AUTOMATIC_RESUME') from error
        # A failed or interrupted initializer retains its reservation: never auto-resume.
        try:
            os.fsync(reserved)
        finally:
            os.close(reserved)
        self.sync_directory()
        self.allowed = allowed
        self.lock = threading.Lock()
        self.send = send or self.forward
        self.data = {'contract': '830-g3-embedding-attempts.v1', 'upstream': UPSTREAM,
                     'manifest_sha256': manifest_sha, 'max_attempts': LIMIT,
                     'stopped': False, 'attempts': []}
        self.save()

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        with tmp.open('w') as f:
            os.chmod(tmp, 0o600)
            json.dump(self.data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        self.sync_directory()

    def sync_directory(self):
        directory = os.open(str(self.path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def save_or_stop(self):
        try:
            self.save()
            return True
        except Exception as error:
            self.data['stopped'] = True
            self.data['accounting_error_type'] = type(error).__name__
            # One best-effort stop receipt; memory remains stopped even if disk is unavailable.
            try:
                self.save()
            except Exception:
                pass
            return False

    def forward(self, raw: bytes, authorization: str):
        request = urllib.request.Request(UPSTREAM, data=raw, headers={
            'Authorization': authorization, 'Content-Type': 'application/json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def request(self, raw: bytes, authorization: str):
        digest = sha(raw)
        document = self.allowed.get(digest)
        if document is None:
            return 403, b'{"error":"outside_exact_G3_body"}'
        if not authorization.startswith('Bearer ') or len(authorization) <= 7:
            return 401, b'{"error":"missing_authorization"}'
        with self.lock:
            if self.data['stopped']:
                return 409, b'{"error":"G3_run_stopped_after_failure"}'
            if any(row['request_sha256'] == digest for row in self.data['attempts']):
                return 409, b'{"error":"G3_source_already_attempted"}'
            if len(self.data['attempts']) >= LIMIT:
                return 429, b'{"error":"G3_attempt_budget_exhausted"}'
            row = {'attempt': len(self.data['attempts']) + 1, 'request_sha256': digest,
                   'source_sha256': document['source_sha256'],
                   'material_id': document['material_id'], 'status': 'STARTED'}
            self.data['attempts'].append(row)
            if not self.save_or_stop():
                return 503, b'{"error":"G3_accounting_failed_run_stopped"}'
            try:
                status, body = self.send(raw, authorization)
                row.update(status='RESPONSE', http_status=status, response_sha256=sha(body))
            except Exception as error:
                status, body = 502, b'{"error":"upstream_transport_failed"}'
                row.update(status='TRANSPORT_FAILED', error_type=type(error).__name__)
            if status != 200:
                self.data['stopped'] = True
            if not self.save_or_stop():
                return 503, b'{"error":"G3_accounting_failed_run_stopped"}'
            return status, body


def load_allowed(root: Path, manifest_path: Path, expected_sha: str):
    raw = manifest_path.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError('FROZEN_MANIFEST_DRIFT')
    manifest = json.loads(raw)
    if (manifest['contract'] != '830-g3-prepared-embedding-transport.v1'
            or manifest['upstream'] != UPSTREAM or manifest['provider_calls'] != 0
            or manifest['batch_embed_size'] != 100):
        raise ValueError('WRONG_TRANSPORT_MANIFEST')
    allowed = {}
    for row in manifest['requests']:
        path = (root / row['persisted_path']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('REQUEST_OUTSIDE_FROZEN_ROOT')
        body = path.read_bytes()
        if sha(body) != row['request_sha256'] or len(body) != row['body_bytes']:
            raise ValueError('FROZEN_BODY_DRIFT')
        value = json.loads(body)
        if (set(value) != {'model', 'input', 'encoding_format', 'truncate_prompt_tokens'}
                or value['model'] != 'qwen3.7-text-embedding'
                or value['encoding_format'] != 'float' or value['truncate_prompt_tokens'] != 511
                or len(value['input']) != row['input_count'] or not 1 <= len(value['input']) <= 100
                or not all(isinstance(item, str) for item in value['input'])
                or row['request_sha256'] in allowed):
            raise ValueError('FROZEN_BODY_SHAPE')
        allowed[row['request_sha256']] = {k: row[k] for k in ('source_sha256', 'material_id')}
    return allowed


def serve(root: Path, manifest: Path, expected_sha: str, ledger: Path):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    guard = Guard(ledger, load_allowed(root, manifest, expected_sha), expected_sha)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.client_address[0] != '127.0.0.1' or self.path != '/compatible-mode/v1/embeddings':
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.send_error(400)
                return
            if not 0 < length <= 1_000_000:
                self.send_error(413)
                return
            status, body = guard.request(self.rfile.read(length), self.headers.get('Authorization', ''))
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(('127.0.0.1', 19030), Handler)
    timer = threading.Timer(1800, server.shutdown)
    timer.start()
    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()


if __name__ == '__main__':
    import sys
    os.umask(0o077)
    if len(sys.argv) != 5:
        raise SystemExit('Expected frozen root, manifest, manifest SHA, new ledger path')
    serve(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))

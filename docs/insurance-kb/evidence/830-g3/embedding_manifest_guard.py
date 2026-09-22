"""Manifest-sized G3 embedding boundary, derived from the reviewed permutation guard.

Each exact manifest authorizes only its named source bodies. The per-document
split, durable attempt ledger, isolated sender and no-retry behavior are reused.
"""
from __future__ import annotations

import base64
import binascii
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
from typing import Any, BinaryIO, Callable
import urllib.error
import urllib.request

UPSTREAM = 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings'
MAX_PROVIDER_INPUTS = 20
MATERIAL_TIMEOUT_SECONDS = 50.0
CHILD_CLEANUP_SECONDS = 5.0
MAX_REQUEST_BYTES = 1_000_000
MAX_AUTH_BYTES = 8192
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
VECTOR_DIMENSIONS = 1024



def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise ValueError('NONFINITE_JSON_NUMBER')


def strict_json(raw: bytes) -> Any:
    try:
        text = raw.decode('utf-8', errors='strict')
        return json.loads(text, object_pairs_hook=_no_duplicate_object,
                          parse_constant=_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('INVALID_JSON') from error


def go_json(value: Any) -> bytes:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                          allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError('UNENCODABLE_JSON') from error
    for literal, escaped in (
        ('&', r'\u0026'), ('<', r'\u003c'), ('>', r'\u003e'),
        ('\u2028', r'\u2028'), ('\u2029', r'\u2029'),
    ):
        text = text.replace(literal, escaped)
    return text.encode('utf-8')


def _request_shape(value: Any) -> list[str]:
    if not isinstance(value, dict) or set(value) != {
        'model', 'input', 'encoding_format', 'truncate_prompt_tokens',
    }:
        raise ValueError('REQUEST_SHAPE')
    if (type(value['model']) is not str
            or type(value['encoding_format']) is not str
            or type(value['truncate_prompt_tokens']) is not int
            or value['model'] != 'qwen3.7-text-embedding'
            or value['encoding_format'] != 'float'
            or value['truncate_prompt_tokens'] != 511
            or type(value['input']) is not list
            or not 1 <= len(value['input']) <= 100
            or not all(type(item) is str for item in value['input'])):
        raise ValueError('REQUEST_SHAPE')
    return value['input']


def _signature(inputs: list[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(inputs).items()))


def _multiset_sha(signature: tuple[tuple[str, int], ...]) -> str:
    return sha(json.dumps(signature, ensure_ascii=False, separators=(',', ':'),
                          allow_nan=False).encode('utf-8'))


def _part_bodies(value: dict[str, Any]) -> list[bytes]:
    inputs = value['input']
    result = []
    for start in range(0, len(inputs), MAX_PROVIDER_INPUTS):
        result.append(_request_wire(value, inputs[start:start + MAX_PROVIDER_INPUTS]))
    return result


def _request_wire(value: dict[str, Any], inputs: list[str] | None = None) -> bytes:
    """Rebuild encoding/json's fixed OpenAIEmbedRequest field order."""
    return go_json({
        'model': value['model'],
        'input': value['input'] if inputs is None else inputs,
        'encoding_format': value['encoding_format'],
        'truncate_prompt_tokens': value['truncate_prompt_tokens'],
    })


def load_allowed(root: Path, manifest_path: Path, expected_sha: str) -> dict[str, dict[str, Any]]:
    raw = manifest_path.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError('FROZEN_MANIFEST_DRIFT')
    manifest = strict_json(raw)
    if (not isinstance(manifest, dict)
            or manifest.get('contract') != '830-g3-prepared-embedding-transport.v2'
            or manifest.get('upstream') != UPSTREAM
            or manifest.get('provider_calls') != 0
            or manifest.get('batch_embed_size') != 100
            or type(manifest.get('requests')) is not list
            or not 1 <= len(manifest['requests']) <= 1000):
        raise ValueError('WRONG_TRANSPORT_MANIFEST')

    allowed: dict[str, dict[str, Any]] = {}
    signatures: set[tuple[tuple[str, int], ...]] = set()
    source_ids: set[str] = set()
    material_ids: set[str] = set()
    total_inputs = total_frozen_bytes = total_parts = total_part_bytes = 0
    root = root.resolve()
    for row in manifest['requests']:
        if not isinstance(row, dict):
            raise ValueError('WRONG_TRANSPORT_MANIFEST')
        try:
            persisted = row['persisted_path']
            request_sha = row['request_sha256']
            source_sha = row['source_sha256']
            material_id = row['material_id']
            body_bytes = row['body_bytes']
            input_count = row['input_count']
        except KeyError as error:
            raise ValueError('WRONG_TRANSPORT_MANIFEST') from error
        if (type(persisted) is not str or type(request_sha) is not str
                or type(source_sha) is not str or type(material_id) is not str
                or type(body_bytes) is not int or type(input_count) is not int
                or len(request_sha) != 64 or len(source_sha) != 64):
            raise ValueError('WRONG_TRANSPORT_MANIFEST')
        path = (root / persisted).resolve()
        if not path.is_relative_to(root):
            raise ValueError('REQUEST_OUTSIDE_FROZEN_ROOT')
        body = path.read_bytes()
        if sha(body) != request_sha or len(body) != body_bytes:
            raise ValueError('FROZEN_BODY_DRIFT')
        value = strict_json(body)
        inputs = _request_shape(value)
        if _request_wire(value) != body or len(inputs) != input_count:
            raise ValueError('FROZEN_BODY_SHAPE')
        signature = _signature(inputs)
        if (signature in signatures or request_sha in allowed
                or source_sha in source_ids or material_id in material_ids):
            raise ValueError('AMBIGUOUS_OR_DUPLICATE_FROZEN_SOURCE')
        part_bodies = _part_bodies(value)
        part_bytes = sum(map(len, part_bodies))
        document = {
            'material_id': material_id,
            'source_sha256': source_sha,
            'frozen_request_sha256': request_sha,
            'body_bytes': body_bytes,
            'input_count': input_count,
            'signature': signature,
            'input_multiset_sha256': _multiset_sha(signature),
            'part_count': len(part_bodies),
            'part_bytes': part_bytes,
        }
        allowed[request_sha] = document
        signatures.add(signature)
        source_ids.add(source_sha)
        material_ids.add(material_id)
        total_inputs += input_count
        total_frozen_bytes += body_bytes
        total_parts += len(part_bodies)
        total_part_bytes += part_bytes
    if (type(manifest.get('max_materials')) is not int
            or type(manifest.get('max_attempts')) is not int
            or manifest['max_materials'] != len(allowed)
            or manifest['max_attempts'] != total_parts):
        raise ValueError('FROZEN_MANIFEST_BUDGET_MISMATCH')
    return allowed


def _validate_allowed(allowed: dict[str, dict[str, Any]]) -> dict[tuple[tuple[str, int], ...], dict[str, Any]]:
    if type(allowed) is not dict or not 1 <= len(allowed) <= 1000:
        raise ValueError('NONEMPTY_DISTINCT_SOURCES_REQUIRED')
    index: dict[tuple[tuple[str, int], ...], dict[str, Any]] = {}
    materials: set[str] = set()
    sources: set[str] = set()
    for frozen_sha, document in allowed.items():
        if (type(frozen_sha) is not str or not isinstance(document, dict)
                or document.get('frozen_request_sha256') != frozen_sha):
            raise ValueError('INVALID_ALLOWED_SOURCE')
        signature = document.get('signature')
        material = document.get('material_id')
        source = document.get('source_sha256')
        if (not isinstance(signature, tuple) or signature in index
                or type(material) is not str or material in materials
                or type(source) is not str or source in sources):
            raise ValueError('AMBIGUOUS_OR_DUPLICATE_FROZEN_SOURCE')
        index[signature] = document
        materials.add(material)
        sources.add(source)
    return index


def _remaining(deadline: float, clock: Callable[[], float]) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError('MATERIAL_DEADLINE')
    return remaining


def _finite_float32(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
        if not math.isfinite(number):
            return False
        return math.isfinite(struct.unpack('!f', struct.pack('!f', number))[0])
    except (OverflowError, struct.error, ValueError):
        return False


def _validated_part_data(raw: bytes, count: int, input_start: int) -> list[dict[str, Any]]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError('RESPONSE_TOO_LARGE')
    value = strict_json(raw)
    if not isinstance(value, dict) or type(value.get('data')) is not list:
        raise ValueError('INVALID_PROVIDER_RESPONSE')
    data = value['data']
    if len(data) != count:
        raise ValueError('INVALID_PROVIDER_RESPONSE')
    by_index: dict[int, list[Any]] = {}
    for row in data:
        if not isinstance(row, dict) or type(row.get('index')) is not int:
            raise ValueError('INVALID_PROVIDER_RESPONSE')
        index = row['index']
        embedding = row.get('embedding')
        if (index in by_index or not 0 <= index < count
                or type(embedding) is not list or len(embedding) != VECTOR_DIMENSIONS
                or not all(_finite_float32(item) for item in embedding)):
            raise ValueError('INVALID_PROVIDER_RESPONSE')
        by_index[index] = embedding
    if set(by_index) != set(range(count)):
        raise ValueError('INVALID_PROVIDER_RESPONSE')
    return [{'embedding': by_index[index], 'index': input_start + index}
            for index in range(count)]


def _frame(authorization: str, raw: bytes) -> bytes:
    if type(authorization) is not str:
        raise ValueError('INVALID_AUTHORIZATION')
    auth = authorization.encode('utf-8')
    if (not 1 <= len(auth) <= MAX_AUTH_BYTES or not authorization.startswith('Bearer ')
            or len(authorization) <= 7 or any(char in authorization for char in '\r\n\0')
            or not 1 <= len(raw) <= MAX_REQUEST_BYTES):
        raise ValueError('INVALID_FORWARD_FRAME')
    return struct.pack('!I', len(auth)) + auth + struct.pack('!I', len(raw)) + raw


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    result = stream.read(length)
    if result is None or len(result) != length:
        raise ValueError('SHORT_FORWARD_FRAME')
    return result


def _read_frame(stream: BinaryIO) -> tuple[str, bytes]:
    auth_length = struct.unpack('!I', _read_exact(stream, 4))[0]
    if not 1 <= auth_length <= MAX_AUTH_BYTES:
        raise ValueError('INVALID_FORWARD_FRAME')
    auth_raw = _read_exact(stream, auth_length)
    request_length = struct.unpack('!I', _read_exact(stream, 4))[0]
    if not 1 <= request_length <= MAX_REQUEST_BYTES:
        raise ValueError('INVALID_FORWARD_FRAME')
    request = _read_exact(stream, request_length)
    if stream.read(1) != b'':
        raise ValueError('EXTRA_FORWARD_FRAME')
    try:
        authorization = auth_raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError as error:
        raise ValueError('INVALID_FORWARD_FRAME') from error
    _frame(authorization, request)
    return authorization, request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _bounded_read(response: Any) -> bytes:
    body: bytes = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError('RESPONSE_TOO_LARGE')
    return body


def forward_once(stdin: BinaryIO, stdout: BinaryIO, opener: Any | None = None) -> None:
    authorization, raw = _read_frame(stdin)
    request = urllib.request.Request(UPSTREAM, data=raw, headers={
        'Authorization': authorization, 'Content-Type': 'application/json'})
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=MATERIAL_TIMEOUT_SECONDS) as response:
            status, body = response.status, _bounded_read(response)
    except urllib.error.HTTPError as error:
        with error:
            status, body = error.code, _bounded_read(error)
    envelope = {'status': status, 'body_base64': base64.b64encode(body).decode('ascii')}
    if type(status) is not int or not 100 <= status <= 599:
        raise ValueError('INVALID_HTTP_STATUS')
    stdout.write(go_json(envelope))


class SubprocessSender:
    def __init__(self, popen: Callable[..., Any] = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic):
        self.popen = popen
        self.clock = clock

    @staticmethod
    def _kill_and_reap(child: Any) -> None:
        child.kill()
        try:
            child.communicate(timeout=CHILD_CLEANUP_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise TimeoutError('FORWARD_CHILD_REAP_FAILED') from error

    def __call__(self, raw: bytes, authorization: str, timeout: float) -> tuple[int, bytes]:
        deadline = self.clock() + timeout
        child = self.popen(
            [sys.executable, str(Path(__file__).resolve()), '--forward-once'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                 'PYTHONDONTWRITEBYTECODE': '1'},
        )
        try:
            remaining = _remaining(deadline, self.clock)
        except TimeoutError:
            self._kill_and_reap(child)
            raise
        try:
            output, _ = child.communicate(
                input=_frame(authorization, raw), timeout=remaining)
        except subprocess.TimeoutExpired as error:
            self._kill_and_reap(child)
            raise TimeoutError('FORWARD_CHILD_TIMEOUT') from error
        _remaining(deadline, self.clock)
        if child.returncode != 0 or len(output) > (MAX_RESPONSE_BYTES * 2):
            raise RuntimeError('FORWARD_CHILD_FAILED')
        envelope = strict_json(output)
        if (not isinstance(envelope, dict)
                or set(envelope) != {'status', 'body_base64'}
                or type(envelope['status']) is not int
                or not 100 <= envelope['status'] <= 599
                or type(envelope['body_base64']) is not str
                or go_json(envelope) != output):
            raise RuntimeError('INVALID_FORWARD_CHILD_RESPONSE')
        try:
            body = base64.b64decode(envelope['body_base64'], validate=True)
        except (ValueError, binascii.Error) as error:
            raise RuntimeError('INVALID_FORWARD_CHILD_RESPONSE') from error
        if (len(body) > MAX_RESPONSE_BYTES
                or base64.b64encode(body).decode('ascii') != envelope['body_base64']):
            raise RuntimeError('INVALID_FORWARD_CHILD_RESPONSE')
        _remaining(deadline, self.clock)
        status: int = envelope['status']
        return status, body


class Guard:
    def __init__(self, ledger: Path, allowed: dict[str, dict[str, Any]], manifest_sha: str,
                 send: Callable[[bytes, str, float], tuple[int, bytes]] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.by_signature = _validate_allowed(allowed)
        self.path = Path(ledger)
        try:
            reserved = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise RuntimeError('EXISTING_LEDGER_NO_AUTOMATIC_RESUME') from error
        try:
            os.fsync(reserved)
        finally:
            os.close(reserved)
        self.sync_directory()
        self.lock = threading.Lock()
        self.send = send or SubprocessSender()
        self.clock = clock
        self.data: dict[str, Any] = {
            'contract': '830-g3-embedding-attempts.v2', 'upstream': UPSTREAM,
            'manifest_sha256': manifest_sha,
            'max_attempts': sum(d['part_count'] for d in allowed.values()),
            'max_materials': len(allowed), 'stopped': False,
            'materials': [], 'attempts': [],
        }
        self.save()

    def save(self) -> None:
        tmp = self.path.with_suffix('.tmp')
        with tmp.open('w') as handle:
            os.chmod(tmp, 0o600)
            json.dump(self.data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        self.sync_directory()

    def sync_directory(self) -> None:
        directory = os.open(str(self.path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def save_or_stop(self) -> bool:
        try:
            self.save()
            return True
        except Exception as error:
            self.data['stopped'] = True
            self.data['accounting_error_type'] = type(error).__name__
            try:
                self.save()
            except Exception:
                pass
            return False

    def _stop(self, material: dict[str, Any], status: str, error_type: str,
              http_status: int | None = None) -> None:
        material['status'] = status
        material['error_type'] = error_type
        if http_status is not None:
            material['http_status'] = http_status
        self.data['stopped'] = True
        self.save_or_stop()

    def _admit(self, raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
        if not 1 <= len(raw) <= MAX_REQUEST_BYTES:
            raise ValueError('REQUEST_SIZE')
        value = strict_json(raw)
        inputs = _request_shape(value)
        if _request_wire(value) != raw:
            raise ValueError('NONCANONICAL_REQUEST_WIRE')
        document = self.by_signature.get(_signature(inputs))
        if document is None or len(raw) != document['body_bytes']:
            raise ValueError('OUTSIDE_FROZEN_SOURCE')
        return value, document

    def request(self, raw: bytes, authorization: str) -> tuple[int, bytes]:
        try:
            value, document = self._admit(raw)
        except ValueError:
            return 403, b'{"error":"outside_exact_G3_body"}'
        try:
            _frame(authorization, raw)
        except ValueError:
            return 401, b'{"error":"missing_authorization"}'

        with self.lock:
            if self.data['stopped']:
                return 409, b'{"error":"G3_run_stopped_after_failure"}'
            if any(row['source_sha256'] == document['source_sha256']
                   for row in self.data['materials']):
                return 409, b'{"error":"G3_source_already_attempted"}'
            if (len(self.data['materials']) >= self.data['max_materials']
                    or len(self.data['attempts']) >= self.data['max_attempts']):
                return 429, b'{"error":"G3_attempt_budget_exhausted"}'

            deadline = self.clock() + MATERIAL_TIMEOUT_SECONDS
            part_bodies = _part_bodies(value)
            if (len(part_bodies) != document['part_count']
                    or sum(map(len, part_bodies)) != document['part_bytes']):
                return 403, b'{"error":"outside_exact_G3_body"}'
            material: dict[str, Any] = {
                'material_id': document['material_id'],
                'source_sha256': document['source_sha256'],
                'frozen_request_sha256': document['frozen_request_sha256'],
                'actual_request_sha256': sha(raw),
                'input_multiset_sha256': document['input_multiset_sha256'],
                'part_count': len(part_bodies), 'status': 'STARTED',
            }
            self.data['materials'].append(material)
            if not self.save_or_stop():
                return 503, b'{"error":"G3_accounting_failed_run_stopped"}'

            assembled: list[dict[str, Any]] = []
            input_start = 0
            for part_index, part_raw in enumerate(part_bodies):
                try:
                    remaining = _remaining(deadline, self.clock)
                except TimeoutError as error:
                    self._stop(material, 'TRANSPORT_FAILED', type(error).__name__)
                    return 502, b'{"error":"upstream_transport_failed"}'
                part_value = strict_json(part_raw)
                part_count = len(_request_shape(part_value))
                attempt: dict[str, Any] = {
                    'attempt': len(self.data['attempts']) + 1,
                    'material_id': document['material_id'],
                    'source_sha256': document['source_sha256'],
                    'part_index': part_index, 'input_start': input_start,
                    'input_end': input_start + part_count,
                    'request_sha256': sha(part_raw), 'status': 'STARTED',
                }
                self.data['attempts'].append(attempt)
                if not self.save_or_stop():
                    material['status'] = 'STOPPED'
                    return 503, b'{"error":"G3_accounting_failed_run_stopped"}'
                try:
                    remaining = _remaining(deadline, self.clock)
                    status, body = self.send(part_raw, authorization, remaining)
                    _remaining(deadline, self.clock)
                except Exception as error:
                    attempt.update(status='TRANSPORT_FAILED', error_type=type(error).__name__)
                    self._stop(material, 'TRANSPORT_FAILED', type(error).__name__)
                    return 502, b'{"error":"upstream_transport_failed"}'
                attempt.update(status='RESPONSE', http_status=status,
                               response_sha256=sha(body))
                if status != 200:
                    self._stop(material, 'STOPPED', 'UPSTREAM_HTTP_ERROR', status)
                    return status, body
                try:
                    assembled.extend(_validated_part_data(body, part_count, input_start))
                except ValueError:
                    attempt['error_type'] = 'INVALID_PROVIDER_RESPONSE'
                    self._stop(material, 'STOPPED', 'INVALID_PROVIDER_RESPONSE')
                    return 502, b'{"error":"invalid_provider_response"}'
                if not self.save_or_stop():
                    material['status'] = 'STOPPED'
                    return 503, b'{"error":"G3_accounting_failed_run_stopped"}'
                input_start += part_count

            response = go_json({'data': assembled})
            try:
                _remaining(deadline, self.clock)
            except TimeoutError as error:
                self._stop(material, 'TRANSPORT_FAILED', type(error).__name__)
                return 502, b'{"error":"upstream_transport_failed"}'
            material.update(status='RESPONSE', http_status=200,
                            aggregate_response_sha256=sha(response))
            if not self.save_or_stop():
                return 503, b'{"error":"G3_accounting_failed_run_stopped"}'
            try:
                _remaining(deadline, self.clock)
            except TimeoutError as error:
                self._stop(material, 'TRANSPORT_FAILED', type(error).__name__)
                return 502, b'{"error":"upstream_transport_failed"}'
            return 200, response


def serve(root: Path, manifest: Path, expected_sha: str, ledger: Path) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    guard = Guard(ledger, load_allowed(root, manifest, expected_sha), expected_sha)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            if self.client_address[0] != '127.0.0.1' or self.path != '/compatible-mode/v1/embeddings':
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.send_error(400)
                return
            if not 0 < length <= MAX_REQUEST_BYTES:
                self.send_error(413)
                return
            status, body = guard.request(
                self.rfile.read(length), self.headers.get('Authorization', ''))
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(('127.0.0.1', 19030), Handler)
    timer = threading.Timer(1440, server.shutdown)
    timer.start()
    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()


if __name__ == '__main__':
    os.umask(0o077)
    if sys.argv[1:] == ['--forward-once']:
        forward_once(sys.stdin.buffer, sys.stdout.buffer)
    elif len(sys.argv) == 5:
        serve(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
    else:
        raise SystemExit('Expected --forward-once or frozen root, manifest, SHA, ledger path')

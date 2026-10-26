"""Frozen train-only literal-span GPT broker, localhost8122; no ordinary-policy changes."""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import uuid


def validate_body(body, requests):
    from src.train_span_proposer import MODE
    if (not isinstance(body, dict) or set(body) != {'mode', 'initial_state_id', 'trial_id', 'request'}
            or body['mode'] != MODE or type(body['trial_id']) is not int or body['trial_id'] not in range(1, 9)
            or body['initial_state_id'] not in requests
            or json.dumps(requests[body['initial_state_id']]) != json.dumps(body['request'])):
        raise ValueError('Only exact frozen context and eight fresh declared trials are accepted')
    return body['initial_state_id'], body['trial_id']


def serve(args):
    bundle = args.collection.resolve().parent
    sys.path.insert(0, str(bundle / 'interface'))
    from src.train_span_bundle import load_bundle, validate_tokenizer
    from src.train_span_cli import run_cli, save
    from src.train_span_proposer import MODE, ROLE, VERSION
    manifest = load_bundle(args.collection)
    validate_tokenizer(args.tokenizer, bundle)
    if Path(__file__).read_bytes() != (bundle / 'interface/broker.py').read_bytes():
        raise ValueError('Run the exact frozen span broker')
    requests = {row['initial_state_id']: json.loads((bundle / row['teacher_request']).read_text()) for row in manifest['contexts']}
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(args.tokenizer), local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != 151645: raise ValueError('Unexpected pinned Qwen tokenizer EOS')
    executable = shutil.which(os.environ.get('GPT_CLI', 'gpt-cli'))
    if not executable: raise ValueError('The authenticated existing GPT CLI is unavailable')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    metadata = {'status': 'INITIALIZED_NOT_LISTENING', 'pid': __import__('os').getpid(),
        'collection_id': manifest['collection_id'], 'collection_sha256': hashlib.sha256(args.collection.read_bytes()).hexdigest(),
        'teacher_interface_version': VERSION, 'source_role': ROLE, 'mode': MODE,
        'native_tools_enabled': False, 'max_context_tokens': 16384, 'max_new_tokens': 3072,
        'timeout_seconds': 240, 'maximum_concurrent_requests': 2, 'seed_control_available': False,
        'shared_transport_global_slots': 2, 'cli_version': subprocess.check_output([executable, '--version'], text=True).strip(),
        'started_at_utc': datetime.now(timezone.utc).isoformat(), 'active_requests': 0, 'completed_requests': 0,
        'failed_requests': 0, 'accepted_trials': [], 'output': str(output)}
    semaphore = threading.BoundedSemaphore(2); lock = threading.Lock(); accepted = set(); stopped = False
    def stop(*unused):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused): pass
        def respond(self, status, value):
            payload = json.dumps(value).encode(); self.send_response(status)
            self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
        def do_GET(self):
            self.respond(200 if self.path == '/health' else 404, metadata if self.path == '/health' else {'error': 'unknown endpoint'})
        def do_POST(self):
            if self.path != '/decision': self.respond(404, {'error': 'unknown endpoint'}); return
            if not semaphore.acquire(blocking=False): self.respond(429, {'error': 'Both declared slots occupied; no model issued'}); return
            response = {}; work = None
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 1024 * 1024: raise ValueError('Unexpected packet size')
                body = json.loads(self.rfile.read(length))
                key = validate_body(body, requests)
                with lock:
                    if key in accepted: raise ValueError('Trial already accepted; never duplicate a model call')
                    accepted.add(key); metadata['accepted_trials'].append(list(key)); metadata['active_requests'] += 1; save(output / 'service.json', metadata)
                inference_id = str(uuid.uuid4()); work = output / 'sessions' / inference_id
                response = run_cli(executable, tokenizer, body['request'], work)
                response.update(inference_id=inference_id, collection_sha256=metadata['collection_sha256'])
                save(work / 'teacher_request.json', body); save(work / 'teacher_response.json', response)
            except Exception as exc: response = {'error': type(exc).__name__ + ': ' + str(exc), 'native_tools': []}
            finally:
                with lock:
                    if work is not None: metadata['active_requests'] -= 1
                    metadata['failed_requests' if response.get('error') else 'completed_requests'] += 1
                    save(output / 'service.json', metadata)
                try: self.respond(422 if response.get('error') else 200, response)
                except (BrokenPipeError, ConnectionResetError): pass
                semaphore.release()
    server = ThreadingHTTPServer(('127.0.0.1', 8122), Handler); server.timeout = .5
    metadata.update(status='READY', ready_at_utc=datetime.now(timezone.utc).isoformat()); save(output / 'service.json', metadata)
    print(json.dumps(metadata), flush=True)
    while not stopped: server.handle_request()
    server.server_close(); metadata.update(status='STOPPED', stopped_at_utc=datetime.now(timezone.utc).isoformat()); save(output / 'service.json', metadata)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('collection', 'output', 'tokenizer'): parser.add_argument('--' + name, type=Path, required=True)
    serve(parser.parse_args())

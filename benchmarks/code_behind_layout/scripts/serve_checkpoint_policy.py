#!/usr/bin/env python3
"""Ordinary16k policy for one actual E4 checkpoint, before validation selection.

The operator fixes the completed training run/checkpoint and adapter SHA. The
policy can send only the existing ordinary packet/history, never a model path.
No selected-methods manifest, teacher mode, native tool or GPU supervisor exists
in this service. Its actual GPU launch remains a separate coordinated operation.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.e4_methods import (METHODS, REVISION, SEEDS, SELECTION_RULE, checkpoint_files,
    file_digest, inspect_formal_run)
from src.local_model_adapter import decision_prompt
from src.model_adapter import ACTION_SCHEMA, check_utc_budget, remaining_utc_budget, validate_action
from src.student_interface import CONTEXT_VERSION, interface_definition
from scripts.serve_frozen_policy import QUANTIZATION, validate_request as validate_frozen_request

PORT = 8121
INFERENCE_SEED = 41
ROLE = 'E4_checkpoint_validation_not_selected'
DEFINITION = interface_definition(CONTEXT_VERSION, 16384, 1024)


def validate_checkpoint(args):
    """Bind one completed formal run; deliberately do not select a checkpoint."""
    plan_path = args.validation_plan.resolve()
    plan = json.loads(plan_path.read_text())
    if (plan.get('status') != 'FROZEN_E4_VALIDATION_PLAN'
            or plan.get('selection_rule') != SELECTION_RULE or not plan.get('points')
            or plan_path.stat().st_mode & 0o222
            or plan.get('budget', {}).get('maximum_context_tokens') != 16384
            or plan.get('budget', {}).get('maximum_output_tokens') != 1024):
        raise ValueError('A readonly predeclared validation-only16k/1024 plan is required')
    if args.method not in METHODS or type(args.training_seed) is not int or args.training_seed not in SEEDS:
        raise ValueError('Fix one actual T1--T4 training method and seed')
    checkpoint = args.checkpoint.resolve()
    entry = {'method': args.method, 'seed': args.training_seed,
             'run_directory': str(args.run_directory.resolve()),
             'training_manifest': str(args.training_manifest.resolve())}
    training = inspect_formal_run(entry, ROOT, DEFINITION, plan['split_registry_sha256'])
    if checkpoint not in {path.resolve() for path in training['checkpoints']}:
        raise ValueError('Requested checkpoint is outside the actual completed formal run')
    marker = checkpoint_files(checkpoint)
    if any(training['config'].get('quantization', {}).get(key) != value for key, value in QUANTIZATION.items()):
        raise ValueError('Training precision differs from common NF4/double-quant/bf16 inference')
    adapter = checkpoint / 'adapter/policy'
    digest = file_digest(adapter / 'adapter_model.safetensors')
    if digest != args.adapter_sha256:
        raise ValueError('Operator weight SHA differs from the actual checkpoint adapter')
    snapshot = Path(training['manifest']['backbone_snapshot']).resolve()
    if snapshot.name != REVISION or not snapshot.is_dir():
        raise ValueError('The actual pinned32B backbone snapshot is absent')
    identity = {'variant': args.method, 'training_seed': args.training_seed,
        'checkpoint_update': marker['updates'], 'checkpoint': str(checkpoint),
        'adapter_path': str(adapter), 'adapter_sha256': digest,
        'adapter_config_sha256': file_digest(adapter / 'adapter_config.json'),
        'base_model': training['config']['backbone'], 'base_revision': REVISION,
        'tokenizer_revision': REVISION, 'backbone_snapshot': str(snapshot),
        'source_role': ROLE, 'student_interface_version': CONTEXT_VERSION,
        'visible_history_policy': DEFINITION['history_policy'],
        'validation_plan': str(plan_path), 'validation_plan_sha256': file_digest(plan_path),
        'training_manifest': str(args.training_manifest.resolve()),
        'training_manifest_sha256': file_digest(args.training_manifest),
        'selected_checkpoint': False}
    return identity


def validate_request(body, identity):
    if not isinstance(body, dict) or set(body) != {'variant', 'request'}:
        raise ValueError('Expected only the existing ordinary variant/request body')
    if body['variant'] != identity['variant']:
        raise ValueError('Request method differs from the operator-fixed checkpoint')
    return validate_frozen_request({**body, 'training_seed': identity['training_seed']}, DEFINITION)


def failed_decision(inference_id, error, identity, usage, generation_started):
    response = {'inference_id': inference_id, 'error': type(error).__name__ + ': ' + str(error),
        'model': identity, 'native_tools': [], 'generation_started': generation_started,
        'failure_class': 'policy_output_or_budget' if usage is not None and isinstance(error, (ValueError, TimeoutError)) else 'unknown'}
    if usage is not None:
        response['usage'] = usage
    return response


def serve(args):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    metadata = {'phase': 'E4_checkpoint_validation_policy_service', 'status': 'VALIDATING_CHECKPOINT',
        'pid': os.getpid(), 'argv': [sys.executable] + sys.argv, 'port': PORT, 'bind': '127.0.0.1',
        'native_tools': [], 'successful_requests': 0, 'failed_requests': 0,
        'started_at_utc': datetime.now(timezone.utc).isoformat()}
    lifetime = time.monotonic(); lifetime_cpu = resource.getrusage(resource.RUSAGE_SELF); stopped = False
    def save():
        (out / 'service.json').write_text(json.dumps(metadata, indent=2, allow_nan=False) + '\n')
    (out / 'pid').write_text(str(os.getpid()) + '\n'); save()
    try:
        started = time.monotonic(); identity = validate_checkpoint(args)
        metadata.update(status='LOADING', model_identity=identity,
                        checkpoint_binding_wall_seconds=time.monotonic() - started)
        affinity = sorted(os.sched_getaffinity(0)); os.sched_setaffinity(0, affinity[:4])
        os.environ.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', TOKENIZERS_PARALLELISM='false',
                          HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        metadata['environment_overrides'] = {key: os.environ[key] for key in ['OMP_NUM_THREADS',
            'OPENBLAS_NUM_THREADS', 'TOKENIZERS_PARALLELISM', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE']}
        save()
        import torch
        from peft import PeftModel, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, StoppingCriteria, StoppingCriteriaList
        import xgrammar
        from xgrammar.contrib.hf import LogitsProcessor
        torch.set_num_threads(2); torch.set_num_interop_threads(2)
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise RuntimeError('One available GPU required; this service never stops another job')
        if torch.cuda.mem_get_info()[0] < 65 * 1024**3:
            raise RuntimeError('GPU unavailable; the unique supervisor must drain and pause its own model first')
        torch.manual_seed(INFERENCE_SEED); torch.cuda.manual_seed_all(INFERENCE_SEED)
        tokenizer = AutoTokenizer.from_pretrained(identity['backbone_snapshot'], local_files_only=True, trust_remote_code=False)
        tokenizer.pad_token = tokenizer.eos_token
        torch.cuda.reset_peak_memory_stats(); loading = time.monotonic()
        model = AutoModelForCausalLM.from_pretrained(identity['backbone_snapshot'], local_files_only=True,
            trust_remote_code=False, quantization_config=BitsAndBytesConfig(load_in_4bit=True,
                bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16),
            dtype=torch.bfloat16, device_map={'': 0}, attn_implementation='sdpa')
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=False)
        model = PeftModel.from_pretrained(model, identity['adapter_path'], adapter_name='policy', is_trainable=False)
        model.set_adapter('policy'); model.eval(); model.config.use_cache = True
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        compiler = xgrammar.GrammarCompiler(xgrammar.TokenizerInfo.from_huggingface(tokenizer,
            vocab_size=model.config.vocab_size), max_threads=2)
        compiled = compiler.compile_json_schema(ACTION_SCHEMA)
        torch.cuda.synchronize()
        settings = {'quantization': 'NF4', 'double_quantization': True, 'compute_dtype': 'bfloat16',
            'attention_backend': 'sdpa', 'nonquantized_preparation': 'prepare_model_for_kbit_training(use_gradient_checkpointing=False)',
            'nonquantized_inference_autocast': 'bfloat16',
            'do_sample': False, 'seed': INFERENCE_SEED, 'max_new_tokens': 1024, 'maximum_context_tokens': 16384,
            'use_cache': True, 'visible_history_policy': DEFINITION['history_policy'],
            'adapter_dropout': 'disabled by model.eval(), as in frozen8117',
            'json_constraint': 'xgrammar HF LogitsProcessor with shared ACTION_SCHEMA'}
        identity.update(settings=settings)
        metadata.update(status='LOADED_NOT_LISTENING', settings=settings, student_interface=DEFINITION,
            tokenizer_class=type(tokenizer).__name__, tokenizer_eos_token_id=tokenizer.eos_token_id,
            versions={name: importlib.metadata.version(name) for name in ['torch', 'transformers', 'peft', 'bitsandbytes', 'xgrammar', 'safetensors']},
            load_and_grammar_wall_seconds=time.monotonic() - loading,
            load_peak_allocated_bytes=torch.cuda.max_memory_allocated(), load_peak_reserved_bytes=torch.cuda.max_memory_reserved())
        save()
        def stop(signum, frame):
            nonlocal stopped
            stopped = True
        signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
        class DeadlineStop(StoppingCriteria):
            def __init__(self, packet):
                self.packet = packet
            def __call__(self, input_ids, scores, **unused):
                remaining = remaining_utc_budget(self.packet)
                return remaining is not None and remaining <= 0
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass
            def respond(self, status, body):
                data = json.dumps(body, allow_nan=False).encode(); self.send_response(status)
                self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
            def do_GET(self):
                self.respond(200, {**metadata, 'resident_wall_seconds_so_far': time.monotonic() - lifetime}) if self.path == '/health' else self.respond(404, {'error': 'unknown endpoint'})
            def do_POST(self):
                if self.path != '/decision':
                    self.respond(404, {'error': 'unknown endpoint'}); return
                inference_id = str(uuid.uuid4()); work = out / 'requests' / inference_id; work.mkdir(parents=True)
                record = {'inference_id': inference_id, 'status': 'RUNNING', 'started_at_utc': datetime.now(timezone.utc).isoformat()}
                started = time.monotonic(); before = resource.getrusage(resource.RUSAGE_SELF); usage = None; gpu_started = False
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 2 * 1024 * 1024:
                        raise ValueError('Request exceeds ordinary packet transport limit')
                    body = json.loads(self.rfile.read(length)); (work / 'request.json').write_text(json.dumps(body, indent=2) + '\n')
                    prompt = validate_request(body, identity); packet = body['request']['task_packet']
                    encoded = tokenizer.apply_chat_template([{'role': 'user', 'content': prompt}], tokenize=True,
                        add_generation_prompt=True, return_dict=True, return_tensors='pt')
                    input_tokens = int(encoded['input_ids'].shape[-1])
                    if input_tokens + 1024 > 16384:
                        raise ValueError('Full source/history plus1024reserve exceeds16k; no truncation')
                    check_utc_budget(packet)
                    torch.cuda.reset_peak_memory_stats(); gpu_started = True
                    inputs = {key: value.to('cuda:0') for key, value in encoded.items() if key in ('input_ids', 'attention_mask')}
                    torch.manual_seed(INFERENCE_SEED); torch.cuda.manual_seed_all(INFERENCE_SEED)
                    torch.cuda.synchronize(); generation = time.monotonic()
                    begin = torch.cuda.Event(enable_timing=True); end = torch.cuda.Event(enable_timing=True)
                    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
                        begin.record()
                        generated = model.generate(**inputs, max_new_tokens=1024, do_sample=False, use_cache=True,
                            pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id,
                            logits_processor=[LogitsProcessor(compiled)], stopping_criteria=StoppingCriteriaList([DeadlineStop(packet)]))
                        end.record()
                    torch.cuda.synchronize(); tokens = generated[0, input_tokens:]
                    text = tokenizer.decode(tokens, skip_special_tokens=True); (work / 'completion.txt').write_text(text)
                    eos = bool(len(tokens) and int(tokens[-1]) == tokenizer.eos_token_id)
                    after = resource.getrusage(resource.RUSAGE_SELF)
                    usage = {'input_tokens': input_tokens, 'output_tokens': len(tokens), 'eos_terminated': eos,
                        'max_new_tokens': 1024, 'maximum_context_tokens': 16384,
                        'generation_wall_seconds': time.monotonic() - generation, 'server_wall_seconds': time.monotonic() - started,
                        'cuda_stream_elapsed_seconds': begin.elapsed_time(end) / 1000, 'gpu_devices_allocated': 1,
                        'server_user_cpu_seconds': after.ru_utime - before.ru_utime,
                        'server_system_cpu_seconds': after.ru_stime - before.ru_stime,
                        'peak_allocated_bytes': torch.cuda.max_memory_allocated(), 'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
                        'decoding_settings': {'do_sample': False, 'seed': INFERENCE_SEED},
                        'request_mode': 'E4_checkpoint_validation_ordinary_action', 'output_format': 'structured_action'}
                    if not eos:
                        raise ValueError('ACTION did not finish with EOS within1024tokens or UTC budget')
                    check_utc_budget(packet); action = validate_action(json.loads(text), packet)
                    response = {'inference_id': inference_id, 'action': action, 'usage': usage, 'model': identity, 'native_tools': []}
                    record.update(status='COMPLETED', response=response); metadata['successful_requests'] += 1
                    self.respond(200, response)
                except Exception as error:
                    response = failed_decision(inference_id, error, identity, usage, gpu_started)
                    record.update(status='FAILED', response=response); metadata['failed_requests'] += 1
                    self.respond(422, response)
                finally:
                    after_attempt = resource.getrusage(resource.RUSAGE_SELF)
                    record.update(ended_at_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=time.monotonic() - started,
                        server_user_cpu_seconds=after_attempt.ru_utime - before.ru_utime,
                        server_system_cpu_seconds=after_attempt.ru_stime - before.ru_stime,
                        gpu_generation_started=gpu_started,
                        cuda_stream_elapsed_seconds=None if usage is None else usage['cuda_stream_elapsed_seconds'])
                    if gpu_started:
                        record.update(peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(), peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved())
                    (work / 'invocation.json').write_text(json.dumps(record, indent=2, allow_nan=False) + '\n'); save()
        server = HTTPServer(('127.0.0.1', PORT), Handler); server.timeout = .5
        metadata.update(status='READY', ready_at_utc=datetime.now(timezone.utc).isoformat()); save()
        print(json.dumps({'status': 'READY', 'pid': os.getpid(), 'port': PORT, 'output': str(out)}), flush=True)
        while not stopped:
            server.handle_request()
        server.server_close(); metadata.update(status='STOPPED', stopped_at_utc=datetime.now(timezone.utc).isoformat())
    except Exception as error:
        metadata.update(status='FAILED', error=type(error).__name__ + ': ' + str(error)); raise
    finally:
        final_cpu = resource.getrusage(resource.RUSAGE_SELF)
        metadata.update(service_wall_seconds_so_far=time.monotonic() - lifetime,
            service_user_cpu_seconds=final_cpu.ru_utime - lifetime_cpu.ru_utime,
            service_system_cpu_seconds=final_cpu.ru_stime - lifetime_cpu.ru_stime)
        save()


def rpc(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            sys.stdout.write(response.read().decode() + '\n')
    except urllib.error.HTTPError as error:
        sys.stdout.write(error.read().decode() + '\n'); raise SystemExit(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ['serve', 'validate-only', 'request', 'health']:
        modes.add_argument('--' + name, action='store_true')
    for name in ['validation-plan', 'run-directory', 'training-manifest', 'checkpoint', 'output']:
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--method', choices=METHODS); parser.add_argument('--training-seed', type=int, choices=SEEDS)
    parser.add_argument('--adapter-sha256')
    args = parser.parse_args()
    if args.request:
        rpc('/decision', json.loads(sys.stdin.read()))
    elif args.health:
        rpc('/health')
    else:
        if any(getattr(args, key) is None for key in ['validation_plan', 'run_directory', 'training_manifest',
                'checkpoint', 'method', 'training_seed', 'adapter_sha256']):
            parser.error('Fix the actual validation plan, completed training run, method/seed/checkpoint and weight SHA')
        if args.validate_only:
            print(json.dumps({'status': 'CONFIGURATION_VALIDATED_NO_GPU_LOAD', 'model': validate_checkpoint(args), 'READY': False}))
        else:
            if args.output is None:
                parser.error('--serve needs a fresh output directory')
            serve(args)


if __name__ == '__main__':
    main()

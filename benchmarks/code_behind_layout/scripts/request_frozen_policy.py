#!/usr/bin/env python3
"""Fixed loopback transport for the existing LocalDecisionAdapter stdin body."""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.e4_methods import METHODS,SEEDS
from src.model_adapter import validate_action


def verify_response(response,body,seed,methods_sha256,adapter_sha256):
    if response.get('native_tools')!=[]:raise ValueError('Frozen policy returned an undeclared native capability')
    expected={'variant':body['variant'],'training_seed':None if body['variant']=='T0' else seed,
        'evaluation_seed_slot':seed,'methods_manifest_sha256':methods_sha256,'adapter_sha256':adapter_sha256}
    if response.get('model_identity')!=expected:raise ValueError('Actual frozen model/seed/weights differ from the declared policy')
    if any(response.get('model',{}).get(key)!=value for key,value in expected.items()):
        raise ValueError('Ordinary model metadata contradicts frozen model identity')
    usage=response.get('usage',{})
    if (usage.get('max_new_tokens')!=1024 or type(usage.get('output_tokens')) is not int
        or not 0<usage['output_tokens']<=1024 or usage.get('eos_terminated') is not True):
        raise ValueError('Frozen ordinary response did not satisfy the strict1024/EOS output budget')
    packet=body['request']['task_packet']
    if (usage.get('maximum_context_tokens')!=packet['budget']['maximum_context_tokens']
        or type(usage.get('input_tokens')) is not int or usage['input_tokens']+1024>packet['budget']['maximum_context_tokens']):
        raise ValueError('Frozen response differs from the complete declared context budget')
    validate_action(response['action'],packet)
    return response


def exchange(body,seed,methods_sha256,adapter_sha256,endpoint):
    if (not isinstance(body,dict) or set(body)!={'variant','request'} or body['variant'] not in ('T0',)+METHODS
        or type(seed) is not int or seed not in SEEDS):
        raise ValueError('Expected the existing fixed ordinary variant/request body and a declared seed slot')
    parsed=urllib.parse.urlparse(endpoint)
    if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.port!=8117 or parsed.path!='/decision'
        or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError('Frozen transport endpoint must be the declared127.0.0.1:8117/decision')
    if (body['variant']=='T0')!=(adapter_sha256 is None):raise ValueError('T0 has no adapter; trained variants require their actual adapter identity')
    sent={**body,'training_seed':seed};request=urllib.request.Request(endpoint,json.dumps(sent).encode(),{'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=600) as stream:raw=stream.read().decode()
    except urllib.error.HTTPError as error:
        # Preserve late/truncated/generation-failure usage and inference_id.
        sys.stdout.write(error.read().decode()+'\n');return 2
    response=json.loads(raw)
    try:verify_response(response,body,seed,methods_sha256,adapter_sha256)
    except ValueError as error:
        response={**response,'error':'FrozenPolicyIdentityError: '+str(error)}
        sys.stdout.write(json.dumps(response)+'\n');return 2
    sys.stdout.write(raw+'\n');return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training-seed',type=int,choices=SEEDS,required=True)
    parser.add_argument('--methods-sha256',required=True)
    parser.add_argument('--adapter-sha256',required=True,help='Use literal none for the single T0 backbone')
    parser.add_argument('--endpoint',default='http://127.0.0.1:8117/decision')
    args=parser.parse_args()
    raise SystemExit(exchange(json.loads(sys.stdin.read()),args.training_seed,args.methods_sha256,
        None if args.adapter_sha256=='none' else args.adapter_sha256,args.endpoint))


if __name__=='__main__':main()

"""Prepare/validate prospective E4 plans and record actual checkpoint evidence.

Prepare/validate/freeze/record/select launch no inference or EDA. The explicit
run command requires an already-loaded operator-fixed checkpoint service and
produces ordinary editing plus real isolated physical evidence. It never starts
a GPU service. Finalization reopens raw evidence through the unchanged E4 gate.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from src.e4_validation import prepare, prepare_joint_registry, validate_plan, freeze, record_checkpoint, run_checkpoint, selection, read, save
from src.e4_methods import inspect_formal_run
from src.student_interface import interface_definition, CONTEXT_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--registry', type=Path, required=True); p.add_argument('--tasks', type=Path)
    p.add_argument('--budget', type=Path, required=True); p.add_argument('--checkpoint-backend', type=Path); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('validate'); p.add_argument('--plan', type=Path, required=True); p.add_argument('--draft', action='store_true')
    p = sub.add_parser('freeze'); p.add_argument('--draft', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('record'); p.add_argument('--plan', type=Path, required=True); p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--method', choices=('T1', 'T2', 'T3', 'T4'), required=True); p.add_argument('--seed', type=int, choices=(41, 73, 109), required=True)
    p.add_argument('--task-records', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('select'); p.add_argument('--plan', type=Path, required=True); p.add_argument('--entry', type=Path, required=True)
    p.add_argument('--editing-ledger', action='append', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('run'); p.add_argument('--plan', type=Path, required=True); p.add_argument('--entry', type=Path, required=True)
    p.add_argument('--checkpoint', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('joint-registry'); p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--qualified-task', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'joint-registry': result = prepare_joint_registry(args.registry, args.qualified_task, args.output)
    elif args.command == 'prepare':
        result = prepare(args.registry, args.tasks, read(args.budget), args.checkpoint_backend); save(args.output, result)
    elif args.command == 'validate':
        value = read(args.plan)
        if args.draft:
            result = {'status': value['status'], 'freeze_blockers': value['freeze_blockers'], 'points': len(value['points']), 'new_model_or_EDA_calls': 0}
        else:
            validate_plan(value, args.plan)
            result = {'status': 'FROZEN_VALIDATION_PLAN_SOFTWARE_BINDINGS_VALID', 'points': len(value['points']), 'new_model_or_EDA_calls': 0}
    elif args.command == 'freeze': result = freeze(args.draft, args.output)
    elif args.command == 'record':
        result = record_checkpoint(args.plan, args.checkpoint, args.method, args.seed, read(args.task_records), args.output)
    elif args.command == 'run':
        result = run_checkpoint(args.plan, read(args.entry), args.checkpoint, args.output, ROOT, args.entry.resolve().parent)
    else:
        plan = read(args.plan); registry, _ = validate_plan(plan, args.plan)
        entry = read(args.entry); root = args.entry.resolve().parent
        definition = interface_definition(CONTEXT_VERSION, plan['budget']['maximum_context_tokens'], 1024)
        training = inspect_formal_run(entry, root, definition, plan['split_registry_sha256'])
        result = selection(entry, training, root, registry, args.plan, args.editing_ledger, args.output)
    print(json.dumps({k: result[k] for k in ('status', 'freeze_blockers', 'selected_checkpoint', 'new_model_or_EDA_calls') if k in result}, indent=2))


if __name__ == '__main__': main()

#!/bin/bash
# Server-side launcher for the six formal DPO runs (T3 and T4 at seeds 41/73/109) after T1 checkpoint selection.
#   1. writes <data_dir>/training_manifest_dpo.json = the frozen SFT manifest plus the validation-selected T1 adapters
#      (methods.T1.selected_checkpoints and T3/T4.starting_t1_checkpoints, identical per seed) — the SFT manifest is untouched;
#   2. validates admission for every (method, seed); 3. requires a free GPU (8114 already stopped); 4. runs T3 then T4 per seed.
# Usage: run_e4_dpo_training.sh <data_dir> <selection dir e.g. runs/e4_validation/<freeze>/T1>
set -u
cd "$(dirname "$0")/.."
DATA="$1"; SEL="$2"; FREEZE=$(basename "$DATA"); PY=runtime/training-venv/bin/python
export PYTHONPYCACHEPREFIX="$PWD/runtime/training-pycache"
chmod u+w $DATA
python3 - "$DATA" "$SEL" <<'PY'
import json,sys,os
data,sel=sys.argv[1:]
m=json.load(open(os.path.join(data,'training_manifest.json')))
selected={}
for seed in (41,73,109):
    s=json.load(open(os.path.join(sel,'seed-%d'%seed,'selection.json')))
    if s.get('status')!='COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION': raise SystemExit('selection for seed %d is not completed: %s'%(seed,s.get('status')))
    adapter=os.path.join(os.path.realpath(s['selected_checkpoint']),'adapter','policy')  # same string the methods freeze derives
    if not os.path.isdir(adapter): raise SystemExit('selected adapter directory missing: '+adapter)
    selected[str(seed)]=adapter
m['methods']['T1']['selected_checkpoints']=selected
for method in ('T3','T4'): m['methods'][method]['starting_t1_checkpoints']=dict(selected)
m['dpo_manifest_note']='Same frozen data, config, registry and evidence as training_manifest.json; adds the validation-selected same-seed T1 adapters for T3/T4.'
out=os.path.join(data,'training_manifest_dpo.json')
if os.path.exists(out): raise SystemExit('DPO manifest already exists: '+out)
json.dump(m,open(out,'w'),indent=2); os.chmod(out,0o444); print('dpo manifest written', selected)
PY
chmod u-w $DATA
for m in T3 T4; do for s in 41 73 109; do
  $PY scripts/train_policy.py --manifest $DATA/training_manifest_dpo.json --method $m --seed $s --output checkpoints/$FREEZE/$m/seed-$s --validate-only > /dev/null || { echo "$(date -u +%FT%TZ) admission failed for $m seed $s"; exit 1; }
done; done
echo "$(date -u +%FT%TZ) all six DPO runs admitted"
FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1); [ "$FREE" -ge 66560 ] || { echo "GPU not free ($FREE MiB)"; exit 1; }
for s in 41 73 109; do for m in T3 T4; do
  OUT=checkpoints/$FREEZE/$m/seed-$s
  if [ -f $OUT/run.json ] && python3 -c "import json,sys; sys.exit(0 if json.load(open('$OUT/run.json')).get('status')=='TRAINING_COMPLETED_NOT_SELECTED' else 1)"; then echo "$(date -u +%FT%TZ) $m seed $s already complete"; continue; fi
  echo "$(date -u +%FT%TZ) training $m seed $s"
  CUDA_VISIBLE_DEVICES=0 $PY scripts/train_policy.py --manifest $DATA/training_manifest_dpo.json --method $m --seed $s --output $OUT > logs/train_${FREEZE}_${m}_seed${s}.log 2>&1
  echo "$(date -u +%FT%TZ) $m seed $s exit $? status $(python3 -c "import json; print(json.load(open('$OUT/run.json')).get('status'))" 2>/dev/null)"
done; done
echo "$(date -u +%FT%TZ) DPO stage finished"

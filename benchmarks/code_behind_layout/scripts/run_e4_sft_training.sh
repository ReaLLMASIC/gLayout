#!/bin/bash
# Server-side launcher for the six formal SFT runs (T1 and T2 at seeds 41/73/109) from a frozen E4 data directory.
#   1. validates every (method, seed) with the trainer's admission check (no GPU);
#   2. stops the 8114 local policy service (recorded receipt) and waits for >= 65 GiB free GPU memory;
#   3. runs T1 then T2, one seed after another, writing checkpoints/<freeze>/<method>/seed-<seed>.
# T3/T4 follow separately after validation selection (scripts/run_e4_dpo_training.sh).
# Usage: run_e4_sft_training.sh <data_dir e.g. data/training/e4_textbook_v1>
set -u
cd "$(dirname "$0")/.."
DATA="$1"; FREEZE=$(basename "$DATA"); PY=runtime/training-venv/bin/python
export PYTHONPYCACHEPREFIX="$PWD/runtime/training-pycache"
for m in T1 T2; do for s in 41 73 109; do
  $PY scripts/train_policy.py --manifest $DATA/training_manifest.json --method $m --seed $s --output checkpoints/$FREEZE/$m/seed-$s --validate-only > /dev/null || { echo "$(date -u +%FT%TZ) admission failed for $m seed $s"; exit 1; }
done; done
echo "$(date -u +%FT%TZ) all six SFT runs admitted"
PID=$(pgrep -f "scripts/serve_local_policy.py --serve" | head -1)
if [ -n "$PID" ]; then
  ARGV=$(tr '\0' ' ' < /proc/$PID/cmdline)
  python3 - "$PID" "$ARGV" <<'PY'
import json,sys,datetime
rec={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'SIGTERM 8114 local policy service before formal E4 training (plan: GPU needed, 62-64 GiB peak)','pid':int(sys.argv[1]),'argv':sys.argv[2]}
open('results/derived/service_8114_stop_receipts.jsonl','a').write(json.dumps(rec)+'\n')
PY
  kill -TERM $PID; echo "$(date -u +%FT%TZ) stopped 8114 service pid $PID"
fi
for i in $(seq 1 60); do
  FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
  [ "$FREE" -ge 66560 ] && break; sleep 10
done
echo "$(date -u +%FT%TZ) GPU free MiB: $FREE"
for m in T1 T2; do for s in 41 73 109; do
  OUT=checkpoints/$FREEZE/$m/seed-$s
  if [ -f $OUT/run.json ] && python3 -c "import json,sys; sys.exit(0 if json.load(open('$OUT/run.json')).get('status')=='TRAINING_COMPLETED_NOT_SELECTED' else 1)"; then echo "$(date -u +%FT%TZ) $m seed $s already complete"; continue; fi
  echo "$(date -u +%FT%TZ) training $m seed $s"
  CUDA_VISIBLE_DEVICES=0 $PY scripts/train_policy.py --manifest $DATA/training_manifest.json --method $m --seed $s --output $OUT > logs/train_${FREEZE}_${m}_seed${s}.log 2>&1
  echo "$(date -u +%FT%TZ) $m seed $s exit $? status $(python3 -c "import json; print(json.load(open('$OUT/run.json')).get('status'))" 2>/dev/null)"
done; done
echo "$(date -u +%FT%TZ) SFT stage finished"

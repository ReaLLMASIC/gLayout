#!/bin/bash
# Server-side: finish the plan-v2 checkpoint selections for the DPO methods T3/T4 (seeds 41, 73, 109) after the
# T1/T2 selections of run_e4_selection_v2_chain.sh completed. T3/T4 selections read the DPO training manifest.
# Usage: run_e4_selection_v2_dpo_chain.sh <data_dir> <frozen_plan_v2.json> <validation_root_v2>
set -u
cd "$(dirname "$0")/.."
DATA="$1"; PLAN="$2"; VROOT="$3"; FREEZE=$(basename "$DATA")
log() { echo "$(date -u +%FT%TZ) $*"; }
sel() { python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('status'), d.get('selected_checkpoint',''))" "$1" 2>/dev/null; }
wait_gpu() { for i in $(seq 1 60); do FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1); [ "$FREE" -ge 66560 ] && return 0; sleep 10; done; log "GPU not free ($FREE MiB)"; return 1; }
for m in T3 T4; do for s in 41 73 109; do
  log "$m seed $s selection (plan v2)"; wait_gpu || exit 1
  bash scripts/run_e4_validation_selection.sh $DATA $PLAN $m $s $VROOT >> logs/e4_selection_v2_${FREEZE}_${m}_seed$s.log 2>&1
  read st ck <<< "$(sel $VROOT/$FREEZE/$m/seed-$s/selection.json)"
  log "$m seed $s status '$st' selected ${ck##*/}"
  [ "$st" = "COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION" ] || { log "chain stops"; exit 1; }
done; done
log "v2 DPO selection chain finished: T3/T4 selections complete"

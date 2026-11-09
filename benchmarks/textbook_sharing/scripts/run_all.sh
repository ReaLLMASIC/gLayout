#!/bin/bash
# Run the whole benchmark in the order of the protocol: case definitions and rules first; the development sizes next,
# from which the fixed mode order is frozen and the cost rule is checked; then the held-out sizes, the selection study,
# the corner simulations and the analyses.  Every stage is resumable (finished runs are skipped); frozen rules
# (data/frozen/) and freeze checkpoints (<results>/freeze/) are never overwritten.  The model sessions are not started
# here: they need a logged-in model CLI or an agent interface (docs/MODELS.md).  The grid and the selection study take
# days of CPU time on a 16-core machine.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd); C="$HERE/scripts/run_in_container.sh"; J=${JOBS:-16}
RES=${TSB_RESULTS:-$HERE/results}; DEV=sW1_sL1,sW1_sL1.5
stage() { echo "== $1"; }
[ -d "$HERE/data/cases" ] || tar -xJf "$HERE/data/cases.tar.xz" -C "$HERE"
freeze() { [ -f "$RES/freeze/$1.json" ] || $C "python -m textbook_sharing.freeze $1 '$2'"; }
stage "1 cases: derive sizes, qualify, freeze specifications"
$C "python -m textbook_sharing.build_cases --jobs $J"
freeze cases_and_rules "size grid, qualification rule and frozen specifications, before any layout"
stage "2 main grid, development sizes"
$C "python -m textbook_sharing.run_grid --sizes $DEV --jobs $J"
stage "3 fixed mode order and cost rule, from the development sizes only"
[ -f "$HERE/data/frozen/fixed_order.json" ] || $C "python -m textbook_sharing.selection.fixed_order --sizes $DEV"
$C "python -m textbook_sharing.analysis.cost_validation --sizes $DEV --out $RES/analysis/cost_validation_dev.json"
freeze cost_and_order "cost rule and fixed mode order, before the held-out sizes"
stage "4 main grid, all sizes"
$C "python -m textbook_sharing.run_grid --jobs $J"
stage "5 selection catalogues and their full evaluation"
$C "python -m textbook_sharing.selection.run_selection --stage all --jobs $J"
stage "6 controlled timing of the selection methods"
$C "python -m textbook_sharing.selection.timing --jobs 10 --out $RES/analysis/timing_controlled.json"
stage "7 corners (PVT)"
$C "python -m textbook_sharing.analysis.pvt --jobs $J --out $RES/analysis/pvt.json"
stage "8 analyses and the generated documents"
$C "python -m textbook_sharing.analysis.all --with-geometry"
stage "9 clean-process reproduction"
"$HERE/scripts/reproduce_clean.sh"

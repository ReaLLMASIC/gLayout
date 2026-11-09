"""Recompute every analysis table from the run records, in dependency order, into <results>/ and <results>/analysis/.

By default only the analyses that read run records are run.  --with-geometry also re-runs the cost-rule validation
(it rebuilds the unshared assembly of every case, a few minutes); the corner simulations (analysis.pvt) and the
controlled timing (selection.timing) are separate commands because they run simulations or time geometry builds.
usage: python -m textbook_sharing.analysis.all [--with-geometry]"""
import argparse, subprocess, sys
from textbook_sharing import paths

DEV = "sW1_sL1,sW1_sL1.5"
HELD_OUT = "sW0.5_sL1,sW0.5_sL1.5,sW0.5_sL2,sW1_sL2,sW1.5_sL1,sW1.5_sL1.5,sW1.5_sL2,sW2_sL1,sW2_sL1.5,sW2_sL2"


def run(mod, *args):
    print("==", mod, *args, flush=True)
    subprocess.run([sys.executable, "-m", f"textbook_sharing.{mod}", *args], check=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--with-geometry", action="store_true"); a = ap.parse_args()
    A = paths.ANALYSIS; A.mkdir(parents=True, exist_ok=True)
    run("analysis.ledger")
    run("analysis.benchmark_table", "--out", str(A / "benchmark_table.json"))
    run("analysis.cost_decomposition", "--out", str(A / "cost_decomposition.json"))
    if a.with_geometry:
        run("analysis.cost_validation", "--sizes", DEV, "--out", str(A / "cost_validation_dev.json"))
        run("analysis.cost_validation", "--sizes", DEV, "--channel-rule", "none", "--out", str(A / "cost_validation_dev_no_channel.json"))
        run("analysis.cost_validation", "--sizes", HELD_OUT, "--out", str(A / "cost_validation_heldout.json"))
    run("analysis.selection", "--out", str(A / "selection_summary.json"))
    run("analysis.models", "--out", str(A / "llm_summary.json"), "--tags", "openai_gpt-6.1-sol,anthropic_claude-sonnet")
    run("analysis.interface", "--out", str(A / "llm_interface.json"))
    run("analysis.scope", "--out", str(A / "scope_audit.json"))
    run("analysis.arrangement_bandwidth", "--topology", "C16", "--out", str(A / "arrangement_bandwidth_C16.json"))
    run("analysis.review_coverage", "--out", str(A / "review_coverage.json"))
    run("analysis.example", "--out", str(A / "running_example.json"))
    run("analysis.report")


if __name__ == "__main__":
    main()

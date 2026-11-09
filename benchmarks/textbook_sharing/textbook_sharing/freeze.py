"""Record a freeze checkpoint: the sha256 of every rule-bearing source file and of every case manifest, with a note.

Rules are frozen in stages before the measurements they govern (size grid and qualification rule before any layout;
cost rule and fixed mode order on the two development sizes before the held-out sizes; testbench fixes before
requalification).  A checkpoint is never overwritten, so it documents which rules were in force at that time.
usage: python -m textbook_sharing.freeze <name> ["note"]   -> <results>/freeze/<name>.json"""
import sys, json, hashlib, glob, time, subprocess
from pathlib import Path
from textbook_sharing import paths

PKG = Path(__file__).resolve().parent
FILES = ["grid.py", "qualify.py", "overrides.py", "build_cases.py", "testbench.py", "run_case.py", "matching.py", "layout.py",
         "run_grid.py", "assembly/engine.py", "assembly/passives.py", "verify/pipeline.py", "verify/drc.py", "verify/lvs.py",
         "verify/pex_sim.py", "selection/catalogue.py", "selection/cost.py", "selection/strategies.py", "selection/run_selection.py",
         "selection/fixed_order.py", "llm/plan_parser.py", "llm/evaluate.py", "llm/tasks.py", "llm/interface_sharing.md"]
SHARING = ["enumerate.py", "group.py", "rules.py", "spec.py", "evidence.py"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    name = sys.argv[1]; out = paths.RESULTS / "freeze"; out.mkdir(parents=True, exist_ok=True)
    f = out / f"{name}.json"
    if f.exists():
        sys.exit(f"{f} exists; freeze checkpoints are never overwritten")
    files = {f"textbook_sharing/{x}": sha(PKG / x) for x in FILES if (PKG / x).exists()}
    files.update({f"glayout/sharing/{x}": sha(paths.REPO / "src/glayout/sharing" / x) for x in SHARING})
    frozen = {str(Path(p).relative_to(paths.ROOT)): sha(p) for p in sorted(glob.glob(str(paths.FROZEN / "*.json")))}
    cases = {str(Path(m).parent.relative_to(paths.ROOT)): sha(m) for m in sorted(glob.glob(str(paths.CASES / "*/*/*/manifest.json")))}
    lock = {"name": name, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": files, "frozen_data": frozen,
            "case_manifests": cases, "n_cases": len(cases),
            "git_head": subprocess.run(["git", "-C", str(paths.REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
            "note": sys.argv[2] if len(sys.argv) > 2 else ""}
    json.dump(lock, open(f, "w"), indent=1)
    print(f, len(files), "files", len(cases), "cases")


if __name__ == "__main__":
    main()

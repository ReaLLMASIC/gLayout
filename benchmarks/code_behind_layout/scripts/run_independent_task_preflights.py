"""Run the five declared generation domains in two engineering containers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(preparation):
    names = json.loads((preparation / "summary.json").read_text())["targets"]

    def one(name):
        command = ["python3", str(ROOT / "scripts/run_eda_probe.py"), "--script", "independent_task_preflight.py",
            "--input-dir", str(preparation / "private" / name), "--timeout", "900", "--magic-runtime", "magic-8.3.685"]
        with (ROOT / "logs" / ("independent_domain_" + name + ".log")).open("x") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        print(json.dumps({"target": name, "launcher_returncode": result.returncode}), flush=True)

    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(one, names))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    run(parser.parse_args().preparation.resolve())

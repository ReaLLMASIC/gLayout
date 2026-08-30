"""Runs ``pdk.lvs_netgen`` on every cell using the GDS + reference netlist
emitted by ``tests/drc/run_cell_drc.py``.

The LVS CI workflow pulls the DRC artifact (``drc_results/<pdk>/``), which
contains:

  drc_results/<pdk>/
    gds/<cell>.gds
    netlists/<cell>.spice          <-- written by run_cell_drc.py
    reports/<cell>.lyrdb
    summary.json

This script iterates the cells whose GDS + netlist are present, calls
``pdk.lvs_netgen``, and emits ``summary.json`` + ``junit.xml`` mirroring the
DRC runner's shape so the same workflow plumbing (artifact upload, JUnit
publication) works.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "drc"))
from run_cell_drc import _resolve_pdk 

sys.path.insert(0, str(Path(__file__).resolve().parent))
from klayout_gf180 import run_lvs_klayout_gf180  


def _parse_lvs_report(text: str) -> Dict[str, Any]:
    """Lightweight parse of a netgen LVS report.

    Looks for the canonical 'Circuits match uniquely' / 'Netlists match' lines
    and pulls counts of mismatched nets and instances if present. Returns a
    dict suitable for embedding in summary.json.
    """
    summary: Dict[str, Any] = {
        "is_pass": False,
        "conclusion": "LVS inconclusive",
        "first_cause": None,
        "unmatched_nets": 0,
        "unmatched_instances": 0,
        "raw_tail": text[-1200:] if text else "",
    }
    if not text:
        return summary
    # Surface the most common environment failures explicitly so the CI
    # status doesn't read as the catch-all "LVS inconclusive". The gf180
    # klayout deck's `run_lvs.py` imports `docopt` and `klayout.db` before
    # doing any work, and a missing module aborts the whole script —
    # without these branches the `lvs.rpt` is just a Python traceback and
    # the runner reports it as "LVS inconclusive (0 mismatches)".
    if "ModuleNotFoundError: No module named 'docopt'" in text:
        summary["conclusion"] = "missing dep: docopt"
        return summary
    if "ModuleNotFoundError: No module named 'klayout'" in text:
        summary["conclusion"] = "missing dep: klayout"
        return summary
    if "klayout: command not found" in text or "klayout: not found" in text:
        summary["conclusion"] = "klayout binary not on PATH"
        return summary
    if "Netlists match" in text or "Circuits match uniquely" in text:
        summary["is_pass"] = True
        summary["conclusion"] = "Netlists match"
    elif (
        "Netlists do not match" in text
        or "Netlist mismatch" in text
        # gf180 klayout deck emits this exact phrasing on a failed compare.
        or "Netlists don't match" in text
    ):
        summary["conclusion"] = "Netlists do not match"

    summary["unmatched_nets"] = sum(1 for _ in re.finditer(r"\(no matching net\)", text))
    summary["unmatched_instances"] = sum(1 for _ in re.finditer(r"\(no matching instance\)", text))
    if not summary["unmatched_nets"]:
        summary["unmatched_nets"] = sum(
            1 for _ in re.finditer(r"is not matching any net from reference netlist", text)
        )
    m = re.search(r"^LIKELY ROOT CAUSE\n\s+(.+)$", text, re.MULTILINE)
    if m:
        summary["first_cause"] = m.group(1).strip()
    # Failures with no per-net log() entries (device/subcircuit-level) leave the
    # net regex above at 0. lvsdb_report's TOTAL ISSUES counts every xref bucket.
    m = re.search(r"^TOTAL ISSUES: (\d+)$", text, re.MULTILINE)
    if m and not summary["unmatched_nets"]:
        summary["unmatched_nets"] = int(m.group(1))
    if summary["unmatched_nets"] or summary["unmatched_instances"]:
        summary["is_pass"] = False
        if "match" in summary["conclusion"].lower() and "do not" not in summary["conclusion"].lower():
            summary["conclusion"] = "Mismatches found"
    return summary


def _write_junit(results: List[dict], pdk: str, out: Path) -> None:
    suite = ET.Element(
        "testsuite",
        attrib={
            "name": f"glayout-lvs-{pdk}",
            "tests": str(len(results)),
            "failures": str(sum(1 for r in results if r["status"] == "fail")),
            "errors": str(sum(1 for r in results if r["status"] == "error")),
            "skipped": str(sum(1 for r in results if r["status"] == "skip")),
        },
    )
    for r in results:
        case = ET.SubElement(
            suite, "testcase",
            attrib={"classname": f"lvs.{pdk}", "name": r["cell"]},
        )
        if r["status"] == "fail":
            ET.SubElement(case, "failure", attrib={"message": r.get("message", "LVS mismatch")}).text = json.dumps(r, indent=2)
        elif r["status"] == "error":
            ET.SubElement(case, "error", attrib={"message": r.get("message", "LVS error")}).text = json.dumps(r, indent=2)
        elif r["status"] == "skip":
            ET.SubElement(case, "skipped", attrib={"message": r.get("message", "skipped")})
    ET.ElementTree(suite).write(out, encoding="utf-8", xml_declaration=True)


def _enumerate_cells(inputs_dir: Path) -> List[str]:
    """Cells that have BOTH a GDS and a reference netlist."""
    gds = {p.stem for p in (inputs_dir / "gds").glob("*.gds")} if (inputs_dir / "gds").is_dir() else set()
    nets = {p.stem for p in (inputs_dir / "netlists").glob("*.spice")} if (inputs_dir / "netlists").is_dir() else set()
    return sorted(gds & nets)


def _run_one_lvs(item: dict) -> dict:
    """Run LVS for one cell. Designed for ProcessPoolExecutor.

    sky130 uses magic+netgen (`pdk.lvs_netgen`). gf180 uses the gf180mcu
    PDK's official klayout LVS deck — magic+netgen mis-extracts the gf180
    substrate (NMOS bulks merge into VDD via the n-well), so we drive the
    deck's own run_lvs.py instead. See tests/lvs/klayout_gf180.py.
    """
    name = item["name"]
    pdk_name = item["pdk"]
    gds_path = item["gds_path"]
    netlist_path = item["netlist_path"]
    out_dir = Path(item["out_dir"])
    rpt_dir = Path(item["rpt_dir"])
    result: Dict[str, Any] = {"cell": name, "pdk": pdk_name, "status": "skip"}
    try:
        print(f"[LVS]  {name}", flush=True)
        if pdk_name == "gf180":
            ret = run_lvs_klayout_gf180(
                layout=str(gds_path),
                design_name=name,
                netlist=str(netlist_path),
                output_file_path=str(rpt_dir),
                mim_option=item.get("mim_option"),
            )
        else:
            pdk = _resolve_pdk(pdk_name)
            ret = pdk.lvs_netgen(
                layout=str(gds_path),
                design_name=name,
                netlist=str(netlist_path),
                output_file_path=str(rpt_dir),
            )
    except Exception as exc:
        result.update({"status": "error", "message": f"lvs failed: {exc}", "trace": traceback.format_exc()})
        print(f"[ERROR] {name}: {exc}", flush=True)
        return result
    rpt_file = rpt_dir / "lvs" / name / f"{name}_lvs.rpt"
    report_text = rpt_file.read_text() if rpt_file.exists() else ""
    parsed = _parse_lvs_report(report_text)
    result.update({
        "summary": parsed,
        "subproc_code": ret.get("subproc_code") if isinstance(ret, dict) else None,
        "report": str(rpt_file.relative_to(out_dir)) if rpt_file.exists() else None,
    })
    if not rpt_file.exists():
        result["status"] = "error"
        result["message"] = "lvs report not produced"
    elif parsed["is_pass"]:
        result["status"] = "pass"
        result["message"] = "Netlists match"
    else:
        result["status"] = "fail"
        mismatches = parsed["unmatched_nets"] + parsed["unmatched_instances"]
        cause = (ret.get("first_cause") if isinstance(ret, dict) else None) \
                or parsed.get("first_cause")
        base = f"{parsed['conclusion']} ({mismatches} mismatch{'es' if mismatches != 1 else ''})"
        result["message"] = f"{base} — {cause}" if cause else base
    print(f"[{result['status'].upper()}] {name}: {result.get('message','')}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdk", required=True, choices=["sky130", "gf180"])
    parser.add_argument(
        "--inputs-dir", required=True,
        help="Directory containing gds/<cell>.gds and netlists/<cell>.spice (DRC artifact root for the PDK).",
    )
    parser.add_argument("--out-dir", default="lvs_results")
    parser.add_argument(
        "--cells",
        default=None,
        help="Comma-separated cell names; default runs every cell with both GDS+netlist.",
    )
    parser.add_argument(
        "--skip-cells",
        default="differential_to_single_ended_converter,nmos_narrow,pmos_narrow",
        help=(
            "Comma-separated cell names to skip when --cells is not specified. "
            "Default skips differential_to_single_ended_converter (Magic mis-extracts "
            "its PMOS bulk; the cell can still be tested by passing --cells "
            "differential_to_single_ended_converter) and nmos_narrow/pmos_narrow, "
            "which are DRC regression cells for the dogbone diffusion: they are bare "
            "primitives, their reference subckt is named after the device rather than "
            "the cell, and LVS aborts with 'no schematic counterpart' instead of "
            "reporting anything useful."
        ),
    )
    parser.add_argument(
        "--mim-option", choices=["A", "B"], default=None,
        help=(
            "gf180 MIM stack the deck should extract: A (met2/FuseTop/met3) "
            "or B (met4/FuseTop/met5). They are mutually exclusive at process "
            "level, so picking the wrong one extracts no capacitor and every "
            "MIM reports as missing from the layout. glayout builds option B "
            "(mimcap/mimcap_array default to option=\"B\"), so that is the "
            "default here too. Default: $GF180_MIM_OPTION, else B."
        ),
    )
    parser.add_argument(
        "--jobs", "-j", type=int, default=max(1, (os.cpu_count() or 2) - 1),
        help="Worker processes for parallel LVS (default: cpu_count-1).",
    )
    args = parser.parse_args()

    inputs_dir = Path(args.inputs_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    rpt_dir = out_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    rpt_dir.mkdir(parents=True, exist_ok=True)

    cells = _enumerate_cells(inputs_dir)
    if not cells:
        print(f"no cells found under {inputs_dir} (expected gds/ and netlists/)", file=sys.stderr)
        return 2

    if args.cells:
        wanted = {c.strip() for c in args.cells.split(",") if c.strip()}
        missing = wanted - set(cells)
        if missing:
            print(f"warning: cells without inputs: {sorted(missing)}", file=sys.stderr)
        cells = [c for c in cells if c in wanted]
    elif args.skip_cells:
        skip = {c.strip() for c in args.skip_cells.split(",") if c.strip()}
        skipped = [c for c in cells if c in skip]
        cells = [c for c in cells if c not in skip]
        for s in skipped:
            print(f"skipping cell on the --skip-cells list: {s}")

    work_items = [
        {
            "name": name,
            "pdk": args.pdk,
            "gds_path": str(inputs_dir / "gds" / f"{name}.gds"),
            "netlist_path": str(inputs_dir / "netlists" / f"{name}.spice"),
            "out_dir": str(out_dir),
            "rpt_dir": str(rpt_dir),
            "mim_option": args.mim_option,
        }
        for name in cells
    ]
    jobs = max(1, min(args.jobs, len(work_items)))
    print(f"running {len(work_items)} cells with {jobs} worker(s)")
    from concurrent.futures import ProcessPoolExecutor, as_completed
    results: List[dict] = []
    if jobs == 1:
        for item in work_items:
            results.append(_run_one_lvs(item))
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(_run_one_lvs, item): item["name"] for item in work_items}
            for fut in as_completed(futures):
                results.append(fut.result())
    name_order = {n: i for i, n in enumerate(cells)}
    results.sort(key=lambda r: name_order.get(r["cell"], len(name_order)))

    summary = {
        "pdk": args.pdk,
        "total": len(results),
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
        "error": sum(1 for r in results if r["status"] == "error"),
        "skip": sum(1 for r in results if r["status"] == "skip"),
        "results": results,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    _write_junit(results, args.pdk, out_dir / "junit.xml")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    return 0 if summary["fail"] == 0 and summary["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

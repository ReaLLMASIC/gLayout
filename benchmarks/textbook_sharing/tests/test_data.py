"""Consistency of the shipped case data and of the run records (when extracted into <runs>)."""
import json, hashlib, collections
import pytest
from textbook_sharing import paths


def test_case_manifests():
    dirs = sorted(paths.CASES.glob("*/*/*/manifest.json"))
    assert len(dirs) == 639                       # 648 requests minus 9 parameter-illegal ones
    for m in dirs:
        man = json.load(open(m))
        for name, sha in man.items():
            assert hashlib.sha256((m.parent / name).read_bytes()).hexdigest() == sha, (m.parent, name)


def test_case_build_counts():
    recs = json.load(open(paths.RESULTS / "case_build.json"))
    c = collections.Counter(r["stage"] for r in recs)
    assert len(recs) == 648 and c["parameter_illegal"] == 9 and c["schematic_not_qualified"] == 88 and c["qualified"] == 551


@pytest.mark.skipif(not (paths.GRID_RUNS).exists(), reason="run records not extracted (tar -xJf results/run_records.tar.xz)")
def test_ledger_matches_records():
    L = json.load(open(paths.RESULTS / "count_ledger.json"))["cases"]
    assert (L["requested"], L["formal_entries"], L["mode_rows"]["total"]) == (648, 547, 2204)
    assert L["mode_rows"]["by_status"] == {"auto_passed": 1608, "NA": 592, "spec_failed": 4}

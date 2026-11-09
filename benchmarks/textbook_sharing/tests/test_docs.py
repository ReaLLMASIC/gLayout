"""The documents agree with the result tables: the generated documents are up to date, and every number quoted in the
hand-written documents is the number in results/."""
import json, tarfile
from textbook_sharing import paths
from textbook_sharing.analysis import report


def J(name):
    return json.load(open(paths.RESULTS / name))


def doc(name):
    return " ".join((paths.ROOT / name).read_text().split())      # whitespace-normalised, so line breaks do not matter


def pct(x, nd=1):
    return f"{100 * x:.{nd}f}"


def present(name, expected):
    text = doc(name)
    missing = [e for e in expected if " ".join(e.split()) not in text]
    assert not missing, f"{name}: {missing}"


def test_generated_documents_are_current():
    assert (paths.ROOT / "docs/PARAMETER_SPACE.md").read_text() == report.parameter_space()
    assert (paths.ROOT / "docs/RESULTS.md").read_text() == report.results()


def test_readme():
    ex = J("analysis/running_example.json"); st = ex["steps"]
    L = J("count_ledger.json")["cases"]; bt = J("analysis/benchmark_table.json")
    cd = J("analysis/cost_decomposition.json"); c = cd["by_mode"]["combined"]; im = cd["increase_mechanisms"]
    ho = J("analysis/cost_validation_heldout.json")["summary"]; sel = J("analysis/selection_summary.json")["summary"]["by_method"]
    sa = J("analysis/scope_audit.json"); b = sa["interface_comparison"]["base-gLayout interface"]
    sharing = sum(1 for r in bt["rows"] if r["outcomes"].get("formal") and r["modes_applicable_in_formal"])
    assert {round(s["gain_db"], 1) for s in st} == {round(st[-1]["gain_db"], 1)} and {round(s["ugf_hz"] / 1e6, 1) for s in st} == {round(st[-1]["ugf_hz"] / 1e6, 1)}
    present("README.md", [
        f"unshared layout is {st[0]['area_um2']:.1f} um^2",
        f"{st[-1]['area_um2']:.1f} um^2, {pct(-st[-1]['change_vs_unshared'])} % smaller",
        f"the gain ({st[-1]['gain_db']:.1f} dB) and unity-gain frequency ({st[-1]['ugf_hz'] / 1e6:.1f} MHz)",
        f"gives {ex['named_mode_combined']['area_um2']:.1f} um^2",
        f"{L['requested']} requests (18 topologies x 3 PDKs x 12 sizes) give {L['formal_entries']} formal entries in "
        f"{bt['totals']['topologies_with_formal_entries']} topologies; {sharing} topologies admit sharing",
        f"makes {c['classes']['positive']} of {c['n']} verified layouts smaller (mean {pct(c['mean_rel'])} %, up to {pct(c['min_rel'])} %)",
        f"Of the {im['n']} area increases over all modes, {im['assembly_only']} come from routing and row assembly",
        f"and {im['by_primary']['wider_row']} from a shared cell",
        f"for {pct(ho['sign_correct'] / ho['n_pairs'], 0)} % of the pairs",
        f"within {pct(sel['cost_rank']['1']['gap_balanced_when_found'])} % of the best of a 64-plan catalogue",
        f"in {sa['best_known_source']['model proposal']} of {sa['task_sets']['model_tasks']} tasks",
        f"{b['sessions_equal_to_reference']} of {b['sessions']} sessions end at the unshared area",
        f"{len(list(paths.CASES.glob('*/*/*/case.json')))} case folders"])


def test_models_doc():
    sa = J("analysis/scope_audit.json"); b = sa["interface_comparison"]["base-gLayout interface"]; s = sa["interface_comparison"]["sharing interface"]
    li = J("analysis/llm_interface.json"); au = J("analysis/agent_session_audit.json")["summary"]
    oai = [x for x in J("analysis/llm_summary.json")["sessions"] if x["tag"].startswith("openai")]
    present("docs/MODELS.md", [
        f"In {sa['best_known_source']['model proposal']} of the {sa['task_sets']['model_tasks']} tasks a model found",
        f"{b['sessions_equal_to_reference']} of {b['sessions']} sessions end at the area of the unshared layout",
        f"the same model saves {pct(-s['vs_reference'])} % on average",
        f"is on average {pct(li['summary']['capability']['mean_gap_of_best_base_expressible_candidate'])} % above",
        f"All {len(oai) + li['summary']['base']['sessions']} OpenAI sessions ({len(oai)} main, {li['summary']['base']['sessions']} interface comparison)",
        f"Of the {au['sessions']} sessions, {au['clean']} made only allowed calls; {au['in_folder_edit_sessions']} also edited",
        f"{au['auto_flagged']} were flagged automatically",
        f"The first {au['launch_text_counts']['A']} sessions received launch text A, the last {au['launch_text_counts']['B']} text B"])
    assert all(x["isolation_breach"] is False for x in oai)
    assert au["after_manual_review"]["foreign_information_access"] == 0


def test_verification_doc():
    rs = J("analysis/resim_after_testbench_fix.json")["counts"]
    worse = sum(n for k, n in rs.items() if k.startswith("auto_passed->") and not k.endswith("auto_passed"))
    pex = J("analysis/pex_sensitivity_C10_gf180.json")[0]["rc_measures"]
    assert worse == 0
    present("docs/VERIFICATION.md", [f"no passing layout failed, {rs.get('spec_failed->auto_passed', 0)} failing layouts passed",
                                     f"settled {abs(pex['vo1'] - pex['vo2']):.2f} V apart"])


def test_data_doc():
    cases = list(paths.CASES.glob("*/*/*/case.json")); nominal = list((paths.DATA / "nominal").glob("*/*.json"))
    build = J("case_build.json")
    with tarfile.open(paths.RESULTS / "run_records.tar.xz") as t:
        files = sum(1 for m in t.getmembers() if m.isfile())
    present("docs/DATA.md", [f"JSON and model text ({files:,} files)".replace(",", " "), f"passed the size derivation ({len(cases)})", f"every topology and PDK ({len(nominal)})",
                             f"one record per request ({len(build)})",
                             f"including the {sum(r['stage'] == 'parameter_illegal' for r in build)} parameter-illegal ones"])

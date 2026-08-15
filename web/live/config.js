/* Where the live dashboard fetches runner output from.
 *
 * It expects <base>/<stage>_results/<pdk>/summary.json for each stage
 * (drc, lvs, sim) and PDK. Missing files are skipped, so a PDK without
 * simulation simply shows no ngspice column.
 *
 * The docs workflow rewrites this file at deploy time so the base tracks the
 * repository it was built from, and run_webpage.sh rewrites the staged copy to
 * point at locally served results.
 */
window.GLAYOUT_LIVE = {
  resultsBase:
    "https://raw.githubusercontent.com/ReaLLMASIC/gLayout/main/",
  pdks: ["sky130", "gf180"]
};

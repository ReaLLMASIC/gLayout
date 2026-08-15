#!/usr/bin/env bash
# Build and serve the Glayout GitHub Pages site locally.
#
# Mirrors what the `build` job in .github/workflows/docs.yml does:
#   1. assemble _site/    -> docs/* overlaid (live dashboard at /live/)
#   2. point the dashboard at a results URL
#   3. sphinx-build       -> Sphinx HTML on top of _site/
#   4. python http.server -> serve _site/ on http://localhost:$PORT/
#
# Usage:
#   ./run_webpage.sh              # build + serve on :8000
#   ./run_webpage.sh 8080         # build + serve on :8080
#   ./run_webpage.sh --no-build   # skip rebuild, just serve existing _site/
#   ./run_webpage.sh --live       # dashboard only: stage _site/ from web/ but
#                                 # skip the Sphinx build — much faster
#                                 # iteration loop when only touching the
#                                 # browser dashboard. Doc pages 404 in this
#                                 # mode; the dashboard at /live/ works.
#   ./run_webpage.sh --strict     # fail if sim_results/results.json is absent
#                                 # instead of falling back to sample data
set -euo pipefail

cd "$(dirname "$0")"

# Portable in-place sed.
#
# GNU sed (Linux) takes `-i` with no argument; BSD sed (macOS) takes
# `-i <ext>` and creates `<file><ext>` as a backup. The form `-i.bak`
# (extension attached to the flag, no space) is accepted by both, so we
# use that and clean up the .bak files afterwards.
sed_inplace() {
    local script="$1"; shift
    sed -i.bak -E "$script" "$@"
    for f in "$@"; do
        rm -f "${f}.bak"
    done
}

PORT=8000
REBUILD=1
LIVE_ONLY=0
STRICT=0
for arg in "$@"; do
    case "$arg" in
        --no-build) REBUILD=0 ;;
        --live) LIVE_ONLY=1 ;;
        --strict) STRICT=1 ;;
        --help|-h)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            if [[ "$arg" =~ ^[0-9]+$ ]]; then
                PORT="$arg"
            else
                echo "error: unrecognised argument '$arg'" >&2
                exit 2
            fi
            ;;
    esac
done

# Resolve the results root the same way sphinx/conf.py does: a local run puts
# <stage>_results/<pdk>/summary.json at the repo root; otherwise fall back to
# the committed sample so a bare checkout still builds.
RESULTS_ROOT="."
if ! ls ./*_results/*/summary.json >/dev/null 2>&1; then
    if [ "$STRICT" -eq 1 ]; then
        echo "error: no <stage>_results/<pdk>/summary.json found (--strict)" >&2
        echo "       run the DRC workflow, then:" >&2
        echo "       python tests/sim/run_cell_sim.py --pdk sky130 \\" >&2
        echo "         --inputs-dir drc_results/sky130 --out-dir sim_results/sky130" >&2
        exit 1
    fi
    echo "==> no local runner output; falling back to sphinx/data/sample"
    RESULTS_ROOT="sphinx/data/sample"
else
    echo "==> using local runner output:"
    ls -1 ./*_results/*/summary.json | sed 's|^|    |'
fi

# The dashboard fetches <base>/<stage>_results/<pdk>/summary.json. A file://
# fetch is blocked by CORS, so copy the summaries into _site/ and point the
# staged config at them relatively.
LIVE_BASE="../"

stage_results() {
    # $1 = destination site root
    for src in "$RESULTS_ROOT"/*_results/*/summary.json; do
        [ -f "$src" ] || continue
        rel="${src#"$RESULTS_ROOT"/}"
        mkdir -p "$1/$(dirname "$rel")"
        cp "$src" "$1/$rel"
    done
    cat > "$1/live/config.js" <<JS
window.GLAYOUT_LIVE = {
  resultsBase: "$LIVE_BASE",
  pdks: ["sky130", "gf180"]
};
JS
}

# Fast path: stage _site/ from web/ but skip the Sphinx build. Useful when
# only editing the dashboard's HTML/JS, which needs no Sphinx involvement.
#
# Note this still stages into _site/ rather than serving docs/ directly, so the
# committed docs/live/config.js is never rewritten in place — a dirty working
# tree after a docs preview is a nasty surprise before a commit.
if [ "$LIVE_ONLY" -eq 1 ]; then
    if [ "$REBUILD" -eq 1 ]; then
        echo "==> staging _site/ from web/ (no Sphinx build)"
        rm -rf _site
        mkdir _site
        cp -r web/. _site/
        stage_results _site
    elif [ ! -d _site ]; then
        echo "error: _site/ does not exist; rerun without --no-build" >&2
        exit 1
    fi
    echo "==> serving _site/ on http://localhost:${PORT}/"
    echo "    Dashboard: http://localhost:${PORT}/live/"
    echo "    (--live: no Sphinx build, so doc pages will 404)"
    echo "    (Ctrl-C to stop)"
    exec python3 -m http.server --directory _site "$PORT"
fi

# Sphinx runner: prefer uv when available, fall back to whatever sphinx-build
# is on PATH. Glayout installs with pip, so uv is a convenience, not a
# requirement.
if command -v uv >/dev/null 2>&1 && [ -f pyproject.toml ]; then
    SPHINX="uv run sphinx-build"
    SYNC="uv sync --group docs"
elif command -v sphinx-build >/dev/null 2>&1; then
    SPHINX="sphinx-build"
    SYNC=""
else
    echo "error: neither 'uv' nor 'sphinx-build' found on PATH" >&2
    echo "       pip install sphinx furo myst-parser" >&2
    exit 1
fi

if [ "$REBUILD" -eq 1 ]; then
    if [ -n "$SYNC" ]; then
        echo "==> $SYNC"
        $SYNC
    fi

    echo "==> assembling _site/ from web/"
    rm -rf _site
    mkdir _site
    cp -r web/. _site/

    # Serve the summaries alongside the site so the dashboard can fetch them
    # without network access, and point the staged config.js at them.
    stage_results _site

    echo "==> sphinx-build sphinx -> _site/"
    export GLAYOUT_RESULTS_ROOT="$(cd "$RESULTS_ROOT" && pwd)"
    if [ "$STRICT" -eq 1 ]; then
        GLAYOUT_RESULTS_STRICT=1 $SPHINX -b html --keep-going sphinx _site
    else
        $SPHINX -b html --keep-going sphinx _site
    fi
    touch _site/.nojekyll
else
    if [ ! -d _site ]; then
        echo "error: _site/ does not exist; rerun without --no-build" >&2
        exit 1
    fi
fi

echo
echo "==> serving _site/ on http://localhost:${PORT}/"
echo "    Dashboard: http://localhost:${PORT}/live/"
echo "    (Ctrl-C to stop)"
exec python3 -m http.server --directory _site "$PORT"

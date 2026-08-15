# Glayout documentation source

Sphinx source for the Glayout documentation site.

```bash
cd ..
uv sync --group docs      # or: pip install sphinx furo myst-parser
./run_webpage.sh          # assembles _site/, builds, serves on :8000
```

Result tables are generated from `sim_results/results.json` by the directives in
`_ext/glayout_results.py`. Do not edit them by hand. If no results file exists,
the build falls back to `data/results.sample.json`.

- `_ext/glayout_results.py` — directives rendering the results tables
- `data/results.sample.json` — fallback data and schema reference
- `../docs/live/` — standalone live dashboard, deployed as a sibling path

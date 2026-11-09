# How to Run the gLayout Tutorials

This document covers two supported environments:

- **iic-osic-tools docker image** (`hpretl/iic-osic-tools`) — the primary, batteries-included setup. All EDA tools, both PDKs (sky130 and gf180mcu), and the right env vars are pre-baked.
- **Bare conda/venv** on a Linux host — for users who already have the EDA toolchain installed locally and want to iterate without docker.

Both flows resolve to the same notebooks. The bootstrap cell at the top of every EDA-touching notebook detects whichever environment it's running in and fills in any missing variables, so the notebook bodies are the same in both places.

---

## What each tutorial needs

| Tutorial | Tools required | PDK needed | Notes |
|---|---|---|---|
| `GLayout_Introduction.ipynb` | klayout (for `.show()` only) | sky130 + gf180 import time | Pure layout. |
| `GLayout_Via.ipynb` | klayout | sky130 + gf180 | Pure layout. |
| `GLayout_Cmirror.ipynb` | klayout | sky130 + gf180 | Pure layout. |
| `GLayout_Cells.ipynb` | klayout | gf180 | Layout-only walkthrough of every built-in cell, including a full opamp. |
| `glayout_tutorial_FVF_part1.ipynb` | klayout | gf180 | Generates `tutorial/FVF/my_FVF.py` helper used by part 2. Runs klayout DRC at the end. |
| `glayout_tutorial_FVF_part2.ipynb` | klayout, **magic**, **netgen**, **ngspice** | gf180 | LVS + Magic-based PEX + ngspice AC sweep. Run part 1 first. |
| `glayout_tutorial_INV_part1.ipynb` | klayout | gf180 | Generates `tutorial/INV/my_INV.py` helper used by part 2. |
| `glayout_tutorial_INV_part2.ipynb` | klayout, magic, netgen | gf180 | LVS + Magic-based PEX. Run part 1 first. |
| `glayout_opamp.ipynb` | klayout | sky130 | Generates and shows a two-stage opamp. The RL-optimization section is documented but lives in the OpenFASOC repo — see the markdown cell in the notebook. |
| `BJT_tutorials/test_bjt_glayout.ipynb` | klayout, magic | gf180 | BJT layout + magic extraction. |
| `BJT_tutorials/test_bjt_custom_pattern.ipynb` | klayout | gf180 | BJT custom-pattern routing demo. Writes a GDS into `tutorial/out/`. |
| `BJT_tutorials/test_bjt_gdsfactory.ipynb` | klayout, magic | gf180 | BJT built via raw gdsfactory + extraction. |

PDK column lists what's needed *at runtime*. `glayout`'s gf180 module reads `PDK_ROOT` at **import time**, so even notebooks that don't run gf180 DRC need `PDK_ROOT` set to *something*.

---

## Required environment variables

| Variable | Purpose | Example (iic-osic-tools) | Example (bare local) |
|---|---|---|---|
| `PDK_ROOT` | Root directory holding the PDK install. Used at glayout import time to compute magic/netgen paths. | `/foss/pdks` | `/home/you/openmpw/pdk/volare/gf180mcu/versions/<hash>` |
| `PDK` | Which PDK variant to use. Used by the magic-DRC/LVS helpers to find `${PDKPATH}/libs.tech/magic/${PDK}.magicrc` etc. | `gf180mcuD` (or `sky130A`) | `gf180mcuD` |
| `PDKPATH` | Full path to the specific PDK variant directory. The bootstrap cell auto-derives this as `$PDK_ROOT/$PDK` if you don't set it. | `/foss/pdks/gf180mcuD` | `$PDK_ROOT/$PDK` |
| `GLAYOUT_SKIP_EXTRESIST` | Optional. When set (sets `1`), the PEX cells in the FVF/INV/BJT tutorials skip magic's `extresist` pass and extract devices + capacitance only — full RC extraction takes minutes on a flattened design. Leave unset locally to run the full flow. | `1` | unset |

The bootstrap cell at the top of every PDK-touching notebook does:

1. `source ~/.bashrc 2>/dev/null && printenv` so iic-osic-tools' shell-set vars are inherited by the kernel even when the kernel was started from a menu launcher.
2. `os.environ.setdefault(...)` so anything you exported in the calling shell wins.
3. Computes `PDKPATH=$PDK_ROOT/$PDK` if `PDKPATH` isn't already set.

So in practice: in iic-osic-tools you don't need to do anything. In a bare local setup you need to export `PDK_ROOT` and `PDK` (and optionally `PDKPATH`).

---

## Running inside iic-osic-tools (recommended)

The image already provides klayout, magic, netgen, ngspice, and both PDKs under `/foss/pdks`. `PDK_ROOT`, `PDK`, `PDKPATH` are set in the image's `~/.bashrc`.

**One important gotcha**: recent `hpretl/iic-osic-tools` builds ship Python **3.12** with **gdsfactory 9.x** and **numpy 2.x**, while `glayout` is written against **gdsfactory 7.x** and **numpy 1.x**. We work around that by installing `glayout` into a Python venv that pins those two deps, and registering the venv as a dedicated Jupyter kernel. Verified against tag `hpretl/iic-osic-tools:chipathon` — all 12 tutorials pass end-to-end.

### One-time setup inside the container

```bash
# 1. Start the image with this repo mounted at /foss/designs/gLayout:
#    docker run -it --rm \
#      -v "$PWD":/foss/designs/gLayout \
#      -p 8888:8888 hpretl/iic-osic-tools:latest bash
# (Or use the existing chipathon container and copy the repo into /foss/designs/.)

# 2. Source bashrc so PDK_ROOT / PDK / PDKPATH and the EDA-tool PATH are set:
source ~/.bashrc

# 3. Create a venv that inherits the container's site-packages (klayout,
#    matplotlib, pandas, etc.) but lets us pin gdsfactory + numpy:
python3.12 -m venv --system-site-packages /tmp/glayout-venv
source /tmp/glayout-venv/bin/activate

# 4. Make sure the venv's gdsfactory 7.x and numpy 1.x shadow the system
#    versions. The bashrc-set PYTHONPATH would otherwise put the system
#    site-packages first, so we drop it for the rest of this shell:
unset PYTHONPATH

# 5. Install pinned deps and glayout itself:
pip install "gdsfactory>6.0.0,<=7.7.0" "numpy<2" gdstk svgutils ipykernel
cd /foss/designs/gLayout
pip install --no-deps -e .

# 6. Register the venv as a dedicated Jupyter kernel and force PYTHONPATH=""
#    inside it (so the kernel doesn't inherit the system gdsfactory):
python -m ipykernel install --user --name glayout-venv --display-name "glayout-venv"
cat > ~/.local/share/jupyter/kernels/glayout-venv/kernel.json <<'EOF'
{
 "argv": ["/tmp/glayout-venv/bin/python", "-Xfrozen_modules=off",
          "-m", "ipykernel_launcher", "-f", "{connection_file}"],
 "display_name": "glayout-venv",
 "language": "python",
 "metadata": {"debugger": true},
 "env": {"PYTHONPATH": ""}
}
EOF
```

### Per-session

```bash
source ~/.bashrc
source /tmp/glayout-venv/bin/activate
unset PYTHONPATH
cd /foss/designs/gLayout/tutorial
jupyter notebook --ip=0.0.0.0 --no-browser --allow-root
```

When you open a notebook, **switch the kernel to `glayout-venv`** via *Kernel → Change kernel*. The first cell of the notebooks is the env bootstrap; if you didn't `source ~/.bashrc` before starting Jupyter, the bootstrap will re-source it for you.

Then run notebooks in this order if you plan the full FVF/INV walk-through:

- `…_FVF_part1.ipynb` → `…_FVF_part2.ipynb`
- `…_INV_part1.ipynb` → `…_INV_part2.ipynb`

(Part 1 writes the `my_FVF.py` / `my_INV.py` helper module that part 2 imports.)

### Headless / CI alternative

If you just want to verify everything runs without opening Jupyter:

```bash
source ~/.bashrc && source /tmp/glayout-venv/bin/activate && unset PYTHONPATH
cd /foss/designs/gLayout/tutorial
for nb in GLayout_*.ipynb glayout_*part1.ipynb glayout_*part2.ipynb \
          glayout_opamp.ipynb BJT_tutorials/*.ipynb; do
  jupyter nbconvert --to notebook --execute \
    --ExecutePreprocessor.timeout=180 \
    --ExecutePreprocessor.kernel_name=glayout-venv \
    --output "/tmp/$(basename $nb .ipynb)__executed.ipynb" "$nb"
done
```

---

## Running in a bare conda/venv on Linux

### 1. Install EDA tools

You need klayout (≥ 0.29 OK; the deck supports both `<0.29` and `>0.29` argument conventions), magic, netgen, ngspice on `PATH`.

Quick check:
```bash
for t in klayout magic netgen ngspice; do
  command -v "$t" >/dev/null && echo "OK $t -> $(command -v "$t")" || echo "MISSING $t"
done
```

**Known wart:** the netgen wrapper (`bin/netgen`) ships with `#!/bin/sh` but uses bash-only parameter substitution. On Ubuntu where `/bin/sh` is `dash`, you'll see `Bad substitution` errors. `glayout` works around this by invoking netgen via `bash $(which netgen)` explicitly, so you don't need to patch the wrapper.

### 2. Install the PDKs (volare)

[Volare](https://github.com/efabless/volare) is the easiest way:

```bash
pip install volare
mkdir -p ~/pdk
volare enable --pdk sky130 --pdk-root ~/pdk
volare enable --pdk gf180mcu --pdk-root ~/pdk
```

After this:
- sky130 lives at `~/pdk/sky130/versions/<hash>/{sky130A,sky130B}`
- gf180mcu lives at `~/pdk/gf180mcu/versions/<hash>/{gf180mcuA,…,gf180mcuD}`

### 3. Create a conda env and install glayout editable

```bash
conda create -n gLayout python=3.10 -y
conda activate gLayout
cd /path/to/gLayout
pip install -e .
pip install jupyter ipykernel nbconvert
```

### 4. Export the env vars

For the FVF / INV / BJT tutorials (gf180-based):
```bash
export PDK_ROOT=~/pdk/gf180mcu/versions/<hash>
export PDK=gf180mcuD
export PDKPATH=$PDK_ROOT/$PDK
```

For the opamp notebook (sky130-based, but layout-only — `PDKPATH` isn't actually used):
```bash
export PDK_ROOT=~/pdk/sky130/versions/<hash>
export PDK=sky130A
export PDKPATH=$PDK_ROOT/$PDK
```

The bootstrap cell will fill in `PDKPATH` for you if you don't set it, so you can get away with just `PDK_ROOT` and `PDK`.

### 5. Launch Jupyter and run

```bash
cd tutorial
jupyter notebook
```

Same ordering rule as iic-osic-tools: run FVF/INV part 1 before part 2.

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'glayout'"
You installed gLayout into a different Python than the kernel is using. Confirm with `import sys; print(sys.executable)` from inside the notebook, then `pip install -e .` into that same Python.

### "RuntimeError: error running klayout DRC" / "Unable to open file: …/drc/rule_decks/antenna.drc"
You're on an older `glayout` install that points the gf180 DRC at `gf180mcu_drc.lydrc` (which includes rule_deck fragments that aren't bundled). Reinstall from this repo (`pip install -e .`) — the fix routes through a wrapper deck that calls the bundled standalone `gf180mcu.drc`.

### "KeyError: 'PDKPATH'"
The bootstrap cell didn't run, or you don't have `PDK_ROOT` + `PDK` set. Run the first code cell of the notebook explicitly, or `export PDK_ROOT=… PDK=…` and restart the kernel.

### "DRC report file not found" from `gf180.drc_magic(...)`
Magic ran but didn't produce a `.rpt`. Usually means `$PDKPATH/libs.tech/magic/$PDK.magicrc` doesn't exist for the variant you set. Double-check `$PDKPATH` actually exists: `ls $PDKPATH/libs.tech/magic/`.

### "netgen: Bad substitution" or `lvs_netgen` raising `CalledProcessError` immediately
Your `/bin/sh` is dash but the netgen wrapper uses bash syntax. The current `glayout` mainline already forces bash via `bash $(which netgen) …`, so this should be resolved — if you still see it, you're on an older glayout install.

### "Netlists do not match" in the LVS report
This is the LVS report's *content*, not a tool failure. The netgen call still succeeded (exit code 0). The FVF part 2 schematic intentionally doesn't model dummy devices, so a mismatch against the real layout is expected for that tutorial; treat it as illustrative.

### "layer_views for Pdk 'gf180' is None"
You did `comp` as the last line of a cell, which triggers gdsfactory's HTML repr. `glayout`'s gf180 PDK doesn't ship `layer_views`, so this raises. Use `comp.show()` (writes a GDS and opens klayout) or just `print(comp.name)` instead.

### Notebooks 5–8 (FVF/INV) — "ModuleNotFoundError: No module named 'my_FVF'" / "'my_INV'"
You ran part 2 before part 1. Part 1 writes the helper module to `tutorial/FVF/` or `tutorial/INV/`. Run part 1 first, or vendor the helper manually before retrying.

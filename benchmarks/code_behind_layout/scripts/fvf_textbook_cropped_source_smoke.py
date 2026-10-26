"""Development proof that the public compiler runs without evaluation targets."""
import json
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
source = Path("/work/vendor/textbook-sharing-readonly")
out = Path.cwd()
original = Path(os.environ["PROBE_INPUT"])
pack = out / "source_pack"
common = pack / "glayout"
common.mkdir(parents=True)
shutil.copy2(source / "LICENSE", pack / "LICENSE")
shutil.copy2(source / "src/glayout/__init__.py", common / "__init__.py")
for name in ["backend", "pdk", "primitives", "routing", "placement", "spice", "util", "sharing"]:
    shutil.copytree(source / "src/glayout" / name, common / name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
benchmark = source / "benchmarks/textbook_sharing/textbook_sharing"
target = pack / "textbook_sharing"
target.mkdir()
for name in ["__init__.py", "layout.py", "netlist.py"]:
    shutil.copy2(benchmark / name, target / name)
shutil.copytree(benchmark / "assembly", target / "assembly",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
for name in ["circuit_input.json", "sizing_input.json"]:
    shutil.copy2(original / name, pack / name)
sys.path[:0] = [str(pack)]
os.environ["GLAYOUT_BACKEND"] = "gdsfactory"
from glayout import sky130
from textbook_sharing.netlist import Circuit
from textbook_sharing.layout import build

circuit = Circuit.from_json(json.loads((pack / "circuit_input.json").read_text()))
sizing = json.loads((pack / "sizing_input.json").read_text())
layout = build(sky130, circuit, sizing, mode="independent", name="cropped_c08")
layout["component"].write_gds(out / "cropped_c08.gds")
loaded = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
          if (name == "glayout" or name.startswith(("glayout.", "textbook_sharing")))
          and getattr(module, "__file__", None)}
assert all(Path(path).is_relative_to(pack) for path in loaded.values()), loaded
assert not any(name.startswith(("glayout.cells", "glayout.blocks")) for name in loaded)
assert not any((pack / path).exists() for path in ["glayout/cells", "glayout/blocks",
    "textbook_sharing/circuits.py", "textbook_sharing/verify"])
record = {"scope": "development_source_crop_generation_only_not_formal_or_training",
          "source_revision": "1f90e33913208e572744b7c5a144a7da8c073235",
          "included_circuit": "C08", "excluded_target_source_trees": ["glayout.cells", "glayout.blocks"],
          "excluded_full_topology_declarations": True, "excluded_prior_results_and_evaluator": True,
          "generation_succeeded": True, "physical_verification_performed_here": False,
          "loaded_source_modules": loaded,
          "pack_files": sorted(str(p.relative_to(pack)) for p in pack.rglob("*") if p.is_file())}
(out / "source_crop.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({key: value for key, value in record.items()
                  if key not in ["loaded_source_modules", "pack_files"]}, indent=2))

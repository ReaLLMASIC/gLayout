import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / 'src'))

from glayout.blocks.elementary.transmission_gate.transmission_gate import transmission_gate, tg_netlist, add_tg_labels
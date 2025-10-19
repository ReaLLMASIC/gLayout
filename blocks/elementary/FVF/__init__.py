import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / 'src'))

from glayout.blocks.elementary.FVF.fvf import flipped_voltage_follower, fvf_netlist, add_fvf_labels
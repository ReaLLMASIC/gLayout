import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / 'src'))

from glayout.blocks.elementary.current_mirror.current_mirror import current_mirror, current_mirror_netlist, add_cm_labels
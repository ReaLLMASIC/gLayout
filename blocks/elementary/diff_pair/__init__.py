import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / 'src'))

from glayout.blocks.elementary.diff_pair.diff_pair import diff_pair, diff_pair_generic, diff_pair_netlist, add_df_labels
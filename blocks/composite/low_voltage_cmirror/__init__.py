import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / 'src'))

from glayout.blocks.elementary.low_voltage_cmirror.low_voltage_cmirror import low_voltage_cmirror, low_voltage_cmirr_netlist
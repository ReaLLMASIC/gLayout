# Copyright 2022 Efabless Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Run Skywater 130nm LVS.

Usage:
    run_lvs.py (--help| -h)
    run_lvs.py (--design=<layout_path>) (--net=<netlist_path>) [--report=<report_output_path>] [--output_netlist=<output_netlist_path>] [--thr=<thr>] [--run_mode=<run_mode>] [--lvs_sub=<sub_name>] [--no_net_names] [--set_spice_comments] [--set_scale] [--set_verbose] [--set_schematic_simplify] [--set_net_only] [--set_top_lvl_pins] [--set_combine] [--set_purge] [--set_purge_nets]

Options:
    --help -h                                   Print this help message.
    --design=<layout_path>                      The input GDS file path.
    --net=<netlist_path>                        The input netlist file path.
    --report=<report_output_path>               The output database file path.
    --output_netlist=<output_netlist_path>      Output netlist path.
    --thr=<thr>                                 Number of cores to be used by LVS checker
    --run_mode=<run_mode>                       Select klayout mode Allowed modes (flat , deep, tiling). [default: deep]
    --lvs_sub=<sub_name>                        Assign the substrate name used in design.
    --no_net_names                              Discard net names in extracted netlist.
    --set_spice_comments                        Set netlist comments in extracted netlist.
    --set_scale                                 Set scale of 1e6 in extracted netlist.
    --set_verbose                               Set verbose mode.
    --set_schematic_simplify                    Set schematic simplification in input netlist.
    --set_net_only                              Set netlist object creation only in extracted netlist.
    --set_top_lvl_pins                          Set top level pins only in extracted netlist.
    --set_combine                               Set netlist combine only in extracted netlist.
    --set_purge                                 Set netlist purge all only in extracted netlist.
    --set_purge_nets                            Set netlist purge nets only in extracted netlist.
"""

from docopt import docopt
import os
import subprocess
import logging

def main():

    # Switches used in run
    switches = ''

    if args["--run_mode"] in ["flat" , "deep", "tiling"]:
        switches = switches + f'-rd run_mode={args["--run_mode"]} '
    else:
        logging.error("Allowed klayout modes are (flat , deep , tiling) only")
        exit()

    
    if args["--output_netlist"]:
        switches += "-rd target_netlist={} ".format(args["--output_netlist"])

    switches = switches + '-rd spice_net_names=false ' if args["--no_net_names"] else switches + '-rd spice_net_names=true '

    switches = switches + '-rd spice_comments=true ' if args["--set_spice_comments"] else switches + '-rd spice_comments=false '

    switches = switches + '-rd scale=true ' if args["--set_scale"] else switches + '-rd scale=false '

    switches = switches + '-rd verbose=true ' if args["--set_verbose"] else switches + '-rd verbose=false '

    switches = switches + '-rd schematic_simplify=true ' if args["--set_schematic_simplify"] else switches + '-rd schematic_simplify=false '

    switches = switches + '-rd net_only=true ' if args["--set_net_only"] else switches + '-rd net_only=false '

    switches = switches + '-rd top_lvl_pins=true ' if args["--set_top_lvl_pins"] else switches + '-rd top_lvl_pins=false '

    switches = switches + '-rd combine=true ' if args["--set_combine"] else switches + '-rd combine=false '

    switches = switches + '-rd purge=true ' if args["--set_purge"] else switches + '-rd purge=false '

    switches = switches + '-rd purge_nets=true ' if args["--set_purge_nets"] else switches + '-rd purge_nets=false '

    switches = switches + f'-rd lvs_sub={args["--lvs_sub"]} ' if args["--lvs_sub"] else switches


    # Generate databases
    if args["--design"]:
        path = args["--design"]
        if args["--net"]:
            file_name = args["--net"].split('.')
        else:
            print("The script must be given a netlist file or a path to be able to run LVS")
            exit()
        
        if args["--report"]:
            report = args["--report"]
        else:
            report = file_name[0]

        subprocess.check_call(f"klayout -b -r {pdk_root}/{pdk}/sky130.lvs -rd input={path} -rd report={report}.lvsdb -rd schematic={args['--net']} -rd target_netlist=extracted_netlist_{file_name[0]}.cir -rd thr={workers_count} {switches}", shell=True)

    else:
        print("The script must be given a layout file or a path to be able to run LVS")
        exit()


if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG, format=f"%(asctime)s | %(levelname)-7s | %(message)s", datefmt='%d-%b-%Y %H:%M:%S')

    # Args
    args          = docopt(__doc__, version='LVS Checker: 0.1')
    workers_count = os.cpu_count()*2 if args["--thr"] == None else int(args["--thr"])

    # Env. variables
    if os.environ.get('PDK_ROOT') is not None:
        ## if PDK_ROOT is defined, we assume that PDK is defined as well. Will error out if PDK_ROOT only is defined.
        pdk_root = os.environ['PDK_ROOT']
        pdk      = os.environ['PDK']
    else:
        pdk_full_path = os.path.dirname(os.path.abspath(__file__))
        pdk_root = os.path.dirname(pdk_full_path)
        pdk      = os.path.basename(pdk_full_path)

    # ========= Checking Klayout version =========
    klayout_v_ = os.popen("klayout -v").read()
    klayout_v_ = klayout_v_.split("\n")[0]
    klayout_v  = int (klayout_v_.split(".") [-1])

    if klayout_v < 8:
        logging.warning("Using this klayout version has not been assesed in this development. Limits are unknown")
        logging.info(f"Your version is: {klayout_v_}"  )
        logging.info(f"Prerequisites at a minimum: KLayout 0.27.8")

    # Calling main function
    main()

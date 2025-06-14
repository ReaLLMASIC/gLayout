#!/bin/tcsh
#---------------------------------------------------------------
# Shell script setting up all variables used by the qflow scripts
# for this project
#---------------------------------------------------------------

# The LEF file containing standard cell macros

set leffile=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.ref/sky130_osu_sc_15t_ls/lef/sky130_osu_sc_15t_ls.lef

# The SPICE netlist containing subcell definitions for all the standard cells
set spicefile=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.ref/sky130_osu_sc_15t_ls/spice/sky130_osu_sc_15t_ls.spice

# The liberty format file containing standard cell timing and function information
set libertyfile=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.ref/sky130_osu_sc_15t_ls/lib/sky130_osu_sc_15t_ls.lib

# If there is another LEF file containing technology information
# that is separate from the file containing standard cell macros,
# set this.  Otherwise, leave it defined as an empty string.

set techleffile=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.ref/sky130_osu_sc_15t_ls/techlef/sky130_osu_sc_15t_ls.tlef

# All cells below should be the lowest output drive strength value,
# if the standard cell set has multiple cells with different drive
# strengths.  Comment out any cells that do not exist.

set bufcell=BUFX2		;# Minimum drive strength buffer cell
set bufpin_in=A			;# Name of input port to buffer cell
set bufpin_out=Y		;# Name of output port to buffer cell
set clkbufcell=BUFX2		;# Minimum drive strength buffer cell
set clkbufpin_in=A		;# Name of input port to buffer cell
set clkbufpin_out=Y		;# Name of output port to buffer cell

set fillcell=FILL		;# Spacer (filler) cell (prefix, if more than one)
set decapcell="DECAP"		;# Decap (filler) cell (prefix, if more than one)
set antennacell="ANT"		;# Antenna (filler) cell (prefix, if more than one)
set antennapin_in="A"		;# Antenna cell input connection
set bodytiecell=""		;# Body tie (filler) cell (prefix, if more than one)

# yosys tries to eliminate use of these; depends on source .v
set tiehi="TIEHI"		;# Cell to connect to power, if one exists
set tiehipin_out="Y"		;# Output pin name of tiehi cell, if it exists
set tielo="TIELO"		;# Cell to connect to ground, if one exists
set tielopin_out="Y"		;# Output pin name of tielo cell, if it exists

set gndnet="vdd"		;# Name used for ground pins in standard cells
set vddnet="vss"		;# Name used for power pins in standard cells

set separator=""		;# Separator between gate names and drive strengths
set techfile=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.tech/magic/sky130A.tech	    ;# magic techfile
set magicrc=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.tech/magic/sky130A.magicrc    ;# magic startup script
set magic_display="XR" 	;# magic display, defeat display query and OGL preference
set netgen_setup=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.tech/netgen/sky130A_setup.tcl	;# netgen setup file for LVS
set gdsfile=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.ref/sky130_osu_sc_15t_ls/gds/sky130_osu_sc_15t_ls.gds	;# GDS database of standard cells
set verilogfile=/home/donn/.volare/volare/sky130/build/cd1748bb197f9b7af62a54507de6624e30363943/sky130A/libs.ref/sky130_osu_sc_15t_ls/verilog/sky130_osu_sc_15t_ls.v	;# Verilog models of standard cells

# Set a conditional default in the project_vars.sh file for this process
set postproc_options=""
# Normally one does not want to use the top metal for signal routing
set route_layers = 5
set fill_ratios="100,0,0,0"
set fanout_options="-l 100 -c 10"
set addspacers_options="-stripe 1.6 40.0 PG"
set xspice_options="-io_time=250p -time=50p -idelay=20p -odelay=50p -cload=250f"

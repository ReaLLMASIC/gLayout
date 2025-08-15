v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 110 -530 110 -510 {
lab=GND}
N 110 -650 110 -590 {
lab=DVDD}
N 170 -530 170 -510 {
lab=GND}
N 170 -650 170 -590 {
lab=VDD}
N 110 -510 170 -510 {
lab=GND}
N 230 -530 230 -510 {
lab=GND}
N 230 -650 230 -590 {
lab=DVSS}
N 290 -530 290 -510 {
lab=GND}
N 290 -650 290 -590 {
lab=VSS}
N 230 -510 290 -510 {
lab=GND}
N 170 -510 230 -510 {
lab=GND}
N 380 -440 380 -420 {
lab=GND}
N 380 -650 380 -590 {
lab=ASIG}
N 380 -530 380 -500 {
lab=#net1}
C {devices/code_shown.sym} 490 -490 0 0 {name=s1
only_toplevel=false
value="
.ac dec 100 1k 100G
.save all
.control
run
display
plot ASIG
** plot vdb(asig) vdb(pad)
.endc
"}
C {devices/code_shown.sym} 490 -660 0 0 {name=MODELS only_toplevel=true
format="tcleval( @value )"
value="
.include $::180MCU_MODELS/design.ngspice
.lib $::180MCU_MODELS/sm141064.ngspice typical
.lib $::180MCU_MODELS/sm141064.ngspice diode_typical
.lib $::180MCU_MODELS/sm141064.ngspice res_typical
.lib $::180MCU_MODELS/sm141064.ngspice mimcap_typical
.lib $::180MCU_MODELS/sm141064.ngspice moscap_typical
"}
C {devices/code_shown.sym} 70 -770 0 0 {name=DUT only_toplevel=true
format="tcleval( @value )"
value="
.include "/foss/designs/gLayout-mahowalders/blocks/composite/regulated_cascoded_cmirror/xschem
/gf180mcu_fd_io__asig_5p0_extracted.spice"
XDUT DVSS DVDD VSS VDD PAD ASIG gf180mcu_fd_io__asig_5p0_extracted
"}
C {devices/vsource.sym} 110 -560 0 0 {name=V1 value=3}
C {devices/gnd.sym} 110 -510 0 0 {name=l1 lab=GND}
C {devices/lab_wire.sym} 110 -630 0 0 {name=p1 sig_type=std_logic lab=DVDD}
C {devices/vsource.sym} 170 -560 0 0 {name=V2 value=3}
C {devices/lab_wire.sym} 170 -630 0 0 {name=p2 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 230 -560 0 0 {name=V3 value=0}
C {devices/lab_wire.sym} 230 -630 0 0 {name=p3 sig_type=std_logic lab=DVSS}
C {devices/vsource.sym} 290 -560 0 0 {name=V4 value=0}
C {devices/lab_wire.sym} 290 -630 0 0 {name=p4 sig_type=std_logic lab=VSS}
C {devices/vsource.sym} 380 -470 0 0 {name=V5 value="DC 3 AC 1"}
C {devices/lab_wire.sym} 380 -630 0 0 {name=p5 sig_type=std_logic lab=ASIG}
C {devices/gnd.sym} 380 -420 0 0 {name=l2 lab=GND}
C {devices/res.sym} 380 -560 0 0 {name=R1
value=1k
footprint=1206
device=resistor
m=1}

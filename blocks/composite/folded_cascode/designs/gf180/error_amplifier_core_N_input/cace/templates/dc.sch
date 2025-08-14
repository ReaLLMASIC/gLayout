v {xschem version=3.4.6 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 100 -160 100 -140 {
lab=GND}
N 180 -160 180 -140 {
lab=GND}
N 100 -140 100 -120 {
lab=GND}
N 180 -140 180 -120 {
lab=GND}
N 280 -160 280 -140 {
lab=GND}
N 280 -140 280 -120 {
lab=GND}
N 640 -370 660 -370 {lab=#net1}
N 380 -160 380 -140 {
lab=GND}
N 380 -140 380 -120 {
lab=GND}
N 510 -160 510 -140 {
lab=GND}
N 510 -140 510 -120 {
lab=GND}
N 590 -530 610 -530 {lab=Vout}
N 590 -580 590 -530 {lab=Vout}
N 590 -580 840 -580 {lab=Vout}
N 840 -580 840 -500 {lab=Vout}
N 810 -500 840 -500 {lab=Vout}
N 840 -500 870 -500 {lab=Vout}
N 580 -470 610 -470 {lab=Vref}
N 630 -160 630 -140 {
lab=GND}
N 630 -140 630 -120 {
lab=GND}
N 180 -230 180 -220 {lab=#net2}
N 180 -310 180 -290 {lab=VDD}
N 100 -250 100 -220 {lab=VSS}
N 280 -250 280 -220 {lab=Vref}
N 380 -250 380 -220 {lab=VbiasP2}
N 510 -250 510 -220 {lab=VbiasN2}
N 630 -250 630 -220 {lab=VbiasN1}
N 640 -350 660 -350 {lab=VbiasP2}
N 640 -330 660 -330 {lab=VbiasN2}
N 640 -310 660 -310 {lab=VbiasN1}
N 640 -390 660 -390 {lab=VSS}
N 640 -410 660 -410 {lab=VDD}
C {devices/code_shown.sym} 0 -860 0 0 {name=SETUP
simulator=ngspice
only_toplevel=false
value="
.lib CACE\{PDK_ROOT\}/CACE\{PDK\}/libs.tech/combined/sky130.lib.spice CACE\{corner\}

.include CACE\{DUT_path\}

.temp CACE\{temperature\}

.option SEED=CACE[CACE\{seed=12345\} + CACE\{iterations=0\}]

* Flag unsafe operating conditions (exceeds models' specified limits)
.option warn=1
"}
C {/foss/designs/chipathon_2025/designs/folded_cascode_core/xschem/folded_cascode_core.sym} 710 -500 0 0 {name=x1}
C {devices/vsource.sym} 100 -190 0 0 {name=V0 value=0 savecurrent=false}
C {devices/gnd.sym} 100 -120 0 0 {name=l4 lab=GND}
C {devices/vsource.sym} 180 -190 0 0 {name=V1 value=CACE\{vdd\} savecurrent=false}
C {devices/gnd.sym} 180 -120 0 0 {name=l8 lab=GND}
C {devices/vsource.sym} 280 -190 0 0 {name=V3 value=CACE\{vref\} savecurrent=false}
C {devices/gnd.sym} 280 -120 0 0 {name=l9 lab=GND}
C {noconn.sym} 640 -370 0 0 {name=l1}
C {devices/vsource.sym} 380 -190 0 0 {name=V2 value=CACE\{VbiasP2\} savecurrent=false}
C {devices/gnd.sym} 380 -120 0 0 {name=l2 lab=GND}
C {devices/vsource.sym} 510 -190 0 0 {name=V4 value=CACE\{VbiasN2\} savecurrent=false}
C {devices/gnd.sym} 510 -120 0 0 {name=l3 lab=GND}
C {lab_pin.sym} 580 -470 2 1 {name=p1 sig_type=std_logic lab=Vref}
C {lab_pin.sym} 280 -250 2 1 {name=p2 sig_type=std_logic lab=Vref}
C {lab_pin.sym} 180 -310 2 1 {name=p3 sig_type=std_logic lab=VDD}
C {lab_pin.sym} 380 -250 2 1 {name=p4 sig_type=std_logic lab=VbiasP2}
C {lab_pin.sym} 510 -250 2 1 {name=p5 sig_type=std_logic lab=VbiasN2}
C {lab_pin.sym} 100 -250 2 1 {name=p6 sig_type=std_logic lab=VSS}
C {lab_pin.sym} 640 -410 2 1 {name=p7 sig_type=std_logic lab=VDD}
C {lab_pin.sym} 640 -390 2 1 {name=p8 sig_type=std_logic lab=VSS}
C {devices/vsource.sym} 630 -190 0 0 {name=V5 value=CACE\{VbiasN1\} savecurrent=false}
C {devices/gnd.sym} 630 -120 0 0 {name=l5 lab=GND}
C {lab_pin.sym} 630 -250 2 1 {name=p9 sig_type=std_logic lab=VbiasN1}
C {lab_pin.sym} 870 -500 0 1 {name=p10 sig_type=std_logic lab=Vout}
C {ammeter.sym} 180 -260 2 0 {name=vdd_i savecurrent=true spice_ignore=0}
C {lab_pin.sym} 640 -350 2 1 {name=p11 sig_type=std_logic lab=VbiasP2}
C {lab_pin.sym} 640 -330 2 1 {name=p12 sig_type=std_logic lab=VbiasN2}
C {lab_pin.sym} 640 -310 2 1 {name=p13 sig_type=std_logic lab=VbiasN1}
C {code.sym} 230 -550 0 0 {name=OP only_toplevel=true value="
.control
save all

*DC simulation
op

let Vout = v(Vout)
let Ivdd = i(vdd_i)

print Vout Ivdd
echo $&Vout $&Ivdd> CACE\{simpath\}/CACE\{filename\}_CACE\{N\}.data
.endc
"}

v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 480 -70 480 -60 {lab=GND}
N 480 -160 480 -130 {lab=Vref}
N 160 -140 160 -130 {lab=GND}
N 160 -230 160 -200 {lab=VDD}
N 240 -140 240 -130 {lab=GND}
N 240 -230 240 -200 {lab=VSS}
N 870 -70 870 -10 {
lab=GND}
N 780 -180 870 -180 {
lab=Vout}
N 870 -180 870 -130 {
lab=Vout}
N 480 -210 580 -210 {
lab=Vn}
N 480 -280 480 -210 {
lab=Vn}
N 870 -280 870 -180 {
lab=Vout}
N 500 -160 600 -160 {
lab=Vref}
N 580 -210 600 -210 {lab=Vn}
N 480 -280 560 -280 {lab=Vn}
N 620 -280 710 -280 {lab=Vx}
N 770 -280 870 -280 {lab=Vout}
N 480 -160 500 -160 {lab=Vref}
C {devices/vsource.sym} 480 -100 0 0 {name=V1 value=CACE\{vref\}}
C {devices/gnd.sym} 480 -60 0 0 {name=l2 lab=GND}
C {devices/lab_wire.sym} 480 -160 0 0 {name=p1 sig_type=std_logic lab=Vref}
C {devices/noconn.sym} 710 -120 0 1 {name=l4}
C {devices/lab_wire.sym} 670 -60 0 0 {name=p7 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 670 -80 0 0 {name=p8 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 160 -170 0 0 {name=V8 value=CACE\{vdd\}}
C {devices/gnd.sym} 160 -130 0 0 {name=l5 lab=GND}
C {devices/lab_wire.sym} 160 -230 0 0 {name=p9 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 240 -170 0 0 {name=V5 value=0}
C {devices/gnd.sym} 240 -130 0 0 {name=l6 lab=GND}
C {devices/lab_wire.sym} 240 -230 0 0 {name=p10 sig_type=std_logic lab=VSS}
C {devices/capa.sym} 870 -100 0 0 {name=C1
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {devices/lab_wire.sym} 870 -180 0 0 {name=p12 sig_type=std_logic lab=Vout}
C {devices/gnd.sym} 870 -10 0 0 {name=l8 lab=GND}
C {devices/lab_wire.sym} 670 -100 0 0 {name=p4 sig_type=std_logic lab=Vref}
C {devices/vsource.sym} 740 -280 1 0 {name=Vsweep value=CACE\{Vsweep\}}
C {devices/vsource.sym} 590 -280 3 1 {name=V3 value=CACE\{vref\}}
C {error_amplifier_N_input.sym} 690 -180 0 0 {name=x1}
C {devices/code_shown.sym} -10 -600 0 0 {name=SETUP
simulator=ngspice
only_toplevel=false
value="
.lib CACE\{PDK_ROOT\}/CACE\{PDK\}/libs.tech/ngspice/sm141064.ngspice CACE\{corner\}

.include CACE\{PDK_ROOT\}/CACE\{PDK\}/libs.tech/ngspice/design.ngspice
.include CACE\{DUT_path\}

.temp CACE\{temperature\}

.option SEED=CACE[CACE\{seed=12345\} + CACE\{iterations=0\}]

* Flag unsafe operating conditions (exceeds models' specified limits)
.option warn=1
"}
C {code.sym} 770 -470 0 0 {name=OS only_toplevel=true value="


.control
save all
 
** OP simulation
op
** Output swing
dc Vsweep 0 1.8 0.01 

setplot dc1
let dvout = deriv(v(Vout))

meas dc limmin when dvout=0.98 rise=1
meas dc limmax when dvout=0.98 fall=1

let Output_swing = limmax - limmin

*print Output_swing
*plot dvout

print Output_swing
echo $&Output_swing > CACE\{simpath\}/CACE\{filename\}_CACE\{N\}.data


.endc
"}
C {devices/lab_wire.sym} 480 -280 0 0 {name=p2 sig_type=std_logic lab=Vn
}
C {devices/lab_wire.sym} 670 -280 0 0 {name=p3 sig_type=std_logic lab=Vx
}

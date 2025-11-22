v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
L 4 1035 -380 1455 -380 {}
L 4 1035 -330 1455 -330 {}
L 4 1165 -380 1165 -20 {}
L 4 1255 -380 1255 -20 {}
L 4 1345 -380 1345 -20 {}
L 4 1455 -380 1455 -20 {}
L 4 1035 -380 1035 -20 {}
L 4 1035 -20 1455 -20 {}
T {Expected values for inputs:} 1115 -430 0 0 0.4 0.4 {}
T {Input} 1075 -370 0 0 0.4 0.4 {}
T {Min} 1195 -370 0 0 0.4 0.4 {}
T {Typ} 1285 -370 0 0 0.4 0.4 {}
T {Max} 1385 -370 0 0 0.4 0.4 {}
T {VDD} 1075 -320 0 0 0.4 0.4 {}
T {1.8} 1285 -320 0 0 0.4 0.4 {}
T {VIN_CM} 1055 -270 0 0 0.4 0.4 {}
T {0.8} 1385 -270 0 0 0.4 0.4 {}
T {VbiasP1} 1055 -220 0 0 0.4 0.4 {}
T {VbiasP2} 1055 -170 0 0 0.4 0.4 {}
T {VbiasN1} 1055 -120 0 0 0.4 0.4 {}
T {VbiasN2} 1055 -70 0 0 0.4 0.4 {}
T {0.95} 1280 -220 0 0 0.4 0.4 {}
T {0.81} 1280 -120 0 0 0.4 0.4 {}
T {1.2} 1285 -70 0 0 0.4 0.4 {}
T {0.5} 1285 -170 0 0 0.4 0.4 {}
N 190 -20 190 -10 {lab=GND}
N 190 -110 190 -80 {lab=VbiasP2}
N 270 -20 270 -10 {lab=GND}
N 270 -110 270 -80 {lab=VbiasN2}
N 350 -20 350 -10 {lab=GND}
N 350 -110 350 -80 {lab=VbiasN1}
N 30 -20 30 -10 {lab=GND}
N 30 -110 30 -80 {lab=VDD}
N 110 -20 110 -10 {lab=GND}
N 110 -110 110 -80 {lab=VSS}
N 950 -60 950 0 {
lab=GND}
N 860 -170 950 -170 {
lab=Vout}
N 950 -170 950 -120 {
lab=Vout}
N 560 -200 660 -200 {
lab=Vn}
N 560 -270 560 -200 {
lab=Vn}
N 950 -270 950 -170 {
lab=Vout}
N 560 -10 560 0 {lab=GND}
N 560 -100 560 -70 {lab=Vin}
N 560 -140 560 -100 {
lab=Vin}
N 560 -140 660 -140 {
lab=Vin}
N 430 -110 430 -80 {lab=VbiasP1}
N 430 -20 430 -10 {lab=GND}
N 860 -400 910 -400 {lab=Vout}
N 820 -350 820 -320 {lab=GND}
N 860 -360 900 -360 {lab=GND}
N 900 -360 900 -330 {lab=GND}
N 820 -330 900 -330 {lab=GND}
N 820 -430 820 -410 {lab=Vz}
N 770 -430 820 -430 {lab=Vz}
N 910 -400 950 -400 {lab=Vout}
N 950 -400 950 -270 {lab=Vout}
N 560 -430 560 -270 {lab=Vn}
N 660 -40 710 -40 {lab=Vcom}
N 660 -430 690 -430 {lab=#net1}
N 750 -430 770 -430 {lab=Vz}
N 560 -430 600 -430 {lab=Vn}
C {devices/vsource.sym} 190 -50 0 0 {name=V1 value=\{VbiasP2\}}
C {devices/gnd.sym} 190 -10 0 0 {name=l2 lab=GND}
C {devices/launcher.sym} 110 -330 0 0 {name=h3
descr="Save & Netlist & sim" 
tclcommand="xschem save; xschem netlist; xschem simulate"}
C {devices/lab_wire.sym} 190 -110 0 0 {name=p1 sig_type=std_logic lab=VbiasP2}
C {devices/vsource.sym} 270 -50 0 0 {name=V2 value=\{VbiasN2\}}
C {devices/gnd.sym} 270 -10 0 0 {name=l1 lab=GND}
C {devices/lab_wire.sym} 270 -110 0 0 {name=p2 sig_type=std_logic lab=VbiasN2}
C {devices/vsource.sym} 350 -50 0 0 {name=V3 value=\{VbiasN1\}}
C {devices/gnd.sym} 350 -10 0 0 {name=l3 lab=GND}
C {devices/lab_wire.sym} 350 -110 0 0 {name=p3 sig_type=std_logic lab=VbiasN1}
C {devices/lab_wire.sym} 710 40 0 0 {name=p4 sig_type=std_logic lab=VbiasN1}
C {devices/lab_wire.sym} 710 20 0 0 {name=p5 sig_type=std_logic lab=VbiasN2}
C {devices/lab_wire.sym} 710 0 0 0 {name=p6 sig_type=std_logic lab=VbiasP2}
C {devices/lab_wire.sym} 710 -60 0 0 {name=p7 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 710 -80 0 0 {name=p8 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 30 -50 0 0 {name=V4 value=\{VDD\}}
C {devices/gnd.sym} 30 -10 0 0 {name=l5 lab=GND}
C {devices/lab_wire.sym} 30 -110 0 0 {name=p9 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 110 -50 0 0 {name=V5 value=\{VSS\}}
C {devices/gnd.sym} 110 -10 0 0 {name=l6 lab=GND}
C {devices/lab_wire.sym} 110 -110 0 0 {name=p10 sig_type=std_logic lab=VSS}
C {devices/capa.sym} 950 -90 0 0 {name=C1
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {devices/vsource.sym} 560 -40 0 0 {name=V6 value=\{Vin_CM\}}
C {devices/gnd.sym} 560 0 0 0 {name=l7 lab=GND}
C {devices/lab_wire.sym} 560 -140 0 0 {name=p11 sig_type=std_logic lab=Vin}
C {devices/lab_wire.sym} 950 -170 0 0 {name=p12 sig_type=std_logic lab=Vout}
C {devices/gnd.sym} 950 0 0 0 {name=l8 lab=GND}
C {gf180/error_amplifier_core_N_input/xschem/error_amplifier_core_N_input.sym} 760 -170 0 0 {name=x1}
C {launcher.sym} 110 -260 0 0 {name=h1
descr="Annotate OP"
tclcommand="set show_hidden_texts 1; xschem annotate_op"}
C {simulator_commands.sym} 100 -500 0 0 {name=COMMANDS
simulator=ngspice
only_toplevel=false 
value="

* --- Include PDK and Model Files ---
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

* --- Define Parameters for the Simulation ---
.param VDD = 1.8
.param VSS = 0
.param VbiasN1 = 0.81
.param VbiasN2 = 1.2
.param VbiasP1 = 0.95
.param VbiasP2 = 0.5
.param Vin_CM = 0.8
.param Vout_CM = 0.9
.param Vy = (Vout_CM - Vin_CM)
.param load_cap = 5*1e-12 

* --- Simulation Commands and Analysis ---
.control
save all

** OP & DC simulations
op
dc V9 0 1.8 0.001

** DC measurements 
setplot dc1
let dvout = deriv(v(Vout))

meas dc limmin when dvout=0.98 rise=1
meas dc limmax when dvout=0.98 fall=1

let Output_swing = limmax - limmin

print Output_swing
plot dvout


write error_amplifier_core_N_input_op.raw
.endc
"}
C {devices/vsource.sym} 430 -50 0 0 {name=Vsb1 value=\{VbiasP1\} savecurrent=false}
C {devices/gnd.sym} 430 -10 0 0 {name=l10 lab=GND}
C {devices/lab_wire.sym} 430 -110 0 0 {name=p13 sig_type=std_logic lab=VbiasP1
}
C {devices/lab_wire.sym} 710 -20 0 0 {name=p14 sig_type=std_logic lab=VbiasP1}
C {devices/vsource.sym} 630 -430 1 0 {name=V9 value=\{Vout_CM\}}
C {vcvs.sym} 820 -380 0 1 {name=E1 value=1}
C {devices/gnd.sym} 820 -320 0 0 {name=l11 lab=GND}
C {devices/lab_wire.sym} 820 -430 0 0 {name=p19 sig_type=std_logic lab=Vz}
C {devices/lab_wire.sym} 560 -300 0 0 {name=p15 sig_type=std_logic lab=Vn}
C {noconn.sym} 660 -40 2 1 {name=l9}
C {devices/lab_wire.sym} 690 -40 0 0 {name=p16 sig_type=std_logic lab=Vcom}
C {devices/vsource.sym} 720 -430 3 0 {name=V7 value=\{Vin_CM\}
}

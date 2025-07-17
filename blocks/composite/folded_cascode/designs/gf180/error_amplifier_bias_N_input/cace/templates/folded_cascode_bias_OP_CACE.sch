v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
P 4 1 400 -580 {}
N 430 -360 430 -320 {
lab=GND}
N 430 -460 430 -420 {
lab=VSS}
N 510 -360 510 -320 {
lab=GND}
N 510 -460 510 -420 {
lab=VDD}
N 590 -360 590 -320 {
lab=GND}
N 590 -460 590 -420 {
lab=Vref}
C {devices/vsource.sym} 430 -390 0 0 {name=V0 value=0 savecurrent=false}
C {devices/gnd.sym} 430 -320 0 0 {name=l3 lab=GND}
C {devices/vsource.sym} 510 -390 0 0 {name=V2 value=CACE\{VDD\} savecurrent=false}
C {devices/lab_wire.sym} 430 -460 0 0 {name=p12 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 510 -460 0 0 {name=p13 sig_type=std_logic lab=VDD}
C {devices/gnd.sym} 510 -320 0 0 {name=l4 lab=GND}
C {devices/vsource.sym} 590 -390 0 0 {name=V4 value=\{Vref\} savecurrent=false}
C {devices/lab_wire.sym} 590 -460 0 0 {name=p14 sig_type=std_logic lab=Vref}
C {devices/gnd.sym} 590 -320 0 0 {name=l5 lab=GND}
C {error_amplifier_bias_N_input.sym} 850 -430 0 0 {name=x1}
C {lab_pin.sym} 730 -450 0 0 {name=p8 sig_type=std_logic lab=Vref}
C {lab_pin.sym} 730 -430 0 0 {name=p1 sig_type=std_logic lab=VDD}
C {lab_pin.sym} 730 -410 0 0 {name=p2 sig_type=std_logic lab=VSS}
C {noconn.sym} 970 -450 2 0 {name=l1}
C {noconn.sym} 970 -430 2 0 {name=l2}
C {noconn.sym} 970 -410 2 0 {name=l6}
C {simulator_commands.sym} 300 -620 0 0 {name=OP only_toplevel="true" value="
.param Vref=1.2
.save

.control
save all
op

* Obtener voltajes en los nodos
let VbiasP2_voltage = v(net3)
let VbiasN2_voltage = v(net2)
let VbiasN1_voltage = v(net1)

* Imprimir voltajes en la consola
print VbiasP2_voltage VbiasN2_voltage VbiasN1_voltage

* Echo para guardar los voltajes en un archivo de datos
echo $&VbiasP2_voltage $&VbiasN2_voltage $&VbiasN1_voltage > CACE\{simpath\}/CACE\{filename\}_CACE\{N\}.data

.endc
"}
C {devices/code_shown.sym} 450 -700 0 0 {name=SETUP
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

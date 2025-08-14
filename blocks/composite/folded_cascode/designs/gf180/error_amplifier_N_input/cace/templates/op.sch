v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 390 -260 400 -260 {lab=Vout}
N 400 -130 400 -50 {
lab=VSS}
N 400 -260 400 -190 {
lab=Vout}
N 130 -240 160 -240 {lab=Vref}
N 130 -290 160 -290 {lab=Vn}
N 130 -340 130 -290 {lab=Vn}
N 400 -340 400 -260 {lab=Vout}
N -80 0 -80 40 {
lab=GND}
N 0 0 0 40 {
lab=GND}
N 100 0 100 40 {
lab=GND}
N 0 -70 0 -60 {lab=#net1}
N 0 -150 0 -130 {lab=VDD}
N -80 -90 -80 -60 {lab=VSS}
N 100 -90 100 -60 {lab=Vref}
N 340 -260 390 -260 {lab=Vout}
N 320 -470 370 -470 {lab=Vout}
N 280 -420 280 -390 {lab=GND}
N 320 -430 360 -430 {lab=GND}
N 360 -430 360 -400 {lab=GND}
N 280 -400 360 -400 {lab=GND}
N 280 -500 280 -480 {lab=Vz}
N 230 -500 280 -500 {lab=Vz}
N 400 -470 400 -340 {lab=Vout}
N 370 -470 400 -470 {lab=Vout}
N 130 -500 170 -500 {lab=Vn}
N 130 -500 130 -340 {lab=Vn}
C {devices/code_shown.sym} 490 -200 0 0 {name=SETUP
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
C {lab_pin.sym} 230 -180 2 1 {name=p7 sig_type=std_logic lab=Vref}
C {lab_pin.sym} 230 -160 2 1 {name=p8 sig_type=std_logic lab=VDD}
C {lab_pin.sym} 230 -140 2 1 {name=p9 sig_type=std_logic lab=VSS}
C {lab_pin.sym} 130 -240 2 1 {name=p10 sig_type=std_logic lab=Vref}
C {error_amplifier_N_input.sym} 250 -260 0 0 {name=x1}
C {capa.sym} 400 -160 0 0 {name=C1
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {lab_pin.sym} 400 -50 2 1 {name=p1 sig_type=std_logic lab=VSS}
C {noconn.sym} 270 -200 2 0 {name=l1}
C {lab_pin.sym} 400 -260 0 1 {name=p2 sig_type=std_logic lab=Vout}
C {devices/vsource.sym} -80 -30 0 0 {name=V0 value=0 savecurrent=false}
C {devices/gnd.sym} -80 40 0 0 {name=l4 lab=GND}
C {devices/vsource.sym} 0 -30 0 0 {name=V1 value=CACE\{vdd\} savecurrent=false}
C {devices/gnd.sym} 0 40 0 0 {name=l8 lab=GND}
C {devices/vsource.sym} 100 -30 0 0 {name=V3 value=CACE\{vref\} savecurrent=false}
C {devices/gnd.sym} 100 40 0 0 {name=l9 lab=GND}
C {lab_pin.sym} 100 -90 2 1 {name=p3 sig_type=std_logic lab=Vref}
C {lab_pin.sym} 0 -150 2 1 {name=p4 sig_type=std_logic lab=VDD}
C {lab_pin.sym} -80 -90 2 1 {name=p6 sig_type=std_logic lab=VSS}
C {ammeter.sym} 0 -100 2 0 {name=vdd_i savecurrent=true spice_ignore=0}
C {code.sym} -70 -340 0 0 {name=OP only_toplevel=true value="
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
C {devices/vsource.sym} 200 -500 1 0 {name=V9 value=CACE\{Vy\}}
C {vcvs.sym} 280 -450 0 1 {name=E1 value=1}
C {devices/gnd.sym} 280 -390 0 0 {name=l11 lab=GND}
C {devices/lab_wire.sym} 280 -500 0 0 {name=p19 sig_type=std_logic lab=Vz}
C {lab_pin.sym} 130 -330 2 1 {name=p5 sig_type=std_logic lab=Vn}

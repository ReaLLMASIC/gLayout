v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
L 4 1050 -630 1470 -630 {}
L 4 1050 -580 1470 -580 {}
L 4 1180 -630 1180 -270 {}
L 4 1270 -630 1270 -270 {}
L 4 1360 -630 1360 -270 {}
L 4 1470 -630 1470 -270 {}
L 4 1050 -630 1050 -270 {}
L 4 1050 -270 1470 -270 {}
T {Expected values for inputs:} 1130 -680 0 0 0.4 0.4 {}
T {Input} 1090 -620 0 0 0.4 0.4 {}
T {Min} 1210 -620 0 0 0.4 0.4 {}
T {Typ} 1300 -620 0 0 0.4 0.4 {}
T {Max} 1400 -620 0 0 0.4 0.4 {}
T {VDD} 1090 -570 0 0 0.4 0.4 {}
T {1.8} 1300 -570 0 0 0.4 0.4 {}
T {VIN_CM} 1070 -520 0 0 0.4 0.4 {}
T {0.8} 1400 -520 0 0 0.4 0.4 {}
T {VbiasP1} 1070 -470 0 0 0.4 0.4 {}
T {VbiasP2} 1070 -420 0 0 0.4 0.4 {}
T {VbiasN1} 1070 -370 0 0 0.4 0.4 {}
T {VbiasN2} 1070 -320 0 0 0.4 0.4 {}
T {0.95} 1295 -470 0 0 0.4 0.4 {}
T {0.81} 1300 -370 0 0 0.4 0.4 {}
T {1.28} 1295 -320 0 0 0.4 0.4 {}
T {0.4} 1295 -420 0 0 0.4 0.4 {}
N 690 -640 750 -640 {lab=Vout}
N 410 -350 490 -350 {
lab=Vx}
N 410 -400 410 -350 {
lab=Vx}
N 270 -350 310 -350 {
lab=Vin}
N 370 -350 410 -350 {
lab=Vx}
N 230 -350 270 -350 {
lab=Vin}
N 820 -640 820 -430 {
lab=Vout}
N 900 -510 900 -430 {
lab=GND}
N 900 -640 900 -580 {
lab=Vout}
N 750 -640 900 -640 {
lab=Vout}
N 410 -500 410 -460 {
lab=Vn}
N 900 -580 900 -570 {
lab=Vout}
N 270 -430 270 -350 {lab=Vin}
N 820 -430 820 -350 {lab=Vout}
N 270 -610 490 -610 {lab=Vin}
N 270 -610 270 -430 {lab=Vin}
N 410 -670 490 -670 {lab=Vn}
N 410 -590 410 -500 {lab=Vn}
N 390 -590 410 -590 {lab=Vn}
N 390 -630 390 -590 {lab=Vn}
N 390 -630 410 -630 {lab=Vn}
N 410 -670 410 -630 {lab=Vn}
N 460 -30 460 -20 {lab=GND}
N 460 -120 460 -90 {lab=VbiasP2}
N 580 -30 580 -20 {lab=GND}
N 580 -120 580 -90 {lab=VbiasN2}
N 710 -30 710 -20 {lab=GND}
N 710 -120 710 -90 {lab=VbiasN1}
N 240 -30 240 -20 {lab=GND}
N 240 -120 240 -90 {lab=VDD}
N 350 -30 350 -20 {lab=GND}
N 350 -120 350 -90 {lab=VSS}
N 840 -120 840 -90 {lab=VbiasP1}
N 840 -30 840 -20 {lab=GND}
N 230 -260 230 -250 {lab=GND}
N 230 -350 230 -320 {lab=Vin}
N 900 -430 900 -410 {lab=GND}
N 490 -510 540 -510 {lab=Vcom}
N 490 -350 510 -350 {lab=Vx}
N 770 -320 820 -320 {lab=Vout}
N 820 -350 820 -320 {lab=Vout}
N 730 -270 730 -240 {lab=GND}
N 770 -280 810 -280 {lab=GND}
N 810 -280 810 -250 {lab=GND}
N 730 -250 810 -250 {lab=GND}
N 730 -350 730 -330 {lab=Vz}
N 680 -350 730 -350 {lab=Vz}
N 570 -350 620 -350 {lab=Vy}
N 1220 -50 1220 -20 {lab=GND}
N 1260 -60 1300 -60 {lab=GND}
N 1300 -60 1300 -30 {lab=GND}
N 1220 -30 1300 -30 {lab=GND}
N 1260 -100 1400 -100 {lab=VbiasP1}
N 1220 -170 1220 -110 {lab=Vaa}
N 1220 -180 1220 -170 {lab=Vaa}
N 1090 -180 1220 -180 {lab=Vaa}
N 1070 -180 1070 -130 {lab=Vaa}
N 1070 -180 1090 -180 {lab=Vaa}
N 1070 -70 1070 -40 {lab=GND}
N 1070 -40 1220 -40 {lab=GND}
C {devices/launcher.sym} 70 -430 0 0 {name=h15
descr="Annotate OP" 
tclcommand="set show_hidden_texts 1; xschem annotate_op"
}
C {devices/launcher.sym} 70 -500 0 0 {name=h3
descr="Netlist & sim" 
tclcommand="xschem netlist; xschem simulate"}
C {vsource.sym} 410 -430 0 0 {name=V5 value="AC 1" savecurrent=false}
C {capa.sym} 340 -350 1 0 {name=C2
m=1
value=10G
footprint=1206
device="ceramic capacitor"}
C {ind.sym} 540 -350 1 0 {name=L4
m=1
value=10G
footprint=1206
device=inductor}
C {lab_pin.sym} 540 -550 2 1 {name=p8 sig_type=std_logic lab=VDD}
C {lab_pin.sym} 540 -530 2 1 {name=p9 sig_type=std_logic lab=VSS}
C {capa.sym} 900 -540 0 0 {name=C1
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {noconn.sym} 490 -510 2 1 {name=l1}
C {lab_pin.sym} 900 -640 0 1 {name=p2 sig_type=std_logic lab=Vout}
C {lab_pin.sym} 540 -490 2 1 {name=p5 sig_type=std_logic lab=VbiasP1}
C {lab_pin.sym} 540 -470 2 1 {name=p6 sig_type=std_logic lab=VbiasP2}
C {lab_pin.sym} 540 -450 2 1 {name=p7 sig_type=std_logic lab=VbiasN2}
C {lab_pin.sym} 540 -430 2 1 {name=p11 sig_type=std_logic lab=VbiasN1}
C {devices/vsource.sym} 460 -60 0 0 {name=V1 value=CACE\{VbiasP2\}}
C {devices/gnd.sym} 460 -20 0 0 {name=l2 lab=GND}
C {devices/lab_wire.sym} 460 -120 0 0 {name=p3 sig_type=std_logic lab=VbiasP2}
C {devices/vsource.sym} 580 -60 0 0 {name=V2 value=CACE\{VbiasN2\}}
C {devices/gnd.sym} 580 -20 0 0 {name=l3 lab=GND}
C {devices/lab_wire.sym} 580 -120 0 0 {name=p4 sig_type=std_logic lab=VbiasN2}
C {devices/vsource.sym} 710 -60 0 0 {name=V3 value=CACE\{VbiasN1\}}
C {devices/gnd.sym} 710 -20 0 0 {name=l5 lab=GND}
C {devices/lab_wire.sym} 710 -120 0 0 {name=p12 sig_type=std_logic lab=VbiasN1}
C {devices/vsource.sym} 240 -60 0 0 {name=V4 value=CACE\{VDD\}}
C {devices/gnd.sym} 240 -20 0 0 {name=l6 lab=GND}
C {devices/lab_wire.sym} 240 -120 0 0 {name=p13 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 350 -60 0 0 {name=V6 value=0}
C {devices/gnd.sym} 350 -20 0 0 {name=l7 lab=GND}
C {devices/lab_wire.sym} 350 -120 0 0 {name=p14 sig_type=std_logic lab=VSS}
C {devices/vsource.sym} 840 -60 0 0 {name=V8 value=CACE\{VbiasP1\} savecurrent=false}
C {devices/gnd.sym} 840 -20 0 0 {name=l10 lab=GND}
C {devices/lab_wire.sym} 840 -120 0 0 {name=p15 sig_type=std_logic lab=VbiasP1
}
C {devices/vsource.sym} 230 -290 0 0 {name=V7 value=CACE\{Vin_CM\}}
C {devices/gnd.sym} 230 -250 0 0 {name=l8 lab=GND}
C {devices/lab_wire.sym} 230 -350 0 0 {name=p10 sig_type=std_logic lab=Vin}
C {devices/gnd.sym} 900 -410 0 0 {name=l9 lab=GND}
C {devices/lab_wire.sym} 450 -350 0 0 {name=p1 sig_type=std_logic lab=Vx}
C {devices/lab_wire.sym} 520 -510 0 0 {name=p16 sig_type=std_logic lab=Vcom}
C {devices/lab_wire.sym} 430 -670 0 0 {name=p17 sig_type=std_logic lab=Vn}
C {devices/vsource.sym} 650 -350 1 0 {name=V9 value=CACE\{Vy\}}
C {vcvs.sym} 730 -300 0 1 {name=E1 value=1}
C {devices/gnd.sym} 730 -240 0 0 {name=l11 lab=GND}
C {devices/lab_wire.sym} 590 -350 0 0 {name=p18 sig_type=std_logic lab=Vy}
C {devices/lab_wire.sym} 730 -350 0 0 {name=p19 sig_type=std_logic lab=Vz}
C {vcvs.sym} 1220 -80 0 1 {name=E2 value=1}
C {devices/gnd.sym} 1220 -20 0 0 {name=l12 lab=GND}
C {devices/lab_wire.sym} 1400 -100 0 0 {name=p20 sig_type=std_logic lab=VbiasP1
}
C {res.sym} 1070 -100 0 0 {name=R1
value=1k
footprint=1206
device=resistor
m=1}
C {devices/lab_wire.sym} 1140 -180 0 0 {name=p21 sig_type=std_logic lab=Vaa}
C {devices/code_shown.sym} 50 -970 0 0 {name=SETUP
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
C {code.sym} 970 -880 0 0 {name=OP only_toplevel=true value="

  
    *remzerovec
    *write error_amplifier_core_N_input_ac.raw
    *set appendwrite 
 

.control
save all

*DC simulation
op
* run ac simulation
ac dec 20 1 100e7


* measure parameters
let vout_mag = db(abs(v(Vout)))
*let vout_phase = cph(v(Vout)) * (180/pi)
let vout_phase = cph(v(Vout)) * (57.295779513)
let gm = (-1)*db(abs(v(Vout)))

meas ac A0 find vout_mag at=1
meas ac UGB when vout_mag=0 fall=1
meas ac PM find vout_phase when vout_mag=0
meas ac GM find gm when vout_phase=0

let A0_p1 = A0 - 3
meas ac BW when vout_mag=A0_p1 

print A0 UGB PM GM BW
echo $&A0 $&UGB $&PM $&GM $&BW > CACE\{simpath\}/CACE\{filename\}_CACE\{N\}.data
.endc
"}
C {error_amplifier_core_N_input.sym} 590 -640 0 0 {name=x1}

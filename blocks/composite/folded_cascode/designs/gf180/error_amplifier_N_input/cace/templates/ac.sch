v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 720 -340 780 -340 {lab=Vout}
N 440 -50 520 -50 {
lab=Vx}
N 440 -100 440 -50 {
lab=Vx}
N 300 -50 340 -50 {
lab=#net1}
N 400 -50 440 -50 {
lab=Vx}
N 260 -50 300 -50 {
lab=#net1}
N 850 -340 850 -130 {
lab=Vout}
N 930 -210 930 -130 {
lab=GND}
N 930 -340 930 -280 {
lab=Vout}
N 780 -340 930 -340 {
lab=Vout}
N 440 -200 440 -160 {
lab=Vn}
N 930 -280 930 -270 {
lab=Vout}
N 300 -130 300 -50 {lab=#net1}
N 850 -130 850 -50 {lab=Vout}
N 300 -310 300 -130 {lab=#net1}
N 440 -370 520 -370 {lab=Vn}
N 440 -290 440 -200 {lab=Vn}
N 420 -290 440 -290 {lab=Vn}
N 420 -330 420 -290 {lab=Vn}
N 420 -330 440 -330 {lab=Vn}
N 440 -370 440 -330 {lab=Vn}
N 930 -130 930 -110 {lab=GND}
N 520 -50 540 -50 {lab=Vx}
N 800 -20 850 -20 {lab=Vout}
N 850 -50 850 -20 {lab=Vout}
N 760 30 760 60 {lab=GND}
N 800 20 840 20 {lab=GND}
N 840 20 840 50 {lab=GND}
N 760 50 840 50 {lab=GND}
N 760 -50 760 -30 {lab=Vz}
N 710 -50 760 -50 {lab=Vz}
N 600 -50 650 -50 {lab=Vy}
N 520 -370 550 -370 {lab=Vn}
N 300 -320 550 -320 {lab=#net1}
N 300 -320 300 -310 {lab=#net1}
N -80 -20 -80 20 {
lab=GND}
N 0 -20 0 20 {
lab=GND}
N 100 -20 100 20 {
lab=GND}
N 0 -90 0 -80 {lab=#net2}
N 0 -170 0 -150 {lab=VDD}
N -80 -110 -80 -80 {lab=VSS}
N 100 -110 100 -80 {lab=Vref}
N 660 -280 680 -280 {lab=#net3}
C {devices/launcher.sym} -20 -270 0 0 {name=h15
descr="Annotate OP" 
tclcommand="set show_hidden_texts 1; xschem annotate_op"
}
C {devices/launcher.sym} -20 -340 0 0 {name=h3
descr="Netlist & sim" 
tclcommand="xschem netlist; xschem simulate"}
C {vsource.sym} 440 -130 0 0 {name=V5 value="AC 1" savecurrent=false}
C {capa.sym} 370 -50 1 0 {name=C2
m=1
value=10G
footprint=1206
device="ceramic capacitor"}
C {ind.sym} 570 -50 1 0 {name=L4
m=1
value=10G
footprint=1206
device=inductor}
C {capa.sym} 930 -240 0 0 {name=C1
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {lab_pin.sym} 930 -340 0 1 {name=p2 sig_type=std_logic lab=Vout}
C {devices/gnd.sym} 930 -110 0 0 {name=l9 lab=GND}
C {devices/lab_wire.sym} 480 -50 0 0 {name=p1 sig_type=std_logic lab=Vx}
C {devices/lab_wire.sym} 460 -370 0 0 {name=p17 sig_type=std_logic lab=Vn}
C {devices/vsource.sym} 680 -50 1 0 {name=V9 value=CACE\{Vy\}}
C {vcvs.sym} 760 0 0 1 {name=E1 value=1}
C {devices/gnd.sym} 760 60 0 0 {name=l11 lab=GND}
C {devices/lab_wire.sym} 620 -50 0 0 {name=p18 sig_type=std_logic lab=Vy}
C {devices/lab_wire.sym} 760 -50 0 0 {name=p19 sig_type=std_logic lab=Vz}
C {devices/code_shown.sym} 80 -670 0 0 {name=SETUP
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
C {code.sym} 900 -610 0 0 {name=AC only_toplevel=true value="

  
    *remzerovec
    *write error_amplifier_core_P_input_ac.raw
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
C {error_amplifier_N_input.sym} 640 -340 0 0 {name=x1}
C {devices/vsource.sym} -80 -50 0 0 {name=V0 value=0 savecurrent=false}
C {devices/gnd.sym} -80 20 0 0 {name=l13 lab=GND}
C {devices/vsource.sym} 0 -50 0 0 {name=V10 value=CACE\{vdd\} savecurrent=false}
C {devices/gnd.sym} 0 20 0 0 {name=l14 lab=GND}
C {devices/vsource.sym} 100 -50 0 0 {name=V11 value=CACE\{vref\} savecurrent=false}
C {devices/gnd.sym} 100 20 0 0 {name=l15 lab=GND}
C {lab_pin.sym} 100 -110 2 1 {name=p22 sig_type=std_logic lab=Vref}
C {lab_pin.sym} 0 -170 2 1 {name=p23 sig_type=std_logic lab=VDD}
C {lab_pin.sym} -80 -110 2 1 {name=p24 sig_type=std_logic lab=VSS}
C {ammeter.sym} 0 -120 2 0 {name=vdd_i savecurrent=true spice_ignore=0}
C {lab_pin.sym} 620 -260 2 1 {name=p3 sig_type=std_logic lab=Vref}
C {lab_pin.sym} 620 -240 2 1 {name=p4 sig_type=std_logic lab=VDD}
C {lab_pin.sym} 620 -220 2 1 {name=p12 sig_type=std_logic lab=VSS}
C {noconn.sym} 680 -280 2 0 {name=l1}
C {lab_pin.sym} 260 -50 2 1 {name=p5 sig_type=std_logic lab=Vref}

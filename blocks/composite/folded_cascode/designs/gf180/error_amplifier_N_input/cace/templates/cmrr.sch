v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 960 -240 960 -180 {
lab=GND}
N 870 -350 960 -350 {
lab=Vout}
N 960 -350 960 -300 {
lab=Vout}
N 570 -380 670 -380 {
lab=V-}
N 80 -110 80 -100 {lab=GND}
N 80 -200 80 -170 {lab=VDD}
N 190 -110 190 -100 {lab=GND}
N 190 -200 190 -170 {lab=VSS}
N 910 -350 910 -90 {lab=Vout}
N 800 -90 910 -90 {lab=Vout}
N 570 -320 570 -90 {lab=V-}
N 270 -340 270 -300 {lab=V+}
N 570 -90 740 -90 {lab=V-}
N 570 -380 570 -320 {lab=V-}
N 620 -320 670 -320 {lab=V+}
N 670 -380 690 -380 {lab=V-}
N 670 -330 670 -320 {lab=V+}
N 670 -330 690 -330 {lab=V+}
N 270 -110 270 -100 {lab=GND}
N 270 -200 270 -170 {lab=Vref}
N 270 -240 270 -200 {lab=Vref}
C {vsource.sym} 270 -270 0 0 {name=V5 value="AC 1" savecurrent=false}
C {capa.sym} 620 -350 0 0 {name=C3
m=1
value=10G
footprint=1206
device="ceramic capacitor"}
C {ind.sym} 770 -90 1 0 {name=L2
m=1
value=10G
footprint=1206
device=inductor}
C {devices/noconn.sym} 800 -290 0 1 {name=l3}
C {devices/lab_wire.sym} 760 -230 0 0 {name=p12 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 760 -250 0 0 {name=p13 sig_type=std_logic lab=VDD}
C {devices/capa.sym} 960 -270 0 0 {name=C4
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {devices/lab_wire.sym} 960 -350 0 0 {name=p15 sig_type=std_logic lab=Vout}
C {devices/gnd.sym} 960 -180 0 0 {name=l8 lab=GND}
C {devices/vsource.sym} 80 -140 0 0 {name=V8 value=CACE\{vdd\}}
C {devices/gnd.sym} 80 -100 0 0 {name=l12 lab=GND}
C {devices/lab_wire.sym} 80 -200 0 0 {name=p19 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 190 -140 0 0 {name=V9 value=0}
C {devices/gnd.sym} 190 -100 0 0 {name=l13 lab=GND}
C {devices/lab_wire.sym} 190 -200 0 0 {name=p20 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 570 -380 0 0 {name=p3 sig_type=std_logic lab=V-}
C {devices/lab_wire.sym} 270 -340 0 0 {name=p4 sig_type=std_logic lab=V+}
C {devices/launcher.sym} 120 -480 0 0 {name=h1
descr="Save & Netlist & sim" 
tclcommand="xschem save; xschem netlist; xschem simulate"}
C {launcher.sym} 120 -410 0 0 {name=h2
descr="Annotate OP"
tclcommand="set show_hidden_texts 1; xschem annotate_op"}
C {devices/lab_wire.sym} 620 -320 2 0 {name=p21 sig_type=std_logic lab=V+}
C {error_amplifier_N_input.sym} 780 -350 0 0 {name=x1}
C {devices/lab_wire.sym} 760 -270 0 0 {name=p1 sig_type=std_logic lab=Vref}
C {devices/vsource.sym} 270 -140 0 0 {name=V1 value=CACE\{vref\}}
C {devices/gnd.sym} 270 -100 0 0 {name=l1 lab=GND
value=\{Vref\}}
C {devices/lab_wire.sym} 270 -200 0 0 {name=p2 sig_type=std_logic lab=Vref
value=\{Vref\}}
C {devices/code_shown.sym} 110 -780 0 0 {name=SETUP
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
C {code.sym} 820 -530 0 0 {name=CMRR only_toplevel=true value="


.control
save all

** OP simulation
op

** run ac simulation
ac dec 20 1 100e6

setplot ac1

* measure parameters
let vout_mag = db(abs(v(Vout)))
let vout_phase = cph(v(Vout)) * 180/pi

meas ac Acm find vout_mag at=1

*plot vout_mag vout_phase

print Acm
echo $&Acm > CACE\{simpath\}/CACE\{filename\}_CACE\{N\}.data


.endc
"}

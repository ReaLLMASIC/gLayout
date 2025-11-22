v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
P 4 1 360 -260 {}
P 4 1 360 -280 {}
P 4 1 360 -300 {}
N 130 -60 130 -20 {
lab=GND}
N 130 -160 130 -120 {
lab=VSS}
N 210 -60 210 -20 {
lab=GND}
N 210 -160 210 -120 {
lab=VDD}
N 290 -60 290 -20 {
lab=GND}
N 290 -160 290 -120 {
lab=Vref}
N 320 -280 350 -280 {lab=VbiasP2}
N 320 -260 350 -260 {lab=VbiasN2}
N 320 -240 350 -240 {lab=VbiasN1}
N 320 -300 350 -300 {lab=VbiasP1}
C {devices/vsource.sym} 130 -90 0 0 {name=V0 value=0 savecurrent=false}
C {devices/gnd.sym} 130 -20 0 0 {name=l3 lab=GND}
C {devices/vsource.sym} 210 -90 0 0 {name=V2 value=1.8 savecurrent=false}
C {devices/lab_wire.sym} 130 -160 0 0 {name=p12 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 210 -160 0 0 {name=p13 sig_type=std_logic lab=VDD}
C {devices/gnd.sym} 210 -20 0 0 {name=l4 lab=GND}
C {devices/vsource.sym} 290 -90 0 0 {name=V4 value=1.2 savecurrent=false}
C {devices/lab_wire.sym} 290 -160 0 0 {name=p14 sig_type=std_logic lab=Vref}
C {devices/gnd.sym} 290 -20 0 0 {name=l5 lab=GND}
C {devices/lab_pin.sym} 80 -290 0 0 {name=p1 sig_type=std_logic lab=Vref}
C {devices/lab_pin.sym} 80 -270 0 0 {name=p2 sig_type=std_logic lab=VDD}
C {devices/lab_pin.sym} 80 -250 0 0 {name=p3 sig_type=std_logic lab=VSS}
C {devices/code_shown.sym} 20 -510 0 0 {name=MODELS only_toplevel=true
format="tcleval( @value )"
value="
.include /foss/pdks/gf180mcuC/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuC/libs.tech/ngspice/sm141064.ngspice typical
"}
C {devices/launcher.sym} 140 -380 0 0 {name=h1
descr="Save & Netlist & sim" 
tclcommand="xschem save; xschem netlist; xschem simulate"}
C {devices/code_shown.sym} 440 -320 0 0 {name=s1 only_toplevel=false value="
.control
save all
op

save V(VbiasP2)
print V(VbiasP2)

save V(VbiasN2)
print V(VbiasN2)

save V(VbiasN1)
print V(VbiasN1)

.endc
"
}
C {devices/noconn.sym} 350 -280 0 1 {name=l1}
C {devices/noconn.sym} 350 -260 0 1 {name=l2}
C {devices/noconn.sym} 350 -240 0 1 {name=l6}
C {devices/lab_pin.sym} 340 -280 0 0 {name=p4 sig_type=std_logic lab=VbiasP2}
C {devices/lab_pin.sym} 340 -260 0 0 {name=p5 sig_type=std_logic lab=VbiasN2}
C {devices/lab_pin.sym} 340 -240 0 0 {name=p6 sig_type=std_logic lab=VbiasN1}
C {gf180/error_amplifier_bias_N_input/xschem/error_amplifier_bias_N_input.sym} 200 -270 0 0 {name=x1}
C {devices/noconn.sym} 350 -300 0 1 {name=l7}
C {devices/lab_pin.sym} 340 -300 0 0 {name=p7 sig_type=std_logic lab=VbiasP1}

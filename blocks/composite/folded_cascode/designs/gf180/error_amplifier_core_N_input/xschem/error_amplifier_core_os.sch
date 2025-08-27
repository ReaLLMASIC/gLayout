v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 240 -60 240 -50 {lab=GND}
N 240 -150 240 -120 {lab=VbiasP2}
N 320 -60 320 -50 {lab=GND}
N 320 -150 320 -120 {lab=VbiasN2}
N 400 -60 400 -50 {lab=GND}
N 400 -150 400 -120 {lab=VbiasN1}
N 80 -60 80 -50 {lab=GND}
N 80 -150 80 -120 {lab=VDD}
N 160 -60 160 -50 {lab=GND}
N 160 -150 160 -120 {lab=VSS}
N 960 -110 960 -50 {
lab=GND}
N 870 -220 960 -220 {
lab=Vout}
N 960 -220 960 -170 {
lab=Vout}
N 570 -250 670 -250 {
lab=Vout}
N 570 -320 570 -250 {
lab=Vout}
N 570 -320 960 -320 {
lab=Vout}
N 960 -320 960 -220 {
lab=Vout}
N 570 -60 570 -50 {lab=GND}
N 570 -150 570 -120 {lab=Vin}
N 570 -190 570 -150 {
lab=Vin}
N 570 -190 670 -190 {
lab=Vin}
C {devices/vsource.sym} 240 -90 0 0 {name=V1 value=\{VbiasP2\}}
C {devices/gnd.sym} 240 -50 0 0 {name=l2 lab=GND}
C {devices/launcher.sym} 120 -370 0 0 {name=h3
descr="Save & Netlist & sim" 
tclcommand="xschem save; xschem netlist; xschem simulate"}
C {devices/lab_wire.sym} 240 -150 0 0 {name=p1 sig_type=std_logic lab=VbiasP2}
C {devices/vsource.sym} 320 -90 0 0 {name=V2 value=\{VbiasN2\}}
C {devices/gnd.sym} 320 -50 0 0 {name=l1 lab=GND}
C {devices/lab_wire.sym} 320 -150 0 0 {name=p2 sig_type=std_logic lab=VbiasN2}
C {devices/vsource.sym} 400 -90 0 0 {name=V3 value=\{VbiasN1\}}
C {devices/gnd.sym} 400 -50 0 0 {name=l3 lab=GND}
C {devices/lab_wire.sym} 400 -150 0 0 {name=p3 sig_type=std_logic lab=VbiasN1}
C {devices/lab_wire.sym} 720 -30 0 0 {name=p4 sig_type=std_logic lab=VbiasN1}
C {devices/lab_wire.sym} 720 -50 0 0 {name=p5 sig_type=std_logic lab=VbiasN2}
C {devices/lab_wire.sym} 720 -70 0 0 {name=p6 sig_type=std_logic lab=VbiasP2}
C {devices/noconn.sym} 720 -90 0 0 {name=l4}
C {devices/lab_wire.sym} 720 -110 0 0 {name=p7 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 720 -130 0 0 {name=p8 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 80 -90 0 0 {name=V4 value=\{VDD\}}
C {devices/gnd.sym} 80 -50 0 0 {name=l5 lab=GND}
C {devices/lab_wire.sym} 80 -150 0 0 {name=p9 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 160 -90 0 0 {name=V5 value=\{VSS\}}
C {devices/gnd.sym} 160 -50 0 0 {name=l6 lab=GND}
C {devices/lab_wire.sym} 160 -150 0 0 {name=p10 sig_type=std_logic lab=VSS}
C {devices/capa.sym} 960 -140 0 0 {name=C1
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {devices/vsource.sym} 570 -90 0 0 {name=Vin value=\{Vin\}}
C {devices/gnd.sym} 570 -50 0 0 {name=l7 lab=GND}
C {devices/lab_wire.sym} 570 -150 0 0 {name=p11 sig_type=std_logic lab=Vin}
C {devices/lab_wire.sym} 960 -220 0 0 {name=p12 sig_type=std_logic lab=Vout}
C {devices/gnd.sym} 960 -50 0 0 {name=l8 lab=GND}
C {devices/code_shown.sym} 40 -500 0 0 {name=MODELS only_toplevel=true
format="tcleval( @value )"
value="
.include $::180MCU_MODELS/design.ngspice
.lib $::180MCU_MODELS/sm141064.ngspice typical
"}
C {launcher.sym} 120 -300 0 0 {name=h1
descr="Annotate OP"
tclcommand="set show_hidden_texts 1; xschem annotate_op"}
C {simulator_commands.sym} 820 -480 0 0 {name=COMMANDS
simulator=ngspice
only_toplevel=false 
value="
.control
save all

** OP simulation
op
** Output swing
dc Vin 0 1.8 0.01

** All OP parameters
setplot op1
let #####_M1_nmos_input_##### = 0 
let id_M1 = @m.x1.xm1.m0[id]
let gm_M1 = @m.x1.xm1.m0[gm]
let ro_M1 = 1/@m.x1.xm1.m0[gds]
let Vgs_M1 = @m.x1.xm1.m0[vgs]
let Vds_M1 = @m.x1.xm1.m0[vds]
let Vsb_M1 = -@m.x1.xm1.m0[vbs]
let Vdsat_M1 = @m.x1.xm1.m0[vdsat]
let Vth_M1 = @m.x1.xm1.m0[vth]
let ao_M1 = gm_M1*ro_M1
let gmid_M1 = gm_M1/id_M1
let fT_M1 = gm_M1/(6.283185*@m.x1.xm1.m0[cgg])
print #####_M1_nmos_input_##### id_M1 gm_M1 ro_M1 Vgs_M1 Vds_M1 Vsb_M1 Vdsat_M1 Vth_M1 ao_M1 gmid_M1 fT_M1

let #####_M2_nmos_input_##### = 0 
let id_M2 = @m.x1.xm2.m0[id]
let gm_M2 = @m.x1.xm2.m0[gm]
let ro_M2 = 1/@m.x1.xm2.m0[gds]
let Vgs_M2 = @m.x1.xm2.m0[vgs]
let Vds_M2 = @m.x1.xm2.m0[vds]
let Vsb_M2 = -@m.x1.xm2.m0[vbs]
let Vdsat_M2 = @m.x1.xm2.m0[vdsat]
let Vth_M2 = @m.x1.xm2.m0[vth]
let ao_M2 = gm_M2*ro_M2
let gmid_M2 = gm_M2/id_M2
let fT_M2 = gm_M2/(6.283185*@m.x1.xm2.m0[cgg])
print #####_M2_nmos_input_##### id_M2 gm_M2 ro_M2 Vgs_M2 Vds_M2 Vsb_M2 Vdsat_M2 Vth_M2 ao_M2 gmid_M2 fT_M2

let #####_M3_pmos_top_##### = 0 
let id_M3 = @m.x1.xm3.m0[id]
let gm_M3 = @m.x1.xm3.m0[gm]
let ro_M3 = 1/@m.x1.xm3.m0[gds]
let Vsg_M3 = @m.x1.xm3.m0[vgs]
let Vsd_M3 = @m.x1.xm3.m0[vds]
let Vbs_M3 = -@m.x1.xm3.m0[vbs]
let Vdsat_M3 = @m.x1.xm3.m0[vdsat]
let Vth_M3 = @m.x1.xm3.m0[vth]
let ao_M3 = gm_M3*ro_M3
let gmid_M3 = gm_M3/id_M3
let fT_M3 = gm_M3/(6.283185*@m.x1.xm3.m0[cgg])
print #####_M3_pmos_top_##### id_M3 gm_M3 ro_M3 Vsg_M3 Vsd_M3 Vbs_M3 Vdsat_M3 Vth_M3 ao_M3 gmid_M3 fT_M3

let #####_M4_pmos_top_##### = 0 
let id_M4 = @m.x1.xm4.m0[id]
let gm_M4 = @m.x1.xm4.m0[gm]
let ro_M4 = 1/@m.x1.xm4.m0[gds]
let Vsg_M4 = @m.x1.xm4.m0[vgs]
let Vsd_M4 = @m.x1.xm4.m0[vds]
let Vbs_M4 = -@m.x1.xm4.m0[vbs]
let Vdsat_M4 = @m.x1.xm4.m0[vdsat]
let Vth_M4 = @m.x1.xm4.m0[vth]
let ao_M4 = gm_M4*ro_M4
let gmid_M4 = gm_M4/id_M4
let fT_M4 = gm_M4/(6.283185*@m.x1.xm4.m0[cgg])
print #####_M4_pmos_top_##### id_M4 gm_M4 ro_M4 Vsg_M4 Vsd_M4 Vbs_M4 Vdsat_M4 Vth_M4 ao_M4 gmid_M4 fT_M4

let #####_M5_pmos_out_##### = 0 
let id_M5 = @m.x1.xm5.m0[id]
let gm_M5 = @m.x1.xm5.m0[gm]
let ro_M5 = 1/@m.x1.xm5.m0[gds]
let Vsg_M5 = @m.x1.xm5.m0[vgs]
let Vsd_M5 = @m.x1.xm5.m0[vds]
let Vbs_M5 = -@m.x1.xm5.m0[vbs]
let Vdsat_M5 = @m.x1.xm5.m0[vdsat]
let Vth_M5 = @m.x1.xm5.m0[vth]
let ao_M5 = gm_M5*ro_M5
let gmid_M5 = gm_M5/id_M5
let fT_M5 = gm_M5/(6.283185*@m.x1.xm5.m0[cgg])
print #####_M5_pmos_out_##### id_M5 gm_M5 ro_M5 Vsg_M5 Vsd_M5 Vbs_M5 Vdsat_M5 Vth_M5 ao_M5 gmid_M5 fT_M5

let #####_M6_pmos_out_##### = 0 
let id_M6 = @m.x1.xm6.m0[id]
let gm_M6 = @m.x1.xm6.m0[gm]
let ro_M6 = 1/@m.x1.xm6.m0[gds]
let Vsg_M6 = @m.x1.xm6.m0[vgs]
let Vsd_M6 = @m.x1.xm6.m0[vds]
let Vbs_M6 = -@m.x1.xm6.m0[vbs]
let Vdsat_M6 = @m.x1.xm6.m0[vdsat]
let Vth_M6 = @m.x1.xm6.m0[vth]
let ao_M6 = gm_M6*ro_M6
let gmid_M6 = gm_M6/id_M6
let fT_M6 = gm_M6/(6.283185*@m.x1.xm6.m0[cgg])
print #####_M6_pmos_out_##### id_M6 gm_M6 ro_M6 Vsg_M6 Vsd_M6 Vbs_M6 Vdsat_M6 Vth_M6 ao_M6 gmid_M6 fT_M6

let #####_M7_nmos_out_##### = 0 
let id_M7 = @m.x1.xm7.m0[id]
let gm_M7 = @m.x1.xm7.m0[gm]
let ro_M7 = 1/@m.x1.xm7.m0[gds]
let Vgs_M7 = @m.x1.xm7.m0[vgs]
let Vds_M7 = @m.x1.xm7.m0[vds]
let Vsb_M7 = -@m.x1.xm7.m0[vbs]
let Vdsat_M7 = @m.x1.xm7.m0[vdsat]
let Vth_M7 = @m.x1.xm7.m0[vth]
let ao_M7 = gm_M7*ro_M7
let gmid_M7 = gm_M7/id_M7
let fT_M7 = gm_M7/(6.283185*@m.x1.xm7.m0[cgg])
print #####_M7_nmos_out_##### id_M7 gm_M7 ro_M7 Vgs_M7 Vds_M7 Vsb_M7 Vdsat_M7 Vth_M7 ao_M7 gmid_M7 fT_M7

let #####_M8_nmos_out_##### = 0 
let id_M8 = @m.x1.xm8.m0[id]
let gm_M8 = @m.x1.xm8.m0[gm]
let ro_M8 = 1/@m.x1.xm8.m0[gds]
let Vgs_M8 = @m.x1.xm8.m0[vgs]
let Vds_M8 = @m.x1.xm8.m0[vds]
let Vsb_M8 = -@m.x1.xm8.m0[vbs]
let Vdsat_M8 = @m.x1.xm8.m0[vdsat]
let Vth_M8 = @m.x1.xm8.m0[vth]
let ao_M8 = gm_M8*ro_M8
let gmid_M8 = gm_M8/id_M8
let fT_M8 = gm_M8/(6.283185*@m.x1.xm8.m0[cgg])
print #####_M8_nmos_out_##### id_M8 gm_M8 ro_M8 Vgs_M8 Vds_M8 Vsb_M8 Vdsat_M8 Vth_M8 ao_M8 gmid_M8 fT_M8

let #####_M9_nmos_bottom_##### = 0 
let id_M9 = @m.x1.xm9.m0[id]
let gm_M9 = @m.x1.xm9.m0[gm]
let ro_M9 = 1/@m.x1.xm9.m0[gds]
let Vgs_M9 = @m.x1.xm9.m0[vgs]
let Vds_M9 = @m.x1.xm9.m0[vds]
let Vsb_M9 = -@m.x1.xm9.m0[vbs]
let Vdsat_M9 = @m.x1.xm9.m0[vdsat]
let Vth_M9 = @m.x1.xm9.m0[vth]
let ao_M9 = gm_M9*ro_M9
let gmid_M9 = gm_M9/id_M9
let fT_M9 = gm_M9/(6.283185*@m.x1.xm9.m0[cgg])
print #####_M9_nmos_bottom_##### id_M9 gm_M9 ro_M9 Vgs_M9 Vds_M9 Vsb_M9 Vdsat_M9 Vth_M9 ao_M9 gmid_M9 fT_M9

let #####_M10_nmos_bottom_##### = 0 
let id_M10 = @m.x1.xm10.m0[id]
let gm_M10 = @m.x1.xm10.m0[gm]
let ro_M10 = 1/@m.x1.xm10.m0[gds]
let Vgs_M10 = @m.x1.xm10.m0[vgs]
let Vds_M10 = @m.x1.xm10.m0[vds]
let Vsb_M10 = @m.x1.xm10.m0[vbs]
let Vdsat_M10 = @m.x1.xm10.m0[vdsat]
let Vth_M10 = @m.x1.xm10.m0[vth]
let ao_M10 = gm_M10*ro_M10
let gmid_M10 = gm_M10/id_M10
let fT_M10 = gm_M10/(6.283185*@m.x1.xm10.m0[cgg])
print #####_M10_nmos_bottom_##### id_M10 gm_M10 ro_M10 Vgs_M10 Vds_M10 Vsb_M10 Vdsat_M10 Vth_M10 ao_M10 gmid_M10 fT_M10

let #####_M11_nmos_mirror_##### = 0 
let id_M11 = @m.x1.xm11.m0[id]
let gm_M11 = @m.x1.xm11.m0[gm]
let ro_M11 = 1/@m.x1.xm11.m0[gds]
let Vgs_M11 = @m.x1.xm11.m0[vgs]
let Vds_M11 = @m.x1.xm11.m0[vds]
let Vsb_M11 = -@m.x1.xm11.m0[vbs]
let Vdsat_M11 = @m.x1.xm11.m0[vdsat]
let Vth_M11 = @m.x1.xm11.m0[vth]
let ao_M11 = gm_M11*ro_M11
let gmid_M11 = gm_M11/id_M11
let fT_M11 = gm_M11/(6.283185*@m.x1.xm11.m0[cgg])
print #####_M11_nmos_mirror_##### id_M11 gm_M11 ro_M11 Vgs_M11 Vds_M11 Vsb_M11 Vdsat_M11 Vth_M11 ao_M11 gmid_M11 fT_M11

** Custom output
let #####_Custom_output_##### = 0
* Power
let power = (id_M11 + id_M10 + id_M9)*VDD
* DC_gain
let r1 = ao_M6*ro_M4
let r2 = ao_M8*((ro_M1*ro_M10)/(ro_M1+ro_M10))
let Rout = (r1*r2)/(r1+r2)
let Av = db(gm_M1*Rout)
* Bandwidth 
let BW = 1/(Rout*1e-12*6.283185)

print #####_Custom_output_##### Av BW Rout power gm_M1 ro_M1 gm_M6 ro_M6 ro_M4 gm_M8 ro_M8 ro_M10

write error_amplifier_core_N_input_os.raw

setplot dc1
let dvout = deriv(v(Vout))

meas dc limmin when dvout=0.98 rise=1
meas dc limmax when dvout=0.98 fall=1

let Output_swing = limmax - limmin

print Output_swing
plot dvout



.endc
"}
C {devices/code_shown.sym} 540 -500 0 0 {name=Voltage_sources only_toplevel=true
value="
.param VDD = 1.8
.param VSS = 0
.param VbiasN1 = 0.77
.param VbiasN2 = 1.28
.param VbiasP2 = 0.46
.param Vin = 1.2
"}
C {/foss/designs/workarea/error_amplifier_core_N_input/xschem/error_amplifier_core_N_input.sym} 770 -220 0 0 {name=x1}

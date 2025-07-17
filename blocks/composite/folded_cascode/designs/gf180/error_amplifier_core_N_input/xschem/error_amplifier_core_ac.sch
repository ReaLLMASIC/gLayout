v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 1210 -240 1210 -180 {
lab=GND}
N 1120 -350 1210 -350 {
lab=Vout}
N 1210 -350 1210 -300 {
lab=Vout}
N 820 -380 920 -380 {
lab=V-}
N 510 -90 510 -80 {lab=GND}
N 510 -180 510 -150 {lab=Vin}
N 820 -320 920 -320 {
lab=Vin}
N 270 -90 270 -80 {lab=GND}
N 270 -180 270 -150 {lab=VbiasP2}
N 350 -90 350 -80 {lab=GND}
N 350 -180 350 -150 {lab=VbiasN2}
N 430 -90 430 -80 {lab=GND}
N 430 -180 430 -150 {lab=VbiasN1}
N 110 -90 110 -80 {lab=GND}
N 110 -180 110 -150 {lab=VDD}
N 190 -90 190 -80 {lab=GND}
N 190 -180 190 -150 {lab=VSS}
N 1160 -350 1160 -90 {lab=Vout}
N 1050 -90 1160 -90 {lab=Vout}
N 790 -90 990 -90 {lab=#net1}
N 650 -320 820 -320 {lab=Vin}
N 650 -320 650 -90 {lab=Vin}
N 650 -90 730 -90 {lab=Vin}
N 820 -140 820 -90 {lab=#net1}
N 820 -240 820 -200 {lab=V-}
C {vsource.sym} 820 -170 0 0 {name=V5 value="AC 1" savecurrent=false}
C {capa.sym} 760 -90 1 0 {name=C2
m=1
value=10G
footprint=1206
device="ceramic capacitor"}
C {ind.sym} 1020 -90 1 0 {name=L4
m=1
value=10G
footprint=1206
device=inductor}
C {devices/code_shown.sym} 50 -580 0 0 {name=MODELS only_toplevel=true
format="tcleval( @value )"
value="
.include $::180MCU_MODELS/design.ngspice
.lib $::180MCU_MODELS/sm141064.ngspice typical
"}
C {devices/lab_wire.sym} 970 -160 0 0 {name=p5 sig_type=std_logic lab=VbiasN1}
C {devices/lab_wire.sym} 970 -180 0 0 {name=p6 sig_type=std_logic lab=VbiasN2}
C {devices/lab_wire.sym} 970 -200 0 0 {name=p11 sig_type=std_logic lab=VbiasP2}
C {devices/noconn.sym} 970 -220 0 0 {name=l2}
C {devices/lab_wire.sym} 970 -240 0 0 {name=p12 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 970 -260 0 0 {name=p13 sig_type=std_logic lab=VDD}
C {devices/capa.sym} 1210 -270 0 0 {name=C3
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {devices/vsource.sym} 510 -120 0 0 {name=V6 value=\{Vin\}}
C {devices/gnd.sym} 510 -80 0 0 {name=l3 lab=GND}
C {devices/lab_wire.sym} 510 -180 0 0 {name=p14 sig_type=std_logic lab=Vin}
C {devices/lab_wire.sym} 1210 -350 0 0 {name=p15 sig_type=std_logic lab=Vout}
C {devices/gnd.sym} 1210 -180 0 0 {name=l8 lab=GND}
C {simulator_commands.sym} 990 -580 0 0 {name=COMMANDS1
simulator=ngspice
only_toplevel=false 
value="
.control
save all

** OP simulation
op

** run ac simulation
ac dec 20 1 100e6

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

write error_amplifier_core_N_input_ac.raw

setplot ac1

* measure parameters
let vout_mag = db(abs(v(Vout)))
let vout_phase = cph(v(Vout)) * 180/pi
let gm = (-1)*db(abs(v(Vout)))

meas ac A0 find vout_mag at=1e2
meas ac UGB when vout_mag=0 fall=1
meas ac PM find vout_phase when vout_mag=0
meas ac GM find gm when vout_phase=0

let A0_p1 = A0 - 3
meas ac BW when vout_mag=A0_p1

plot vout_mag vout_phase

.endc
"}
C {devices/code_shown.sym} 710 -600 0 0 {name=Voltage_sources only_toplevel=true
value="
.param VDD = 1.8
.param VSS = 0
.param VbiasN1 = 0.77
.param VbiasN2 = 1.28
.param VbiasP2 = 0.46
.param Vin = 1
"}
C {/foss/designs/workarea/error_amplifier_core_N_input/xschem/error_amplifier_core_N_input.sym} 1020 -350 0 0 {name=x1}
C {devices/vsource.sym} 270 -120 0 0 {name=V1 value=\{VbiasP2\}}
C {devices/gnd.sym} 270 -80 0 0 {name=l9 lab=GND}
C {devices/lab_wire.sym} 270 -180 0 0 {name=p16 sig_type=std_logic lab=VbiasP2}
C {devices/vsource.sym} 350 -120 0 0 {name=V3 value=\{VbiasN2\}}
C {devices/gnd.sym} 350 -80 0 0 {name=l10 lab=GND}
C {devices/lab_wire.sym} 350 -180 0 0 {name=p17 sig_type=std_logic lab=VbiasN2}
C {devices/vsource.sym} 430 -120 0 0 {name=V7 value=\{VbiasN1\}}
C {devices/gnd.sym} 430 -80 0 0 {name=l11 lab=GND}
C {devices/lab_wire.sym} 430 -180 0 0 {name=p18 sig_type=std_logic lab=VbiasN1}
C {devices/vsource.sym} 110 -120 0 0 {name=V8 value=\{VDD\}}
C {devices/gnd.sym} 110 -80 0 0 {name=l12 lab=GND}
C {devices/lab_wire.sym} 110 -180 0 0 {name=p19 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 190 -120 0 0 {name=V9 value=\{VSS\}}
C {devices/gnd.sym} 190 -80 0 0 {name=l13 lab=GND}
C {devices/lab_wire.sym} 190 -180 0 0 {name=p20 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 820 -380 0 0 {name=p1 sig_type=std_logic lab=V-}
C {devices/lab_wire.sym} 820 -240 0 0 {name=p2 sig_type=std_logic lab=V-}
C {devices/launcher.sym} 140 -410 0 0 {name=h1
descr="Save & Netlist & sim" 
tclcommand="xschem save; xschem netlist; xschem simulate"}
C {launcher.sym} 140 -340 0 0 {name=h2
descr="Annotate OP"
tclcommand="set show_hidden_texts 1; xschem annotate_op"}
C {devices/lab_wire.sym} 820 -320 0 0 {name=p3 sig_type=std_logic lab=Vin}

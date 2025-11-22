v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
L 4 990 -560 1410 -560 {}
L 4 990 -510 1410 -510 {}
L 4 1120 -560 1120 -200 {}
L 4 1210 -560 1210 -200 {}
L 4 1300 -560 1300 -200 {}
L 4 1410 -560 1410 -200 {}
L 4 990 -560 990 -200 {}
L 4 990 -200 1410 -200 {}
T {Expected values for inputs:} 1070 -610 0 0 0.4 0.4 {}
T {Input} 1030 -550 0 0 0.4 0.4 {}
T {Min} 1150 -550 0 0 0.4 0.4 {}
T {Typ} 1240 -550 0 0 0.4 0.4 {}
T {Max} 1340 -550 0 0 0.4 0.4 {}
T {VDD} 1030 -500 0 0 0.4 0.4 {}
T {1.8} 1240 -500 0 0 0.4 0.4 {}
T {VIN_CM} 1010 -450 0 0 0.4 0.4 {}
T {0.8} 1340 -450 0 0 0.4 0.4 {}
T {VbiasP1} 1010 -400 0 0 0.4 0.4 {}
T {VbiasP2} 1010 -350 0 0 0.4 0.4 {}
T {VbiasN1} 1010 -300 0 0 0.4 0.4 {}
T {VbiasN2} 1010 -250 0 0 0.4 0.4 {}
T {0.95} 1235 -400 0 0 0.4 0.4 {}
T {0.81} 1240 -300 0 0 0.4 0.4 {}
T {1.28} 1235 -250 0 0 0.4 0.4 {}
T {0.4} 1235 -350 0 0 0.4 0.4 {}
N 630 -570 690 -570 {lab=Vout}
N 350 -280 430 -280 {
lab=Vx}
N 350 -330 350 -280 {
lab=Vx}
N 210 -280 250 -280 {
lab=Vin}
N 310 -280 350 -280 {
lab=Vx}
N 170 -280 210 -280 {
lab=Vin}
N 760 -570 760 -360 {
lab=Vout}
N 840 -440 840 -360 {
lab=GND}
N 840 -570 840 -510 {
lab=Vout}
N 690 -570 840 -570 {
lab=Vout}
N 350 -430 350 -390 {
lab=Vn}
N 840 -510 840 -500 {
lab=Vout}
N 210 -360 210 -280 {lab=Vin}
N 760 -360 760 -280 {lab=Vout}
N 210 -540 430 -540 {lab=Vin}
N 210 -540 210 -360 {lab=Vin}
N 350 -600 430 -600 {lab=Vn}
N 350 -520 350 -430 {lab=Vn}
N 330 -520 350 -520 {lab=Vn}
N 330 -560 330 -520 {lab=Vn}
N 330 -560 350 -560 {lab=Vn}
N 350 -600 350 -560 {lab=Vn}
N 390 -20 390 -10 {lab=GND}
N 390 -110 390 -80 {lab=VbiasP2}
N 470 -20 470 -10 {lab=GND}
N 470 -110 470 -80 {lab=VbiasN2}
N 550 -20 550 -10 {lab=GND}
N 550 -110 550 -80 {lab=VbiasN1}
N 230 -20 230 -10 {lab=GND}
N 230 -110 230 -80 {lab=VDD}
N 310 -20 310 -10 {lab=GND}
N 310 -110 310 -80 {lab=VSS}
N 630 -110 630 -80 {lab=VbiasP1}
N 630 -20 630 -10 {lab=GND}
N 170 -190 170 -180 {lab=GND}
N 170 -280 170 -250 {lab=Vin}
N 840 -360 840 -340 {lab=GND}
N 430 -440 480 -440 {lab=Vcom}
N 430 -280 450 -280 {lab=Vx}
N 710 -250 760 -250 {lab=Vout}
N 760 -280 760 -250 {lab=Vout}
N 670 -200 670 -170 {lab=GND}
N 710 -210 750 -210 {lab=GND}
N 750 -210 750 -180 {lab=GND}
N 670 -180 750 -180 {lab=GND}
N 670 -280 670 -260 {lab=Vz}
N 620 -280 670 -280 {lab=Vz}
N 510 -280 560 -280 {lab=Vy}
C {simulator_commands.sym} -20 -410 0 0 {name="COMMANDS"
simulator="ngspice"
only_toplevel="false" 
value="

* --- Include PDK and Model Files ---
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

* --- Define Parameters for the Simulation ---
.param VDD = 1.8
.param VSS = 0
.param VbiasN1 = 0.81
.param VbiasN2 = 1.28
.param VbiasP1 = 0.95
.param VbiasP2 = 0.4
.param Vin_CM = 0.8
.param Vout_CM = 0.9
.param Vy = (Vout_CM - Vin_CM)
.param load_cap = 5*1e-12 

* --- Simulation Commands and Analysis ---
 

*+ abstol=1e-14 savecurrents
.control
    save all 
    
** OP simulation
op

** All OP parameters

let #####_M1_pmos_input_##### = 0 
let id_M1 = @m.x1.xm1.m0[id]
let gm_M1 = @m.x1.xm1.m0[gm]
let ro_M1 = 1/@m.x1.xm1.m0[gds]
let Vsg_M1 = @m.x1.xm1.m0[vgs]
let Vsd_M1 = @m.x1.xm1.m0[vds]
let Vbs_M1 = -@m.x1.xm1.m0[vbs]
let Vdsat_M1 = @m.x1.xm1.m0[vdsat]
let Vth_M1 = @m.x1.xm1.m0[vth]
let ao_M1 = gm_M1*ro_M1
let gmid_M1 = gm_M1/id_M1
let fT_M1 = gm_M1/(6.283185*@m.x1.xm1.m0[cgg])
print #####_M1_pmos_input_##### id_M1 gm_M1 ro_M1 Vsg_M1 Vsd_M1 Vbs_M1 Vdsat_M1 Vth_M1 ao_M1 gmid_M1 fT_M1 

let #####_M2_pmos_input_##### = 0 
let id_M2 = @m.x1.xm2.m0[id]
let gm_M2 = @m.x1.xm2.m0[gm]
let ro_M2 = 1/@m.x1.xm2.m0[gds]
let Vsg_M2 = @m.x1.xm2.m0[vgs]
let Vsd_M2 = @m.x1.xm2.m0[vds]
let Vbs_M2 = -@m.x1.xm2.m0[vbs]
let Vdsat_M2 = @m.x1.xm2.m0[vdsat]
let Vth_M2 = @m.x1.xm2.m0[vth]
let ao_M2 = gm_M2*ro_M2
let gmid_M2 = gm_M2/id_M2
let fT_M2 = gm_M2/(6.283185*@m.x1.xm2.m0[cgg])
print #####_M2_pmos_input_##### id_M2 gm_M2 ro_M2 Vsg_M2 Vsd_M2 Vbs_M2 Vdsat_M2 Vth_M2 ao_M2 gmid_M2 fT_M2 

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

let #####_M11_pmos_mirror_##### = 0 
let id_M11 = @m.x1.xm11.m0[id]
let gm_M11 = @m.x1.xm11.m0[gm]
let ro_M11 = 1/@m.x1.xm11.m0[gds]
let Vsg_M11 = @m.x1.xm11.m0[vgs]
let Vsd_M11 = @m.x1.xm11.m0[vds]
let Vbs_M11 = -@m.x1.xm11.m0[vbs]
let Vdsat_M11 = @m.x1.xm11.m0[vdsat]
let Vth_M11 = @m.x1.xm11.m0[vth]
let ao_M11 = gm_M11*ro_M11
let gmid_M11 = gm_M11/id_M11
let fT_M11 = gm_M11/(6.283185*@m.x1.xm11.m0[cgg])
print #####_M11_pmos_mirror_##### id_M11 gm_M11 ro_M11 Vsg_M11 Vsd_M11 Vbs_M11 Vdsat_M11 Vth_M11 ao_M11 gmid_M11 fT_M11

** Custom output
let #####_Custom_output_##### = 0

* DC_gain
let r1 = ao_M6*ro_M4
let r2 = ao_M8*((ro_M1*ro_M10)/(ro_M1+ro_M10))
let Rout = (r1*r2)/(r1+r2)
let Av = db(gm_M1*Rout)
* Bandwidth 
let BW = 1/(Rout*1e-12*6.283185)
let BW_2 = 1/(Rout*5p*6.283185)


print #####_Custom_output_##### Av BW BW_2 Rout gm_M1 ro_M1 gm_M6 ro_M6 ro_M4 gm_M8 ro_M8 ro_M10


    remzerovec
    write error_amplifier_core_N_input_ac.raw
    set appendwrite

    * run ac simulation
    ac dec 20 1 100e7

    * measure parameters
    let vout_mag_VV = abs(v(Vout))
    let vout_mag = db(abs(v(Vout)))
    let vout_phase = cph(v(Vout)) * 180/pi
    let gm = (-1)*db(abs(v(Vout)))

    meas ac A0 find vout_mag at=1
    meas ac UGB when vout_mag=0 fall=1
    meas ac PM find vout_phase when vout_mag=0
    meas ac GM find gm when vout_phase=0

    let A0_p1 = A0 - 3
    meas ac BW when vout_mag=A0_p1
    
    *plot vout_mag
    *plot vout_phase

    write error_amplifier_core_N_input_ac.raw
.endc
"}
C {devices/launcher.sym} 0 -570 0 0 {name=h15
descr="Annotate OP" 
tclcommand="set show_hidden_texts 1; xschem annotate_op"
}
C {devices/launcher.sym} 0 -640 0 0 {name=h3
descr="Netlist & sim" 
tclcommand="xschem netlist; xschem simulate"}
C {vsource.sym} 350 -360 0 0 {name=V5 value="AC 1" savecurrent=false}
C {capa.sym} 280 -280 1 0 {name=C2
m=1
value=10G
footprint=1206
device="ceramic capacitor"}
C {ind.sym} 480 -280 1 0 {name=L4
m=1
value=10G
footprint=1206
device=inductor}
C {lab_pin.sym} 480 -480 2 1 {name=p8 sig_type=std_logic lab=VDD}
C {lab_pin.sym} 480 -460 2 1 {name=p9 sig_type=std_logic lab=VSS}
C {gf180/error_amplifier_core_N_input/xschem/error_amplifier_core_N_input.sym} 530 -570 0 0 {name=x1}
C {capa.sym} 840 -470 0 0 {name=C1
m=1
value=5p
footprint=1206
device="ceramic capacitor"}
C {noconn.sym} 430 -440 2 1 {name=l1}
C {lab_pin.sym} 840 -570 0 1 {name=p2 sig_type=std_logic lab=Vout}
C {lab_pin.sym} 480 -420 2 1 {name=p5 sig_type=std_logic lab=VbiasP1}
C {lab_pin.sym} 480 -400 2 1 {name=p6 sig_type=std_logic lab=VbiasP2}
C {lab_pin.sym} 480 -380 2 1 {name=p7 sig_type=std_logic lab=VbiasN2}
C {lab_pin.sym} 480 -360 2 1 {name=p11 sig_type=std_logic lab=VbiasN1}
C {devices/vsource.sym} 390 -50 0 0 {name=V1 value=\{VbiasP2\}}
C {devices/gnd.sym} 390 -10 0 0 {name=l2 lab=GND}
C {devices/lab_wire.sym} 390 -110 0 0 {name=p3 sig_type=std_logic lab=VbiasP2}
C {devices/vsource.sym} 470 -50 0 0 {name=V2 value=\{VbiasN2\}}
C {devices/gnd.sym} 470 -10 0 0 {name=l3 lab=GND}
C {devices/lab_wire.sym} 470 -110 0 0 {name=p4 sig_type=std_logic lab=VbiasN2}
C {devices/vsource.sym} 550 -50 0 0 {name=V3 value=\{VbiasN1\}}
C {devices/gnd.sym} 550 -10 0 0 {name=l5 lab=GND}
C {devices/lab_wire.sym} 550 -110 0 0 {name=p12 sig_type=std_logic lab=VbiasN1}
C {devices/vsource.sym} 230 -50 0 0 {name=V4 value=\{VDD\}}
C {devices/gnd.sym} 230 -10 0 0 {name=l6 lab=GND}
C {devices/lab_wire.sym} 230 -110 0 0 {name=p13 sig_type=std_logic lab=VDD}
C {devices/vsource.sym} 310 -50 0 0 {name=V6 value=\{VSS\}}
C {devices/gnd.sym} 310 -10 0 0 {name=l7 lab=GND}
C {devices/lab_wire.sym} 310 -110 0 0 {name=p14 sig_type=std_logic lab=VSS}
C {devices/vsource.sym} 630 -50 0 0 {name=V8 value=\{VbiasP1\} savecurrent=false}
C {devices/gnd.sym} 630 -10 0 0 {name=l10 lab=GND}
C {devices/lab_wire.sym} 630 -110 0 0 {name=p15 sig_type=std_logic lab=VbiasP1
}
C {devices/vsource.sym} 170 -220 0 0 {name=V7 value=\{Vin_CM\}}
C {devices/gnd.sym} 170 -180 0 0 {name=l8 lab=GND}
C {devices/lab_wire.sym} 170 -280 0 0 {name=p10 sig_type=std_logic lab=Vin}
C {devices/gnd.sym} 840 -340 0 0 {name=l9 lab=GND}
C {devices/lab_wire.sym} 390 -280 0 0 {name=p1 sig_type=std_logic lab=Vx}
C {devices/lab_wire.sym} 460 -440 0 0 {name=p16 sig_type=std_logic lab=Vcom}
C {devices/lab_wire.sym} 370 -600 0 0 {name=p17 sig_type=std_logic lab=Vn}
C {devices/vsource.sym} 590 -280 1 0 {name=V9 value=\{Vy\}}
C {vcvs.sym} 670 -230 0 1 {name=E1 value=1}
C {devices/gnd.sym} 670 -170 0 0 {name=l11 lab=GND}
C {devices/lab_wire.sym} 530 -280 0 0 {name=p18 sig_type=std_logic lab=Vy}
C {devices/lab_wire.sym} 670 -280 0 0 {name=p19 sig_type=std_logic lab=Vz}

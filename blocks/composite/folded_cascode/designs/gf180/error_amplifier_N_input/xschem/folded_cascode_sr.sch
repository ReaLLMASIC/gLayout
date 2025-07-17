v {xschem version=3.4.6 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 110 -120 110 -100 {
lab=GND}
N 110 -220 110 -180 {
lab=VSS}
N 190 -120 190 -100 {
lab=GND}
N 110 -100 110 -80 {
lab=GND}
N 190 -220 190 -180 {
lab=VDD}
N 190 -100 190 -80 {
lab=GND}
N 270 -120 270 -100 {
lab=GND}
N 270 -220 270 -180 {
lab=Vref}
N 270 -100 270 -80 {
lab=GND}
N 850 -540 910 -540 {lab=Vout}
N 1060 -410 1060 -330 {
lab=VSS}
N 1060 -540 1060 -480 {
lab=Vout}
N 910 -540 1060 -540 {
lab=Vout}
N 490 -520 670 -520 {
lab=Vin}
N 1060 -480 1060 -470 {
lab=Vout}
N 560 -570 670 -570 {
lab=Vout}
N 560 -650 560 -570 {
lab=Vout}
N 560 -650 910 -650 {
lab=Vout}
N 910 -650 910 -540 {
lab=Vout}
N 350 -220 350 -180 {
lab=Vin}
N 350 -120 350 -100 {
lab=GND}
N 350 -100 350 -80 {
lab=GND}
C {sky130_fd_pr/corner.sym} 60 -390 0 0 {name=CORNER only_toplevel=true corner=tt}
C {simulator_commands.sym} 210 -390 0 0 {name="COMMANDS"
simulator="ngspice"
only_toplevel="false" 
value="
.param VDD=1.8
.param Vref=1.2
.param V1 = 0.01
.param V2 = 1.8
.param TR = 50n
.param TF = TR
.param PER = 2m
.param TD = 0.05*PER
.param PWM = PER/2
.save

* Operation point of the folded cascode core

*nfet 

+ @m.x1.x2.xm1.msky130_fd_pr__nfet_01v8[gm]
+ v(@m.x1.x2.xm1.msky130_fd_pr__nfet_01v8[vth])
+ @m.x1.x2.xm1.msky130_fd_pr__nfet_01v8[gds]
+ @m.x1.x2.xm1.msky130_fd_pr__nfet_01v8[id]

+ @m.x1.x2.xm2.msky130_fd_pr__nfet_01v8[gm]
+ v(@m.x1.x2.xm2.msky130_fd_pr__nfet_01v8[vth])
+ @m.x1.x2.xm2.msky130_fd_pr__nfet_01v8[gds]
+ @m.x1.x2.xm2.msky130_fd_pr__nfet_01v8[id]

+ @m.x1.x2.xm7.msky130_fd_pr__nfet_01v8[gm]
+ v(@m.x1.x2.xm7.msky130_fd_pr__nfet_01v8[vth])
+ @m.x1.x2.xm7.msky130_fd_pr__nfet_01v8[gds]
+ @m.x1.x2.xm7.msky130_fd_pr__nfet_01v8[id]

+ @m.x1.x2.xm8.msky130_fd_pr__nfet_01v8[gm]
+ v(@m.x1.x2.xm8.msky130_fd_pr__nfet_01v8[vth])
+ @m.x1.x2.xm8.msky130_fd_pr__nfet_01v8[gds]
+ @m.x1.x2.xm8.msky130_fd_pr__nfet_01v8[id]

+ @m.x1.x2.xm9.msky130_fd_pr__nfet_01v8[gm]
+ v(@m.x1.x2.xm9.msky130_fd_pr__nfet_01v8[vth])
+ @m.x1.x2.xm9.msky130_fd_pr__nfet_01v8[gds]
+ @m.x1.x2.xm9.msky130_fd_pr__nfet_01v8[id]

+ @m.x1.x2.xm10.msky130_fd_pr__nfet_01v8[gm]
+ v(@m.x1.x2.xm10.msky130_fd_pr__nfet_01v8[vth])
+ @m.x1.x2.xm10.msky130_fd_pr__nfet_01v8[gds]
+ @m.x1.x2.xm10.msky130_fd_pr__nfet_01v8[id]

+ @m.x1.x2.xm11.msky130_fd_pr__nfet_01v8[gm]
+ v(@m.x1.x2.xm11.msky130_fd_pr__nfet_01v8[vth])
+ @m.x1.x2.xm11.msky130_fd_pr__nfet_01v8[gds]
+ @m.x1.x2.xm11.msky130_fd_pr__nfet_01v8[id]

*pfet

+ @m.x1.x2.xm3.msky130_fd_pr__pfet_01v8_lvt[gm]
+ v(@m.x1.x2.xm3.msky130_fd_pr__pfet_01v8_lvt[vth])
+ @m.x1.x2.xm3.msky130_fd_pr__pfet_01v8_lvt[gds]
+ @m.x1.x2.xm3.msky130_fd_pr__pfet_01v8_lvt[id]

+ @m.x1.x2.xm4.msky130_fd_pr__pfet_01v8_lvt[gm]
+ v(@m.x1.x2.xm4.msky130_fd_pr__pfet_01v8_lvt[vth])
+ @m.x1.x2.xm4.msky130_fd_pr__pfet_01v8_lvt[gds]
+ @m.x1.x2.xm4.msky130_fd_pr__pfet_01v8_lvt[id]

+ @m.x1.x2.xm5.msky130_fd_pr__pfet_01v8_lvt[gm]
+ v(@m.x1.x2.xm5.msky130_fd_pr__pfet_01v8_lvt[vth])
+ @m.x1.x2.xm5.msky130_fd_pr__pfet_01v8_lvt[gds]
+ @m.x1.x2.xm5.msky130_fd_pr__pfet_01v8_lvt[id]

+ @m.x1.x2.xm6.msky130_fd_pr__pfet_01v8_lvt[gm]
+ v(@m.x1.x2.xm6.msky130_fd_pr__pfet_01v8_lvt[vth])
+ @m.x1.x2.xm6.msky130_fd_pr__pfet_01v8_lvt[gds]
+ @m.x1.x2.xm6.msky130_fd_pr__pfet_01v8_lvt[id]

* Operation point of the folded cascode bias


+ abstol=1e-14 savecurrents
.control
    save all
    op
    remzerovec
    write folded_cascode_sr.raw
    set appendwrite

    * run ac simulation
    tran 25n 2m

    * measure parameters
    let dVout = deriv(Vout)/1e6
    meas tran SRplus MAX dVout
    meas tran SRminus MIN dVout

    meas tran Voutmax MAX Vout
    meas tran Voutmin MIN Vout
    let Output_swing = Voutmax-Voutmin
    print Output_swing

    plot Vout Vin

    write folded_cascode_sr.raw
.endc
"
}
C {devices/vsource.sym} 110 -150 0 0 {name=V0 value=0 savecurrent=false}
C {devices/gnd.sym} 110 -80 0 0 {name=l5 lab=GND}
C {devices/vsource.sym} 190 -150 0 0 {name=V2 value=\{VDD\} savecurrent=false}
C {devices/lab_wire.sym} 110 -220 0 0 {name=p25 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 190 -220 0 0 {name=p26 sig_type=std_logic lab=VDD}
C {devices/gnd.sym} 190 -80 0 0 {name=l6 lab=GND}
C {devices/vsource.sym} 270 -150 0 0 {name=V4 value=\{Vref\} savecurrent=false}
C {devices/lab_wire.sym} 270 -220 0 0 {name=p27 sig_type=std_logic lab=Vref}
C {devices/gnd.sym} 270 -80 0 0 {name=l7 lab=GND}
C {devices/launcher.sym} 160 -510 0 0 {name=h15
descr="Annotate OP" 
tclcommand="set show_hidden_texts 1; xschem annotate_op"
}
C {devices/launcher.sym} 160 -580 0 0 {name=h3
descr="Netlist & sim" 
tclcommand="xschem netlist; xschem simulate"}
C {lab_pin.sym} 740 -460 2 1 {name=p7 sig_type=std_logic lab=Vref}
C {lab_pin.sym} 740 -440 2 1 {name=p8 sig_type=std_logic lab=VDD}
C {lab_pin.sym} 740 -420 2 1 {name=p9 sig_type=std_logic lab=VSS}
C {lab_pin.sym} 490 -520 2 1 {name=p10 sig_type=std_logic lab=Vin}
C {capa.sym} 1060 -440 0 0 {name=C1
m=1
value=1p
footprint=1206
device="ceramic capacitor"}
C {lab_pin.sym} 1060 -330 2 1 {name=p1 sig_type=std_logic lab=VSS}
C {noconn.sym} 780 -480 2 0 {name=l1}
C {lab_pin.sym} 1060 -540 0 1 {name=p2 sig_type=std_logic lab=Vout}
C {vsource.sym} 350 -150 0 0 {name=V3 value="pulse(\{V1\} \{V2\} \{TD\} \{TR\} \{TF\} \{PWM\} \{PER\})" savecurrent=false
*pulse(0.01 1.8 \{TD\} \{TR\} \{TF\} \{PWM\} \{PER\})
*sin(0.9 0.8 1k)}
C {devices/lab_wire.sym} 350 -220 0 0 {name=p3 sig_type=std_logic lab=Vin}
C {devices/gnd.sym} 350 -80 0 0 {name=l2 lab=GND}
C {/foss/designs/chipathon_2025/designs/sky130/error_amplifier_N_input/xschem/error_amplifier_N_input.sym} 760 -540 0 0 {name=x1}

v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 790 -390 790 -350 {lab=VDD_3V3}
N 790 -230 790 -200 {lab=GND}
N 940 -470 940 -410 {lab=VDD_3V3}
N 980 -380 1020 -380 {lab=V_IN}
N 940 -350 940 -310 {lab=V_IN}
N 920 -380 940 -380 {lab=VDD_3V3}
N 920 -420 920 -380 {lab=VDD_3V3}
N 920 -420 940 -420 {lab=VDD_3V3}
N 1000 -380 1000 -330 {lab=V_IN}
N 940 -330 1000 -330 {lab=V_IN}
N 1220 -460 1220 -400 {lab=VDD_3V3}
N 1260 -370 1300 -370 {lab=V_AUX}
N 1220 -340 1220 -300 {lab=V_AUX}
N 1200 -370 1220 -370 {lab=VDD_3V3}
N 1200 -410 1200 -370 {lab=VDD_3V3}
N 1200 -410 1220 -410 {lab=VDD_3V3}
N 1280 -370 1280 -320 {lab=V_AUX}
N 1220 -320 1280 -320 {lab=V_AUX}
N 1220 -240 1220 -200 {lab=GND}
N 1520 -370 1550 -370 {lab=VDD_3V3}
N 1550 -190 1550 -160 {lab=GND}
N 2000 -350 2130 -350 {lab=#net1}
N 2130 -360 2130 -350 {lab=#net1}
N 2000 -330 2130 -330 {lab=#net2}
N 2130 -330 2130 -270 {lab=#net2}
N 2000 -310 2100 -310 {lab=#net3}
N 2100 -310 2100 -170 {lab=#net3}
N 2100 -170 2130 -170 {lab=#net3}
N 1520 -350 1550 -350 {lab=V_IN}
N 1520 -310 1550 -310 {lab=V_IN}
N 1450 -330 1550 -330 {lab=V_IN}
N 1510 -250 1550 -250 {lab=V_AUX}
N 1520 -330 1520 -310 {lab=V_IN}
N 1520 -350 1520 -330 {lab=V_IN}
N 940 -250 940 -210 {lab=GND}
N 1020 -380 1040 -380 {lab=V_IN}
N 1300 -370 1330 -370 {lab=V_AUX}
C {title.sym} 160 -30 0 0 {name=l1 author="Quentin Halbach"}
C {devices/code_shown.sym} 20 -140 0 0 {name=MODELS only_toplevel=true
format="tcleval( @value )"
value="
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

"}
C {vsource.sym} 790 -260 0 0 {name=V1 value=3.3 savecurrent=false}
C {gnd.sym} 790 -200 0 0 {name=l10 lab=GND}
C {symbols/pfet_03v3.sym} 960 -380 0 1 {name=M7
L=1u
W=5u
nf=1
m=1
ad="'int((nf+1)/2) * W/nf * 0.18u'"
pd="'2*int((nf+1)/2) * (W/nf + 0.18u)'"
as="'int((nf+2)/2) * W/nf * 0.18u'"
ps="'2*int((nf+2)/2) * (W/nf + 0.18u)'"
nrd="'0.18u / W'" nrs="'0.18u / W'"
sa=0 sb=0 sd=0
model=pfet_03v3
spiceprefix=X
}
C {isource.sym} 940 -280 0 0 {name=I_in value=1u}
C {lab_wire.sym} 1040 -380 2 0 {name=p1 sig_type=std_logic lab=V_IN}
C {vsource.sym} 2220 -360 3 0 {name=v_vanilla value=1.65 savecurrent=true}
C {gnd.sym} 2250 -360 3 0 {name=l15 lab=GND}
C {code_shown.sym} 20 -780 0 0 {name=code only_toplevel=false value=
"
.option savecurrent

.control

save all

* --- Run vanilla sweep ---
dc v_vanilla 0 3.3 0.01
let i_vanilla = -i(v_vanilla)
wrdata vanilla.txt i_vanilla

* --- Run biased sweep ---
reset
dc v_biased 0 3.3 0.01
let i_biased = -i(v_biased)
wrdata biased.txt i_biased

* --- Run cascode sweep ---
reset
dc v_cascode 0 3.3 0.01
let i_cascode = -i(v_cascode)
wrdata cascode.txt i_cascode

.endc
"
}
C {lab_wire.sym} 1450 -330 0 0 {name=p3 sig_type=std_logic lab=V_IN}
C {gnd.sym} 1550 -160 0 0 {name=l3 lab=GND}
C {vsource.sym} 2220 -270 3 0 {name=v_biased value=1.65 savecurrent=true}
C {gnd.sym} 2250 -270 3 0 {name=l4 lab=GND}
C {vsource.sym} 2220 -170 3 0 {name=v_cascode value=1.65 savecurrent=true}
C {gnd.sym} 2250 -170 3 0 {name=l5 lab=GND}
C {symbols/pfet_03v3.sym} 1240 -370 0 1 {name=M1
L=1u
W=5u
nf=1
m=1
ad="'int((nf+1)/2) * W/nf * 0.18u'"
pd="'2*int((nf+1)/2) * (W/nf + 0.18u)'"
as="'int((nf+2)/2) * W/nf * 0.18u'"
ps="'2*int((nf+2)/2) * (W/nf + 0.18u)'"
nrd="'0.18u / W'" nrs="'0.18u / W'"
sa=0 sb=0 sd=0
model=pfet_03v3
spiceprefix=X
}
C {isource.sym} 1220 -270 0 0 {name=I_aux value=1n}
C {lab_wire.sym} 1330 -370 2 0 {name=p6 sig_type=std_logic lab=V_AUX}
C {gnd.sym} 1220 -200 0 0 {name=l16 lab=GND}
C {res.sym} 790 -320 0 0 {name=R4
value=50
footprint=1206
device=resistor
m=1}
C {res.sym} 2160 -360 3 0 {name=R3
value=50
footprint=1206
device=resistor
m=1}
C {res.sym} 2160 -270 3 0 {name=R5
value=50
footprint=1206
device=resistor
m=1}
C {res.sym} 2160 -170 3 0 {name=R6
value=50
footprint=1206
device=resistor
m=1}
C {top_level.sym} 1370 -90 0 0 {name=x1}
C {lab_wire.sym} 1510 -250 0 0 {name=p4 sig_type=std_logic lab=V_AUX}
C {lab_wire.sym} 790 -390 1 0 {name=p5 sig_type=std_logic lab=VDD_3V3}
C {lab_wire.sym} 940 -470 1 0 {name=p7 sig_type=std_logic lab=VDD_3V3}
C {lab_wire.sym} 1220 -460 1 0 {name=p8 sig_type=std_logic lab=VDD_3V3}
C {lab_wire.sym} 1520 -370 0 0 {name=p2 sig_type=std_logic lab=VDD_3V3}
C {gnd.sym} 940 -210 0 0 {name=l2 lab=GND}

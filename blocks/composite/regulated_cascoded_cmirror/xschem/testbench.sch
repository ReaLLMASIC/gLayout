v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 650 -750 650 -710 {lab=VDD}
N 650 -650 650 -620 {lab=GND}
N 850 -850 850 -790 {lab=VDD}
N 890 -760 930 -760 {lab=v_in}
N 850 -730 850 -690 {lab=v_in}
N 830 -760 850 -760 {lab=VDD}
N 830 -800 830 -760 {lab=VDD}
N 830 -800 850 -800 {lab=VDD}
N 910 -760 910 -710 {lab=v_in}
N 850 -710 910 -710 {lab=v_in}
N 850 -630 850 -590 {lab=GND}
N 1070 -300 1120 -300 {lab=#net1}
N 1540 -300 1590 -300 {lab=#net2}
N 2010 -300 2060 -300 {lab=#net3}
N 1130 -840 1130 -780 {lab=VDD}
N 1170 -750 1210 -750 {lab=v_aux}
N 1130 -720 1130 -680 {lab=v_aux}
N 1110 -750 1130 -750 {lab=VDD}
N 1110 -790 1110 -750 {lab=VDD}
N 1110 -790 1130 -790 {lab=VDD}
N 1190 -750 1190 -700 {lab=v_aux}
N 1130 -700 1190 -700 {lab=v_aux}
N 1130 -620 1130 -580 {lab=GND}
C {title.sym} 160 -30 0 0 {name=l1 author="Quentin Halbach"}
C {devices/code_shown.sym} 20 -140 0 0 {name=MODELS only_toplevel=true
format="tcleval( @value )"
value="
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

"}
C {vsource.sym} 650 -680 0 0 {name=V1 value=3.3 savecurrent=false}
C {vdd.sym} 650 -750 0 0 {name=l9 lab=VDD}
C {gnd.sym} 650 -620 0 0 {name=l10 lab=GND}
C {symbols/pfet_03v3.sym} 870 -760 0 1 {name=M7
L=0.9u
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
C {isource.sym} 850 -660 0 0 {name=I_in value=1u}
C {lab_wire.sym} 930 -760 2 0 {name=p1 sig_type=std_logic lab=v_in}
C {vdd.sym} 850 -850 0 0 {name=l12 lab=VDD}
C {gnd.sym} 850 -590 0 0 {name=l11 lab=GND}
C {vanilla_cm.sym} 920 -300 0 0 {name=x1}
C {lab_wire.sym} 770 -300 0 0 {name=p2 sig_type=std_logic lab=v_in}
C {vdd.sym} 920 -350 0 0 {name=l6 lab=VDD}
C {gnd.sym} 920 -250 0 0 {name=l7 lab=GND}
C {vsource.sym} 1120 -270 0 0 {name=v_vanilla value=1.65 savecurrent=true}
C {gnd.sym} 1120 -240 0 0 {name=l15 lab=GND}
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
C {biased_cm.sym} 1390 -200 0 0 {name=x2}
C {lab_wire.sym} 1240 -300 0 0 {name=p3 sig_type=std_logic lab=v_in}
C {vdd.sym} 1390 -350 0 0 {name=l2 lab=VDD}
C {gnd.sym} 1390 -250 0 0 {name=l3 lab=GND}
C {vsource.sym} 1590 -270 0 0 {name=v_biased value=1.65 savecurrent=true}
C {gnd.sym} 1590 -240 0 0 {name=l4 lab=GND}
C {cascode_cm.sym} 1860 -170 0 0 {name=x3}
C {lab_wire.sym} 1710 -310 0 0 {name=p4 sig_type=std_logic lab=v_in}
C {lab_wire.sym} 1710 -290 0 0 {name=p5 sig_type=std_logic lab=v_aux}
C {vsource.sym} 2060 -270 0 0 {name=v_cascode value=1.65 savecurrent=true}
C {gnd.sym} 2060 -240 0 0 {name=l5 lab=GND}
C {vdd.sym} 1860 -350 0 0 {name=l8 lab=VDD}
C {gnd.sym} 1860 -250 0 0 {name=l13 lab=GND}
C {symbols/pfet_03v3.sym} 1150 -750 0 1 {name=M1
L=0.9u
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
C {isource.sym} 1130 -650 0 0 {name=I_aux value=1n}
C {lab_wire.sym} 1210 -750 2 0 {name=p6 sig_type=std_logic lab=v_aux}
C {vdd.sym} 1130 -840 0 0 {name=l14 lab=VDD}
C {gnd.sym} 1130 -580 0 0 {name=l16 lab=GND}

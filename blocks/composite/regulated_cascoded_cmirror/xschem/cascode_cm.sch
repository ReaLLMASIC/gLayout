v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 170 -190 170 -70 {lab=vss}
N 230 -260 270 -260 {lab=#net1}
N 170 -610 170 -590 {lab=#net2}
N 110 -260 170 -260 {lab=vss}
N 110 -260 110 -220 {lab=vss}
N 210 -260 230 -260 {lab=#net1}
N 170 -230 170 -220 {lab=vss}
N 170 -620 170 -610 {lab=#net2}
N 170 -220 170 -190 {lab=vss}
N 170 -360 340 -360 {lab=#net2}
N 170 -360 170 -290 {lab=#net2}
N 380 -330 380 -170 {lab=#net1}
N 270 -260 380 -260 {lab=#net1}
N 170 -510 170 -360 {lab=#net2}
N 380 -110 380 -70 {lab=vss}
N 170 -70 380 -70 {lab=vss}
N 870 -430 870 -310 {lab=#net2}
N 770 -240 810 -240 {lab=#net3}
N 870 -240 930 -240 {lab=vss}
N 810 -240 830 -240 {lab=#net3}
N 870 -280 870 -270 {lab=#net2}
N 870 -310 870 -280 {lab=#net2}
N 870 -210 870 -140 {lab=vss}
N 660 -330 660 -170 {lab=#net3}
N 660 -240 770 -240 {lab=#net3}
N 660 -430 660 -390 {lab=v_out}
N 660 -110 660 -70 {lab=vss}
N 700 -360 870 -360 {lab=#net2}
N 660 -460 660 -430 {lab=v_out}
N 420 -140 620 -140 {lab=#net4}
N 380 -600 380 -390 {lab=#net4}
N 380 -440 510 -440 {lab=#net4}
N 510 -440 510 -140 {lab=#net4}
N 870 -610 870 -430 {lab=#net2}
N 200 -610 870 -610 {lab=#net2}
N 170 -610 200 -610 {lab=#net2}
N 170 -590 170 -510 {lab=#net2}
N 380 -690 380 -600 {lab=#net4}
N 170 -710 170 -620 {lab=#net2}
N 380 -710 380 -690 {lab=#net4}
N 870 -140 870 -70 {lab=vss}
N 660 -70 870 -70 {lab=vss}
N 370 -70 660 -70 {lab=vss}
N 870 -70 930 -70 {lab=vss}
N 380 -360 400 -360 {lab=vss}
N 350 -140 380 -140 {lab=vss}
N 350 -140 350 -70 {lab=vss}
N 660 -140 690 -140 {lab=vss}
N 690 -140 690 -70 {lab=vss}
N 620 -360 660 -360 {lab=vss}
N 930 -240 930 -70 {lab=vss}
N 110 -220 170 -220 {lab=vss}
N 380 -790 380 -770 {lab=vdd}
N 380 -740 400 -740 {lab=vdd}
N 400 -780 400 -740 {lab=vdd}
N 380 -780 400 -780 {lab=vdd}
N 320 -740 340 -740 {lab=v_in}
N 170 -790 170 -770 {lab=vdd}
N 170 -740 190 -740 {lab=vdd}
N 190 -780 190 -740 {lab=vdd}
N 170 -780 190 -780 {lab=vdd}
N 110 -740 130 -740 {lab=v_aux}
N 170 -790 380 -790 {lab=vdd}
N 400 -360 440 -360 {lab=vss}
N 440 -360 440 -70 {lab=vss}
N 570 -360 620 -360 {lab=vss}
N 570 -360 570 -80 {lab=vss}
N 570 -80 570 -70 {lab=vss}
C {symbols/nfet_03v3.sym} 190 -260 0 1 {name=M10
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
model=nfet_03v3
spiceprefix=X
}
C {symbols/nfet_03v3.sym} 360 -360 0 0 {name=M8
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
model=nfet_03v3
spiceprefix=X
}
C {symbols/nfet_03v3.sym} 400 -140 0 1 {name=M11
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
model=nfet_03v3
spiceprefix=X
}
C {symbols/nfet_03v3.sym} 850 -240 0 0 {name=M12
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
model=nfet_03v3
spiceprefix=X
}
C {symbols/nfet_03v3.sym} 640 -140 0 0 {name=M13
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
model=nfet_03v3
spiceprefix=X
}
C {symbols/nfet_03v3.sym} 680 -360 0 1 {name=M14
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
model=nfet_03v3
spiceprefix=X
}
C {symbols/pfet_03v3.sym} 360 -740 0 0 {name=M16
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
C {symbols/pfet_03v3.sym} 150 -740 0 0 {name=M18
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
C {ipin.sym} 320 -740 0 0 {name=p1 lab=v_in
}
C {ipin.sym} 170 -790 1 0 {name=p2 lab=vdd}
C {ipin.sym} 520 -70 3 0 {name=p3 lab=vss
}
C {ipin.sym} 110 -740 0 0 {name=p4 lab=v_aux
}
C {iopin.sym} 660 -460 3 0 {name=p5 lab=v_out}

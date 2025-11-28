v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 360 -650 360 -630 {
lab=IREF}
N 310 -650 360 -650 {lab=IREF}
N 360 -310 360 -240 {lab=VSS}
N 360 -410 420 -410 {lab=#net1}
N 420 -410 420 -340 {lab=#net1}
N 330 -340 360 -340 {lab=VSS}
N 330 -340 330 -240 {lab=VSS}
N 360 -630 360 -540 {lab=IREF}
N 360 -480 360 -370 {lab=#net1}
N 280 -240 360 -240 {lab=VSS}
N 400 -340 500 -340 {lab=#net1}
N 560 -310 560 -240 {lab=VSS}
N 560 -340 580 -340 {lab=VSS}
N 580 -340 590 -340 {lab=VSS}
N 590 -340 590 -250 {lab=VSS}
N 590 -250 590 -240 {lab=VSS}
N 560 -440 560 -370 {lab=#net2}
N 500 -340 520 -340 {lab=#net1}
N 560 -610 660 -610 {lab=IOUT}
N 560 -610 560 -590 {lab=IOUT}
N 560 -530 560 -440 {lab=#net2}
N 360 -240 590 -240 {lab=VSS}
N 310 -680 660 -680 {lab=VDD}
C {ipin.sym} 310 -680 0 0 {name=p9 lab=VDD
}
C {ipin.sym} 280 -240 0 0 {name=p10 lab=VSS
}
C {ipin.sym} 310 -650 0 0 {name=p12 lab=IREF
}
C {devices/ammeter.sym} 360 -510 0 0 {name=Virefin savecurrent=true}
C {symbols/nfet_05v0.sym} 380 -340 0 1 {name=MREF
L=1u
W=11u
nf=1
m=1
ad="'int((nf+1)/2) * W/nf * 0.18u'"
pd="'2*int((nf+1)/2) * (W/nf + 0.18u)'"
as="'int((nf+2)/2) * W/nf * 0.18u'"
ps="'2*int((nf+2)/2) * (W/nf + 0.18u)'"
nrd="'0.18u / W'" nrs="'0.18u / W'"
sa=0 sb=0 sd=0
model=nfet_05v0
spiceprefix=X
}
C {symbols/nfet_05v0.sym} 540 -340 0 0 {name=MOUT
L=1u
W=11u
nf=1
m=1
ad="'int((nf+1)/2) * W/nf * 0.18u'"
pd="'2*int((nf+1)/2) * (W/nf + 0.18u)'"
as="'int((nf+2)/2) * W/nf * 0.18u'"
ps="'2*int((nf+2)/2) * (W/nf + 0.18u)'"
nrd="'0.18u / W'" nrs="'0.18u / W'"
sa=0 sb=0 sd=0
model=nfet_05v0
spiceprefix=X
}
C {devices/ammeter.sym} 560 -560 0 0 {name=Vi2 savecurrent=true}
C {opin.sym} 660 -610 0 0 {name=p6 lab=IOUT}

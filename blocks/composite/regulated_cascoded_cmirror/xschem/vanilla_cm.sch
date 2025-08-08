v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 300 -50 300 -30 {lab=vss}
N 300 -120 340 -120 {lab=vss}
N 340 -120 340 -70 {lab=vss}
N 300 -70 340 -70 {lab=vss}
N 220 -120 260 -120 {lab=#net1}
N 160 -170 160 -150 {lab=#net1}
N 160 -170 220 -170 {lab=#net1}
N 220 -170 220 -120 {lab=#net1}
N 160 -370 160 -350 {lab=vdd}
N 160 -290 160 -170 {lab=#net1}
N 160 -80 160 -30 {lab=vss}
N 100 -120 160 -120 {lab=vss}
N 100 -120 100 -80 {lab=vss}
N 100 -80 160 -80 {lab=vss}
N 300 -240 300 -150 {lab=vout}
N 300 -90 300 -70 {lab=vss}
N 200 -120 220 -120 {lab=#net1}
N 160 -90 160 -80 {lab=vss}
N 300 -70 300 -50 {lab=vss}
N 160 -30 300 -30 {lab=vss}
N 300 -270 300 -240 {lab=vout}
N 160 -320 180 -320 {lab=vdd}
N 180 -360 180 -320 {lab=vdd}
N 160 -360 180 -360 {lab=vdd}
N 100 -320 120 -320 {lab=v_in}
C {symbols/nfet_03v3.sym} 280 -120 0 0 {name=M1
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
model=nfet_03v3
spiceprefix=X
}
C {symbols/nfet_03v3.sym} 180 -120 0 1 {name=M2
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
model=nfet_03v3
spiceprefix=X
}
C {symbols/pfet_03v3.sym} 140 -320 0 0 {name=M9
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
C {ipin.sym} 100 -320 0 0 {name=p1 lab=v_in
}
C {ipin.sym} 160 -370 1 0 {name=p2 lab=vdd}
C {ipin.sym} 250 -30 3 0 {name=p3 lab=vss
}
C {iopin.sym} 300 -260 3 0 {name=p4 lab=v_out}

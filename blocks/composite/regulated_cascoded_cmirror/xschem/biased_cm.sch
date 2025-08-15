v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 320 -60 320 -40 {lab=vss}
N 320 -130 360 -130 {lab=vss}
N 360 -130 360 -80 {lab=vss}
N 320 -80 360 -80 {lab=vss}
N 240 -130 280 -130 {lab=#net1}
N 180 -180 180 -160 {lab=#net1}
N 180 -180 240 -180 {lab=#net1}
N 240 -180 240 -130 {lab=#net1}
N 180 -300 180 -180 {lab=#net1}
N 180 -90 180 -40 {lab=vss}
N 120 -130 180 -130 {lab=vss}
N 120 -130 120 -90 {lab=vss}
N 120 -90 180 -90 {lab=vss}
N 320 -250 320 -160 {lab=#net2}
N 320 -100 320 -80 {lab=vss}
N 220 -130 240 -130 {lab=#net1}
N 180 -100 180 -90 {lab=vss}
N 320 -80 320 -60 {lab=vss}
N 180 -40 320 -40 {lab=vss}
N 320 -280 320 -250 {lab=#net2}
N 320 -370 360 -370 {lab=vss}
N 360 -370 360 -320 {lab=vss}
N 240 -370 280 -370 {lab=#net3}
N 180 -420 180 -400 {lab=#net3}
N 180 -420 240 -420 {lab=#net3}
N 240 -420 240 -370 {lab=#net3}
N 120 -370 180 -370 {lab=vss}
N 120 -370 120 -330 {lab=vss}
N 320 -340 320 -320 {lab=#net2}
N 220 -370 240 -370 {lab=#net3}
N 180 -340 180 -330 {lab=#net1}
N 180 -430 180 -420 {lab=#net3}
N 180 -330 180 -300 {lab=#net1}
N 320 -320 320 -280 {lab=#net2}
N 320 -430 320 -400 {lab=v_out}
N 180 -510 180 -490 {lab=vdd}
N 180 -460 200 -460 {lab=vdd}
N 200 -500 200 -460 {lab=vdd}
N 180 -500 200 -500 {lab=vdd}
N 120 -460 140 -460 {lab=v_in}
N 360 -320 360 -130 {lab=vss}
N 120 -330 120 -130 {lab=vss}
C {symbols/nfet_03v3.sym} 300 -130 0 0 {name=M3
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
C {symbols/nfet_03v3.sym} 200 -130 0 1 {name=M4
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
C {symbols/nfet_03v3.sym} 300 -370 0 0 {name=M5
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
C {symbols/nfet_03v3.sym} 200 -370 0 1 {name=M6
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
C {symbols/pfet_03v3.sym} 160 -460 0 0 {name=M15
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
C {ipin.sym} 120 -460 0 0 {name=p1 lab=v_in
}
C {ipin.sym} 180 -510 1 0 {name=p2 lab=vdd}
C {ipin.sym} 270 -40 3 0 {name=p3 lab=vss
}
C {iopin.sym} 320 -430 3 0 {name=p4 lab=v_out}

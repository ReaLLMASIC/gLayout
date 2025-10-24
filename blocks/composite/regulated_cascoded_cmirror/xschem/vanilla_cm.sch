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
N 220 -120 260 -120 {lab=v_in}
N 160 -170 160 -150 {lab=v_in}
N 160 -170 220 -170 {lab=v_in}
N 220 -170 220 -120 {lab=v_in}
N 160 -290 160 -170 {lab=v_in}
N 160 -80 160 -30 {lab=vss}
N 100 -120 160 -120 {lab=vss}
N 100 -120 100 -80 {lab=vss}
N 100 -80 160 -80 {lab=vss}
N 300 -240 300 -150 {lab=v_out}
N 300 -90 300 -70 {lab=vss}
N 200 -120 220 -120 {lab=v_in}
N 160 -90 160 -80 {lab=vss}
N 300 -70 300 -50 {lab=vss}
N 160 -30 300 -30 {lab=vss}
N 300 -270 300 -240 {lab=v_out}
N 110 -290 130 -290 {lab=v_in}
N 130 -290 160 -290 {lab=v_in}
N 60 -30 160 -30 {lab=vss}
N 300 -290 320 -290 {lab=v_out}
N 300 -290 300 -270 {lab=v_out}
N 440 -90 440 -30 {lab=vss}
N 300 -30 440 -30 {lab=vss}
N 400 -120 400 -30 {lab=vss}
N 440 -150 470 -150 {lab=vss}
N 470 -150 470 -30 {lab=vss}
N 440 -30 470 -30 {lab=vss}
N 440 -120 470 -120 {lab=vss}
C {symbols/nfet_03v3.sym} 280 -120 0 0 {name=M1
L=1u
W=4u
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
L=1u
W=4u
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
C {ipin.sym} 110 -290 0 0 {name=p1 lab=v_in
}
C {iopin.sym} 60 -30 2 0 {name=p3 lab=vss
}
C {opin.sym} 320 -290 0 0 {name=p4 lab=v_out}
C {symbols/nfet_03v3.sym} 420 -120 0 0 {name=M3
L=1u
W=4u
nf=1
m=2
ad="'int((nf+1)/2) * W/nf * 0.18u'"
pd="'2*int((nf+1)/2) * (W/nf + 0.18u)'"
as="'int((nf+2)/2) * W/nf * 0.18u'"
ps="'2*int((nf+2)/2) * (W/nf + 0.18u)'"
nrd="'0.18u / W'" nrs="'0.18u / W'"
sa=0 sb=0 sd=0
model=nfet_03v3
spiceprefix=X
}

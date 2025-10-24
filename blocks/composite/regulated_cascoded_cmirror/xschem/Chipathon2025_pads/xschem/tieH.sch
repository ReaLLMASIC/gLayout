v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N -40 30 -40 80 {lab=#net1}
N -40 30 0 30 {lab=#net1}
N 0 30 0 50 {lab=#net1}
N 0 -50 0 30 {lab=#net1}
N 40 -20 40 10 {lab=TIEH}
N 40 10 100 10 {lab=TIEH}
N 40 -110 40 -80 {lab=VDD}
N 40 -50 50 -50 {lab=VDD}
N 50 -110 50 -50 {lab=VDD}
N 40 -110 50 -110 {lab=VDD}
N 0 80 10 80 {lab=VSS}
N 10 80 10 130 {lab=VSS}
N 0 130 10 130 {lab=VSS}
N 0 110 0 130 {lab=VSS}
C {symbols/pfet_05v0.sym} 20 -50 0 0 {name=M1
L=0.55u
W=2u
nf=1
m=1
ad="'int((nf+1)/2) * W/nf * 0.18u'"
pd="'2*int((nf+1)/2) * (W/nf + 0.18u)'"
as="'int((nf+2)/2) * W/nf * 0.18u'"
ps="'2*int((nf+2)/2) * (W/nf + 0.18u)'"
nrd="'0.18u / W'" nrs="'0.18u / W'"
sa=0 sb=0 sd=0
model=pfet_05v0
spiceprefix=X
}
C {symbols/nfet_05v0.sym} -20 80 0 0 {name=M2
L=0.70u
W=1u
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
C {iopin.sym} 0 130 2 0 {name=p1 lab=VSS}
C {iopin.sym} 50 -110 0 0 {name=p2 lab=VDD}
C {iopin.sym} 100 10 0 0 {name=p3 lab=TIEH}

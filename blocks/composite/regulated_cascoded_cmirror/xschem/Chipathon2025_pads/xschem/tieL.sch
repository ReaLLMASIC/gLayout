v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 0 30 0 80 {lab=#net1}
N 40 30 40 50 {lab=TIEL}
N -40 -60 -40 -10 {lab=#net1}
N 40 30 100 30 {lab=TIEL}
N 0 -120 0 -90 {lab=VDD}
N 0 -60 10 -60 {lab=VDD}
N 10 -120 10 -60 {lab=VDD}
N 0 -120 10 -120 {lab=VDD}
N 40 80 50 80 {lab=VSS}
N 50 80 50 130 {lab=VSS}
N 40 130 50 130 {lab=VSS}
N 40 110 40 130 {lab=VSS}
N 0 -30 0 30 {lab=#net1}
N -40 -10 0 -10 {lab=#net1}
C {symbols/pfet_05v0.sym} -20 -60 0 0 {name=M3
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
C {symbols/nfet_05v0.sym} 20 80 0 0 {name=M4
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
C {iopin.sym} 40 130 2 0 {name=p4 lab=VSS}
C {iopin.sym} 10 -120 0 0 {name=p5 lab=VDD}
C {iopin.sym} 100 30 0 0 {name=p6 lab=TIEL}

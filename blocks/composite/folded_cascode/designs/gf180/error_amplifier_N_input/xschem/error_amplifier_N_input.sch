v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 0 80 50 80 {
lab=VbiasP2}
N 0 100 50 100 {
lab=VbiasN2}
N 0 120 50 120 {
lab=VbiasN1}
N 50 120 100 120 {lab=VbiasN1}
N 50 100 100 100 {lab=VbiasN2}
N 50 80 100 80 {lab=VbiasP2}
N 0 60 20 60 {lab=#net1}
C {devices/lab_wire.sym} -240 90 0 0 {name=p12 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} -240 70 0 0 {name=p3 sig_type=std_logic lab=Vref}
C {devices/lab_wire.sym} -240 110 0 0 {name=p5 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 50 -100 0 0 {name=p6 sig_type=std_logic lab=V-}
C {devices/lab_wire.sym} 50 -40 0 0 {name=p7 sig_type=std_logic lab=V+}
C {devices/lab_wire.sym} 250 -70 0 1 {name=p8 sig_type=std_logic lab=Vout}
C {devices/lab_wire.sym} 100 20 0 0 {name=p4 sig_type=std_logic lab=VDD}
C {devices/lab_wire.sym} 100 40 0 0 {name=p1 sig_type=std_logic lab=VSS}
C {devices/lab_wire.sym} 100 60 0 0 {name=p2 sig_type=std_logic lab=Vcomn}
C {devices/ipin.sym} 400 -130 0 0 {name=p14 lab=V+}
C {devices/iopin.sym} 380 50 0 0 {name=p18 lab=Vout}
C {devices/ipin.sym} 400 -100 0 0 {name=p19 lab=V-}
C {devices/ipin.sym} 400 -70 0 0 {name=p9 lab=Vref}
C {devices/iopin.sym} 380 -40 0 0 {name=p15 lab=VDD}
C {devices/iopin.sym} 380 -10 0 0 {name=p10 lab=VSS}
C {devices/iopin.sym} 380 20 0 0 {name=p11 lab=Vcomn}
C {error_amplifier_core_N_input.sym} 150 -70 0 0 {name=x1}
C {error_amplifier_bias_N_input.sym} -120 90 0 0 {name=x2}
C {noconn.sym} 20 60 2 0 {name=l1}
C {devices/lab_wire.sym} 80 80 0 0 {name=p13 sig_type=std_logic lab=VbiasP2}
C {devices/lab_wire.sym} 80 100 0 0 {name=p16 sig_type=std_logic lab=VbiasN2}
C {devices/lab_wire.sym} 80 120 0 0 {name=p17 sig_type=std_logic lab=VbiasN1}

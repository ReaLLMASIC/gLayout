v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 80 -450 340 -450 {lab=V_IN_BCM}
N 180 -720 340 -720 {lab=V_IN_VCM}
N 180 -140 340 -140 {lab=V_IN_CCM}
N 290 -800 290 -190 {lab=VDD}
N 290 -160 340 -160 {lab=VDD}
N 290 -470 340 -470 {lab=VDD}
N 290 -740 340 -740 {lab=VDD}
N 310 -700 310 -60 {lab=VSS}
N 310 -700 340 -700 {lab=VSS}
N 310 -430 340 -430 {lab=VSS}
N 310 -120 340 -120 {lab=VSS}
N 290 -190 290 -160 {lab=VDD}
N 80 -140 180 -140 {lab=V_IN_CCM}
N 80 -720 180 -720 {lab=V_IN_VCM}
C {vanilla_cm.sym} 300 -570 0 0 {name=x1}
C {biased_cm.sym} 320 -230 0 0 {name=x2}
C {cascode_cm.sym} 310 120 0 0 {name=x3}
C {ipin.sym} 310 -60 3 0 {name=p1 lab=VSS
}
C {ipin.sym} 80 -450 0 0 {name=p2 lab=V_IN_BCM
}
C {ipin.sym} 490 -230 1 0 {name=p3 lab=V_AUX_CCM
}
C {ipin.sym} 290 -800 1 0 {name=p4 lab=VDD
}
C {iopin.sym} 640 -740 0 0 {name=p5 lab=V_OUT_VCM}
C {iopin.sym} 640 -470 0 0 {name=p6 lab=V_OUT_BCM}
C {iopin.sym} 640 -160 0 0 {name=p7 lab=V_OUT_CCM}
C {ipin.sym} 80 -140 0 0 {name=p8 lab=V_IN_CCM
}
C {ipin.sym} 80 -720 0 0 {name=p9 lab=V_IN_VCM
}

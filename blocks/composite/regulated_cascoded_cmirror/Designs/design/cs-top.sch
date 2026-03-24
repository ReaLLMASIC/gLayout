v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 570 -990 700 -990 {lab=VSS}
N 570 -990 570 -400 {lab=VSS}
N 340 -400 570 -400 {lab=VSS}
N 570 -760 700 -760 {lab=VSS}
N 570 -520 700 -520 {lab=VSS}
N 570 -1030 700 -1030 {lab=VDD}
N 550 -800 700 -800 {lab=VDD}
N 540 -560 700 -560 {lab=VDD}
N 540 -1140 540 -560 {lab=VDD}
N 540 -800 550 -800 {lab=VDD}
N 540 -1030 570 -1030 {lab=VDD}
N 340 -1140 540 -1140 {lab=VDD}
N 340 -1010 700 -1010 {lab=IREF_VM_1}
N 340 -780 700 -780 {lab=IREF_CM_1}
N 340 -540 700 -540 {lab=IREF_RCM_1}
N 1000 -1030 1560 -1030 {lab=IOUT_VM_1}
N 1000 -800 1550 -800 {lab=IOUT_CM_1}
N 1000 -560 1550 -560 {lab=IOUT_RCM_1}
C {ipin.sym} 340 -1140 0 0 {name=p1 lab=VDD}
C {ipin.sym} 340 -400 0 0 {name=p2 lab=VSS}
C {ipin.sym} 340 -1010 0 0 {name=p3 lab=IREF_VM_1}
C {ipin.sym} 340 -780 0 0 {name=p4 lab=IREF_CM_1}
C {ipin.sym} 340 -540 0 0 {name=p5 lab=IREF_RCM_1}
C {iopin.sym} 1560 -1030 0 0 {name=p6 lab=IOUT_VM_1}
C {iopin.sym} 1550 -800 0 0 {name=p7 lab=IOUT_CM_1}
C {iopin.sym} 1550 -560 0 0 {name=p8 lab=IOUT_RCM_1}
C {cs-regulated-cascoded_5V.sym} 620 -410 0 0 {name=x3}
C {cs-vanilla-cm.sym} 620 -880 0 0 {name=x2}
C {cs-cascoded-cm.sym} 620 -650 0 0 {name=x1}

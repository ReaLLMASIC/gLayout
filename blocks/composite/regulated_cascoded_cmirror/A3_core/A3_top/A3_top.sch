v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 250 -370 580 -370 {lab=ENA}
N 820 -180 820 -170 {lab=VSS}
N 820 -430 820 -400 {lab=VDD}
N 340 -330 580 -330 {lab=VIN_INT}
N 460 -280 580 -280 {lab=VBIAS_INT}
N 400 -570 400 -530 {lab=VSS}
N 400 -710 400 -690 {lab=VDD}
N 820 -170 820 -150 {lab=VSS}
N 760 -850 920 -850 {lab=VIN}
N 750 -600 910 -600 {lab=VBIAS}
N 1020 -350 1110 -350 {lab=VCM_OUT}
N 1110 -370 1110 -350 {lab=VCM_OUT}
N 1110 -370 1180 -370 {lab=VCM_OUT}
N 1020 -330 1180 -330 {lab=BCM_OUT}
N 1020 -310 1110 -310 {lab=CCM_OUT}
N 1110 -310 1110 -290 {lab=CCM_OUT}
N 1110 -290 1180 -290 {lab=CCM_OUT}
N 630 -730 710 -730 {lab=VDD}
N 620 -680 710 -680 {lab=VSS}
N 490 -840 520 -840 {lab=ENA}
N 1020 -370 1090 -370 {lab=VIN_OUT}
N 1090 -400 1090 -370 {lab=VIN_OUT}
N 1090 -400 1180 -400 {lab=VIN_OUT}
N 920 -850 960 -850 {lab=VIN}
N 910 -600 960 -600 {lab=VBIAS}
N 1160 -850 1200 -850 {lab=VIN_INT}
N 1160 -600 1270 -600 {lab=VBIAS_INT}
N 80 -840 290 -840 {lab=EN}
N 80 -610 320 -610 {lab=PU}
N 80 -650 320 -650 {lab=PD}
C {title.sym} 190 -90 0 0 {name=l1 author="Quentin Halbach and Sapta"}
C {lab_pin.sym} 400 -710 2 1 {name=p111 lab=VDD}
C {lab_pin.sym} 410 -760 2 1 {name=p164 lab=VSS}
C {iopin.sym} 710 -730 0 0 {name=p92 lab=VDD}
C {iopin.sym} 710 -680 0 0 {name=p51 lab=VSS}
C {lab_pin.sym} 520 -840 0 1 {name=p1 lab=ENA}
C {lab_pin.sym} 400 -530 2 1 {name=p2 lab=VSS}
C {lab_pin.sym} 820 -430 2 1 {name=p3 lab=VDD}
C {lab_pin.sym} 820 -150 2 1 {name=p4 lab=VSS}
C {lab_pin.sym} 250 -370 2 1 {name=p5 lab=ENA}
C {ipin.sym} 760 -850 0 0 {name=p6 lab=VIN}
C {ipin.sym} 750 -600 0 0 {name=p7 lab=VBIAS}
C {lab_pin.sym} 1200 -850 0 1 {name=p8 lab=VIN_INT}
C {lab_pin.sym} 1270 -600 0 1 {name=p9 lab=VBIAS_INT}
C {lab_pin.sym} 340 -330 2 1 {name=p10 lab=VIN_INT}
C {lab_pin.sym} 460 -280 2 1 {name=p11 lab=VBIAS_INT}
C {opin.sym} 1180 -370 0 0 {name=p24 lab=VCM_OUT}
C {opin.sym} 1180 -330 0 0 {name=p20 lab=BCM_OUT}
C {opin.sym} 1180 -290 0 0 {name=p28 lab=CCM_OUT}
C {lab_pin.sym} 630 -730 2 1 {name=p41 lab=VDD}
C {lab_pin.sym} 620 -680 2 1 {name=p43 lab=VSS}
C {lab_pin.sym} 410 -920 2 1 {name=p49 lab=VDD}
C {opin.sym} 1180 -400 0 0 {name=p54 lab=VIN_OUT}
C {lab_pin.sym} 1080 -930 2 1 {name=p12 lab=VDD}
C {lab_pin.sym} 1080 -770 2 1 {name=p13 lab=VSS}
C {lab_pin.sym} 1080 -680 2 1 {name=p14 lab=VDD}
C {lab_pin.sym} 1080 -520 2 1 {name=p15 lab=VSS}
C {ipin.sym} 80 -610 0 0 {name=p16 lab=PU}
C {ipin.sym} 80 -650 0 0 {name=p17 lab=PD}
C {ipin.sym} 80 -840 0 0 {name=p120 lab=EN}
C {/foss/designs/AutoMOS-chipathon2025/designs/Chipathon2025_pads/xschem/symbols/io_secondary_5p0/io_secondary_5p0.sym} 490 -760 0 1 {name=IO1
spiceprefix=X
}
C {/foss/designs/AutoMOS-chipathon2025/designs/Chipathon2025_pads/xschem/symbols/io_secondary_5p0/io_secondary_5p0.sym} 1160 -770 0 1 {name=IO2
spiceprefix=X
}
C {/foss/designs/AutoMOS-chipathon2025/designs/Chipathon2025_pads/xschem/symbols/io_secondary_5p0/io_secondary_5p0.sym} 1160 -520 0 1 {name=IO3
spiceprefix=X
}
C {/foss/designs/AutoMOS-chipathon2025/designs/gf180mcu_fd_sc_mcu9t5v0/xschem/symbols/sc_tieh_tiel.sym} 440 -570 0 1 {name=SC1
spiceprefix=X
}
C {top_level/top_level.sym} 820 -290 0 0 {name=x1}

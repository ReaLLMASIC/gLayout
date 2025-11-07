# Chopper Switch Cell

GenYZ Team: Oct 17 2025

## Schematic
<img width="432" height="534" alt="Image" src="https://github.com/user-attachments/assets/60f1f9d9-25af-4356-b1e5-da82c20bae29" />

This circuit is a differential chopper switch. It alternates the signal polarity between the differential inputs (IN+, IN-) and outputs (OUT+, OUT-). This implementation is constructed using pre-designed tgswitch components as the core switching elements. The opposing control signals, CLK and CLKB, determine which tgswitch path is active, selecting either a straight-through or a crossover connection.

## Parametrizing the Chopper Switch Block
```
def cswitch(
        pdk: MappedPDK,
        width: tuple[float,float] = (10,10),
        length: tuple[float,float] = (0.5,0.5),
        fingers: tuple[int,int] = (6,6),
        multipliers: tuple[int,int] = (1,1),
        dummy_1: tuple[bool,bool] = (True,True),
        dummy_2: tuple[bool,bool] = (True,True),
        tie_layers1: tuple[str,str] = ("met2","met1"),
        tie_layers2: tuple[str,str] = ("met2","met1"),
        sd_rmult: int=1,
        **kwargs
        ) -> Component:
    """
    creates a Chopper Switch
    pdk: pdk to use
    width: (pfet, nfet)
    length: (pfet, nfet)
    fingers: (pfet, nfet)
    multipliers: (pfet, nfet)
    dummy_1: dummy for pfet
    dummy_2: dummy for nfet
    tie_layers1: tie layers for pfet
    tie_layers2: tie layers for nfet
    sd_rmult: sd_rmult for both fets
    **kwargs: any kwarg that is supported by nmos and pmos
```

### GDS generated
<img width="389" height="497" alt="Image" src="https://github.com/user-attachments/assets/37e56806-cb81-4b77-a27a-7d2d7c746779" />

### DRC Report
```
using default pdk_root
Defaulting to stale magic_commands.tcl

Magic 8.3 revision 528 - Compiled on Wed Jun 18 09:45:25 PM CEST 2025.
Starting magic under Tcl interpreter
Using the terminal as the console.
WARNING: RLIMIT_NOFILE is above 1024 and Tcl_Version<9 this may cause runtime issues [rlim_cur=1048576]
Using NULL graphics device.
Processing system .magicrc file
Sourcing design .magicrc for technology gf180mcuD ...
10 Magic internal units = 1 Lambda
Input style import: scaleFactor=10, multiplier=2
The following types are not handled by extraction and will be treated as non-electrical types:
    obsactive mvobsactive filldiff fillpoly m1hole obsm1 fillm1 obsv1 m2hole obsm2 fillm2 obsv2 m3hole obsm3 fillm3 m4hole obsm4 fillm4 m5hole obsm5 fillm5 glass fillblock lvstext obscomment 
Scaled tech values by 10 / 1 to match internal grid scaling
Loading gf180mcuD Device Generator Menu ...
Loading "/tmp/tmpsvvb6hl4/magic_commands.tcl" from command line.
Warning: Calma reading is not undoable!  I hope that's OK.
Library written using GDS-II Release 6.0
Library name: library
Reading "cswitch$3".
[INFO]: Loading cswitch$3

Loading DRC CIF style.
No errors found.
[INFO]: DONE with /tmp/tmpsvvb6hl4/cswitch$3.rpt

Using technology "gf180mcuD", version 1.0.525-0-gf2e289d
```

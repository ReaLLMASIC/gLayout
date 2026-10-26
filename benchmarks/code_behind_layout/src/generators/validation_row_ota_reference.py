"""Independent validation-only 5T intent, with an externally biased tail gate."""
PORTS = ['VDD','GND','VBIAS','VP','VN','VOUT']
DEFAULT = {'input_width':3.,'input_length':1.,'input_fingers':2,
           'load_width':3.,'load_length':1.,'load_fingers':4,
           'tail_width':3.,'tail_length':1.,'tail_fingers':4}


def schematic(sizing=None):
    z = {**DEFAULT, **(sizing or {})}
    lines = ['* Validation-only canonical differential pair, mirror load and biased sink',
             '.subckt validation_row_ota ' + ' '.join(PORTS)]
    # This fixed electrical specification is independent of the layout net table.
    for name,kind,nodes,group in [
        ('INP','nfet','MIRROR VP TAIL GND','input'),
        ('INM','nfet','VOUT VN TAIL GND','input'),
        ('DIODE','pfet','MIRROR MIRROR VDD VDD','load'),
        ('LOAD','pfet','VOUT MIRROR VDD VDD','load'),
        ('SINK','nfet','TAIL VBIAS GND GND','tail')]:
        lines.append('X%s %s sky130_fd_pr__%s_01v8 w=%g l=%g m=%d' %
                     (name,nodes,kind,z[group+'_width'],z[group+'_length'],z[group+'_fingers']))
    return '\n'.join(lines+['.ends validation_row_ota',''])

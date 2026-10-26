"""Measured mirror metrics on a complete trusted DC sweep."""
import math
from pathlib import Path


def mirror_dc_metrics(path,reference_current=20e-6,nominal_voltage=.9,tolerance=.05):
    rows=[]
    for line in Path(path).read_text().splitlines()[1:]:
        if line.strip():rows.append(list(map(float,line.split())))
    if len(rows)!=19 or any(len(row)!=3 or not all(map(math.isfinite,row)) for row in rows):
        raise ValueError('Expected complete finite 19-row mirror DC table')
    if any(abs(row[0]-.1*i)>1e-7 or abs(row[1]-row[0])>1e-7 for i,row in enumerate(rows)):
        raise ValueError('Mirror DC voltage axis differs from the declared 0..1.8 by .1 sweep')
    index=next(i for i,row in enumerate(rows) if abs(row[0]-nominal_voltage)<1e-7)
    currents=[-row[2] for row in rows]
    errors=[abs(current/reference_current-1) for current in currents]
    conductance=(currents[index+1]-currents[index-1])/(rows[index+1][0]-rows[index-1][0])
    if conductance==0:raise ValueError('Output resistance is not finite at declared central difference')
    lower=upper=None
    if errors[index]<=tolerance:
        left=right=index
        while left>0 and errors[left-1]<=tolerance:left-=1
        while right+1<len(rows) and errors[right+1]<=tolerance:right+=1
        lower,upper=rows[left][0],rows[right][0]
    return {'nominal_current_A':currents[index], 'nominal_current_relative_error':errors[index],
       'output_resistance_ohm':1/conductance,'output_resistance_difference_interval_V':[rows[index-1][0],rows[index+1][0]],
       'compliance_5pct_lower_V':lower,'compliance_5pct_upper_V':upper,
       'compliance_5pct_span_V':upper-lower if lower is not None else 0,
       'compliance_definition':'maximal contiguous sampled 5% error component containing 0.9 V; no interpolation/continuous guarantee',
       'dc_sweep_max_relative_error':max(errors),
       'dc_sweep_relative_errors':[{'voltage_V':row[0],'current_A':current,'relative_error':error} for row,current,error in zip(rows,currents,errors)]}


def frequency_3db(path):
    rows=[[float(v) for v in line.split()] for line in Path(path).read_text().splitlines()[1:] if line.strip()]
    if any(len(row)!=3 or not all(map(math.isfinite,row)) for row in rows):raise ValueError('Invalid AC table')
    db=[20*math.log10(math.hypot(row[1],row[2])) for row in rows]
    target=db[0]-3
    for i in range(1,len(rows)):
        if db[i-1]>=target and db[i]<target:
            fraction=(target-db[i-1])/(db[i]-db[i-1])
            return math.exp(math.log(rows[i-1][0])+fraction*math.log(rows[i][0]/rows[i-1][0]))
    raise ValueError('Complete sweep has no descending 3dB crossing')

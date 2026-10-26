"""Visible-configuration selection for the controlled A/R/B/C comparison.

C consumes normalized signals declared outside evaluation; this module does not
load outcomes, fit to hidden points or silently invent missing predictions.
Their frozen artifact distinguishes actual probabilistic predictions from a
transparent heuristic when available data cannot calibrate a failure model.
"""
import math
import random


class RegressionSelector:
    def __init__(self,method,visible_features,feature_bounds,seed,weights=None):
        if method not in ("A","R","B","C"):raise ValueError("Unknown controlled method")
        if not visible_features:raise ValueError("Visible development pool is empty")
        self.method=method;self.features=visible_features;self.bounds=feature_bounds
        self.random=random.Random(seed);self.weights=weights
        for values in visible_features.values():
            if set(values)!=set(feature_bounds):raise ValueError("Features differ from frozen numeric schema")
            for key,value in values.items():
                low,high=feature_bounds[key]
                if not math.isfinite(value) or not low<high or not low<=value<=high:
                    raise ValueError("Feature exceeds its declared visible domain")
        if method=="C" and (not weights or set(weights)!={"failure_probability","uncertainty","changed_call_coverage","low_margin"}
                or any(not math.isfinite(x) or x<0 for x in weights.values()) or sum(weights.values())==0):
            raise ValueError("C requires nonnegative explicitly frozen weights")

    def vector(self,name):
        return [(self.features[name][key]-low)/(high-low) for key,(low,high) in self.bounds.items()]

    def choose(self,tested_ids,predictions=None):
        if not set(tested_ids)<=set(self.features):raise ValueError("Tested ID outside visible pool")
        remaining=sorted(set(self.features)-set(tested_ids))
        if self.method=="A" or not remaining:return None
        if self.method=="R":return self.random.choice(remaining)
        if self.method=="B":
            # Boundary-first maximin coverage, independent of electrical oracle.
            def priority(name):
                v=self.vector(name)
                boundary=min(min(x,1-x) for x in v)
                distance=min((sum((a-b)**2 for a,b in zip(v,self.vector(old))) for old in tested_ids),default=0)
                return (-boundary,distance)
            return max(remaining,key=priority)
        if predictions is None or any(name not in predictions for name in remaining):
            raise ValueError("C needs current-patch predictions for every untested visible point")
        scores={}
        for name in remaining:
            row=predictions[name]
            if set(row)!=set(self.weights) or any(not math.isfinite(x) or not 0<=x<=1 for x in row.values()):
                raise ValueError("C inputs must be declared normalized signals, not hidden measurements")
            scores[name]=sum(self.weights[key]*row[key] for key in self.weights)
        return max(remaining,key=lambda name:scores[name])

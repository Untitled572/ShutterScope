# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572

"""Streaming optical-step extraction, independent of the signal's DC level.

A causal median of three rejects single-sample spikes. A short rolling range
finds significant local changes; each change is timed at half of its own local
step height. The extractor does not interpret a slow return to zero as closure.
The caller pairs opposite transitions and rejects slow recovery relative to the
opening edge. Filter timing is referred to the middle sample, not callback time.
"""
from array import array
from collections import deque
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class Transition:
    time: float
    direction: int
    strength: float
    level: float
    peak: float
    clipped: bool
    amplitude: float

class TransitionTracker:
    def __init__(self, config):
        self.c = config
        self.window = max(8, round((config.maximum_edge_ms+1)*config.rate/1000))
        self.lookahead = max(config.confirm_samples, round(config.maximum_edge_ms*config.rate/1000))
        self.prefix = deque(maxlen=self.window)
        self.low = deque()
        self.high = deque()
        self.inputs = deque(maxlen=3)
        self.candidate = None
        self.rejected = 0

    def reset(self):
        self.prefix.clear();self.low.clear();self.high.clear();self.inputs.clear()
        self.candidate = None

    def seed(self, index, value):
        self.prefix.append((index,value))
        while self.low and self.low[-1][1] >= value:self.low.pop()
        while self.high and self.high[-1][1] <= value:self.high.pop()
        self.low.append((index,value));self.high.append((index,value))
        oldest=self.prefix[0][0]
        while self.low and self.low[0][0] < oldest:self.low.popleft()
        while self.high and self.high[0][0] < oldest:self.high.popleft()

    def make_candidate(self, offset, trace, direction, reference, triggered):
        values=np.asarray(trace,dtype=np.float64)
        peak_at=int(np.argmax((values-reference)*direction))
        return dict(offset=offset,trace=array('f',values),direction=direction,reference=reference,
                    triggered=triggered,peak_at=peak_at,peak=float(values[peak_at]),reverse_count=0)

    def finish(self, candidate):
        c=self.c;direction=candidate['direction'];reference=candidate['reference']
        values=(np.asarray(candidate['trace'],dtype=np.float64)-reference)*direction
        peak_at=candidate['peak_at'];amplitude=direction*(candidate['peak']-reference)
        if amplitude < c.threshold or peak_at < 1:
            self.rejected += 1;return None
        def crossing(fraction, first, last, latest):
            level=amplitude*fraction
            matches=np.flatnonzero((values[first:last-1]<level)&(values[first+1:last]>=level))
            if latest:matches=matches[::-1]
            for match in matches:
                i=first+int(match);after=values[i+1:i+1+c.confirm_samples]
                if len(after)==c.confirm_samples and np.all(after>=level):
                    return i+float((level-values[i])/(values[i+1]-values[i]))
            return None
        mid=crossing(.5,0,peak_at+1,True)
        lo=crossing(.1,0,min(peak_at+1,int(mid)+2) if mid is not None else peak_at+1,True)
        hi=crossing(.9,max(0,int(mid)) if mid is not None else 0,peak_at+1,False)
        if None in (lo,mid,hi) or hi-lo>c.maximum_edge_ms*c.rate/1000:
            self.rejected += 1;return None
        strength=float(np.max(np.diff(values[max(0,int(lo)-1):min(len(values),int(hi)+3)])))*c.rate
        raw=np.asarray(candidate['trace'])
        return Transition(candidate['offset']+mid,direction,strength,reference+direction*amplitude*.5,
                          float(np.max(np.abs(raw))),bool(np.any(np.abs(raw)>=.999)),amplitude)

    def push(self, raw, index):
        self.inputs.append(float(raw))
        if len(self.inputs)<3:return []
        a,b,c=self.inputs
        value=a+b+c-min(a,b,c)-max(a,b,c)
        index-=1
        out=[]
        candidate=self.candidate
        if candidate is not None:
            candidate['trace'].append(value)
            direction=candidate['direction']
            if direction*(value-candidate['peak'])>0:
                candidate['peak']=value;candidate['peak_at']=len(candidate['trace'])-1
            reversed_by=direction*(candidate['peak']-value)
            candidate['reverse_count']=candidate['reverse_count']+1 if reversed_by>=self.c.threshold else 0
            if candidate['reverse_count']>=self.c.confirm_samples:
                edge=self.finish(candidate)
                if edge is None:
                    # A rejected one/two-sample spike must not turn its return
                    # into a convincing opposite edge or replace an open shutter.
                    self.candidate=None
                    self.prefix.clear();self.low.clear();self.high.clear();self.seed(index,value)
                    return out
                out.append(edge)
                peak_at=candidate['peak_at'];trace=candidate['trace'][peak_at:]
                self.candidate=self.make_candidate(candidate['offset']+peak_at,trace,-direction,
                                                   candidate['peak'],index)
                self.prefix.clear();self.low.clear();self.high.clear()
            elif index-candidate['triggered']>=self.lookahead:
                edge=self.finish(candidate)
                if edge is not None:out.append(edge)
                self.candidate=None
                self.prefix.clear();self.low.clear();self.high.clear();self.seed(index,value)
            return out
        self.seed(index,value)
        if len(self.prefix)<max(3,self.c.confirm_samples):return out
        down=self.high[0][1]-value;up=value-self.low[0][1]
        if max(down,up)<self.c.threshold:return out
        direction=-1 if down>=up else 1
        prefix=list(self.prefix)
        count=min(len(prefix)-1,max(self.c.confirm_samples,round(self.c.rate*.0002)))
        reference=float(np.median([v for _,v in prefix[:count]]))
        if (value-reference)*direction<self.c.threshold:return out
        self.candidate=self.make_candidate(prefix[0][0],[v for _,v in prefix],direction,reference,index)
        return out

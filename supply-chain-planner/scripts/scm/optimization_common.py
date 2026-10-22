"""Shared input validation, bounded solve configuration and atomic numeric output."""
import dataclasses
import json
import math
import os
import tempfile
import time
import warnings
from pathlib import Path
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

def numeric(value):
    if dataclasses.is_dataclass(value):return numeric(dataclasses.asdict(value))
    if isinstance(value,np.ndarray):return numeric(value.tolist())
    if isinstance(value,np.generic):return numeric(value.item())
    if isinstance(value,dict):return {str(numeric(k)):numeric(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [numeric(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite result cannot be saved')
    if value is None or isinstance(value,(str,bool,int,float)):return value
    raise ValueError('Unsupported result type: '+type(value).__name__)

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(numeric(value),ensure_ascii=False,indent=2,allow_nan=False)
    fd,name=tempfile.mkstemp(prefix='.result-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def array(value,shape=None,nonnegative=True):
    a=np.asarray(value,dtype=float)
    if shape is not None and a.shape!=shape:raise ValueError(f'Expected shape {shape}; got {a.shape}')
    if not np.all(np.isfinite(a)) or (nonnegative and np.any(a<0)):raise ValueError('Numeric data must be finite and nonnegative')
    return a

class Budget:
    def __init__(self,seconds):
        if not math.isfinite(seconds) or seconds<=0:raise ValueError('seconds must be positive and finite')
        self.start=time.monotonic();self.seconds=seconds;self.end=self.start+max(.01,seconds-.25)
    def remaining(self):return max(0.,self.end-time.monotonic())
    def elapsed(self):return time.monotonic()-self.start

def options(seconds,gap=1e-9):return {'time_limit':max(.001,seconds),'mip_rel_gap':gap,'threads':1}

class Model:
    def __init__(self):
        self.cost=[];self.lower=[];self.upper=[];self.integer=[];self.rows=[];self.cols=[];self.values=[];self.lo=[];self.hi=[]
    def var(self,shape,lower=0,upper=np.inf,integer=False,cost=0):
        n=int(np.prod(shape));idx=np.arange(len(self.cost),len(self.cost)+n).reshape(shape)
        for dst,value in [(self.cost,cost),(self.lower,lower),(self.upper,upper)]:dst.extend(np.broadcast_to(value,shape).ravel().tolist())
        self.integer.extend([int(integer)]*n);return idx
    def row(self,terms,lower=-np.inf,upper=np.inf):
        row=len(self.lo)
        for ids,coef in terms:
            ids=np.atleast_1d(ids).ravel();coef=np.broadcast_to(coef,ids.shape)
            self.rows.extend([row]*len(ids));self.cols.extend(ids.tolist());self.values.extend(coef.tolist())
        self.lo.append(lower);self.hi.append(upper)
    def solve(self,seconds):
        a=coo_matrix((self.values,(self.rows,self.cols)),shape=(len(self.lo),len(self.cost))).tocsc()
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore',message='Unrecognized options detected')
            result=milp(np.array(self.cost),integrality=self.integer,bounds=Bounds(self.lower,self.upper),constraints=LinearConstraint(a,self.lo,self.hi),options=options(seconds))
        return result

def evidence(result,maximize=False):
    out={'solver':'SciPy/HiGHS','threads':1,'solver_status':int(result.status),'message':result.message}
    for src,dst in [('mip_gap','solver_gap'),('mip_dual_bound','best_bound'),('mip_node_count','nodes')]:
        v=getattr(result,src,None)
        if v is not None and math.isfinite(float(v)):out[dst]=float(-v if maximize and src=='mip_dual_bound' else v)
    return out

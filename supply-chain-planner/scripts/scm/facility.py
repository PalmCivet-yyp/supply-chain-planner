"""Capacitated splittable location: screened transportation search plus support MIP."""
import time,warnings
import numpy as np
from scipy.optimize import linprog,milp,Bounds,LinearConstraint
from scipy.sparse import coo_matrix
from .optimization_common import array, numeric

def solve(d,seconds=60,seed=17,checkpoint=None):
 start=time.monotonic();deadline=start+max(.01,seconds-.4)
 if not np.isfinite(seconds) or seconds<=0:raise ValueError('seconds must be positive')
 c=array(d['allocation_cost_all_customer_demand']);f=array(d['fixed_cost']);dem=array(d['demand']);cap=array(d['capacity']);n,m=c.shape;rng=np.random.default_rng(seed)
 array(c,nonnegative=True);array(f,(m,));array(dem,(n,));array(cap,(m,))
 if n==0 or m==0 or np.any(dem<=0) or np.any(cap<=0):raise ValueError('Positive demand and capacity required')
 if sum(cap)<sum(dem)-1e-7:raise ValueError('Total capacity is smaller than total demand')
 kmin=int(np.ceil(sum(dem)/max(cap)-1e-12));global_bound=float(c.min(axis=1).sum()+np.sort(f)[:kmin].sum())
 cache={};best=[float('inf'),None,None];calls=0
 def pack(state):
  obj,opened,xx=state
  return {'status':'feasible','objective':float(obj),'witness':{'open_warehouses':[int(i+1) for i in opened],'allocations':[[int(opened[t]+1),int(j+1),float(xx[j,t])] for j,t in zip(*np.where(xx>1e-10))]},'evidence':{'seconds':time.monotonic()-start,'best_valid_bound':global_bound,'bound_scope':'global elementary lower bound','threads':1}}
 def accept(z):
  if z[0]<best[0]-1e-7:
   best[:]=z
   if checkpoint:checkpoint(pack(best))
 # Guaranteed all-capacity fractional allocation, before any expensive solve.
 xx=np.zeros((n,m));remaining=cap.copy()
 for j in np.argsort(-dem):
  need=dem[j]
  for i in np.argsort(c[j]):
   take=min(need,remaining[i]);xx[j,i]=take/dem[j];remaining[i]-=take;need-=take
   if need<1e-10:break
 used=np.flatnonzero(xx.sum(axis=0)>1e-12)
 accept([float(np.sum(c*xx)+f[used].sum()),tuple(used),xx[:,used]])
 def transport(opened):
  nonlocal calls
  opened=tuple(sorted(opened))
  if opened in cache:return cache[opened]
  if not opened or sum(cap[list(opened)])<sum(dem)-1e-7 or time.monotonic()>deadline:return None
  k=len(opened);x=np.arange(n*k).reshape(n,k)
  A=coo_matrix((np.r_[np.ones(n*k),np.repeat(dem,k)],(np.r_[np.repeat(np.arange(n),k),n+np.tile(np.arange(k),n)],np.r_[x.ravel(),x.ravel()])),shape=(n+k,n*k)).tocsc()
  r=linprog(c[:,opened].ravel(),A_ub=A[n:],b_ub=cap[list(opened)],A_eq=A[:n],b_eq=np.ones(n),bounds=(0,1),method='highs',options={'threads':1,'time_limit':max(.01,min(2,deadline-time.monotonic()))})
  calls+=1
  if r.x is None:return None
  xx=r.x.reshape(n,k);obj=float(c[:,opened].ravel()@r.x+sum(f[list(opened)]))
  if np.max(abs(xx.sum(axis=1)-1))>1e-6 or np.max(dem@xx-cap[list(opened)])>1e-5:return None
  cache[opened]=(obj,opened,xx)
  accept([obj,opened,xx])
  return cache[opened]
 # Multistart greedy uncapacitated opens, with full transportation repair.
 starts=[]
 for trial in range(16):
  opened=[];cur=np.full(n,np.inf)
  for _ in range(m):
   gains=(np.maximum(cur[:,None]-c,0).sum(axis=0)-f) if opened else -f-c.sum(axis=0)
   gains[opened]=-np.inf
   if trial and opened:gains=gains+rng.normal(0,max(1,np.max(np.abs(gains[np.isfinite(gains)]))*.025),m)
   j=int(np.argmax(gains))
   if opened and gains[j]<=0 and sum(cap[opened])>=sum(dem):break
   opened.append(j);cur=np.minimum(cur,c[:,j])
  z=transport(opened)
  if z:starts.append(z)
 # Best-improvement swaps/add/drop: cheap uncapacitated lower bounds screen exact transport LPs.
 visited=set()
 for restart in range(8):
  if time.monotonic()>start+seconds*.65:break
  if restart==0:current=best.copy()
  elif restart<len(starts):current=list(sorted(starts,key=lambda z:z[0])[restart])
  else:
   opened=list(best[1]); closed=list(set(range(m))-set(opened));
   if not closed:break
   opened.remove(int(rng.choice(opened)));opened.append(int(rng.choice(closed)));z=transport(opened)
   if not z:continue
   current=list(z)
  for iteration in range(20):
   opened=list(current[1]);key=tuple(opened)
   if key in visited:break
   visited.add(key);closed=np.array(sorted(set(range(m))-set(opened)),int);cand=[]
   costs=c[:,opened];idx=np.argmin(costs,axis=1);low=costs[np.arange(n),idx];second=np.partition(costs,1,axis=1)[:,1] if len(opened)>1 else np.full(n,np.inf);fixed=sum(f[opened])
   if len(closed):
    vals=fixed+f[closed]+np.minimum(low[:,None],c[:,closed]).sum(axis=0)
    for q in np.argsort(vals)[:12]:cand.append((float(vals[q]),tuple(sorted(opened+[int(closed[q])]))))
   for k,old in enumerate(opened):
    after=np.where(idx==k,second,low);base=fixed-f[old]
    if sum(cap[opened])-cap[old]>=sum(dem):cand.append((float(base+after.sum()),tuple(x for x in opened if x!=old)))
    if len(closed):
     vals=base+f[closed]+np.minimum(after[:,None],c[:,closed]).sum(axis=0)
     for q in np.argsort(vals)[:5]:cand.append((float(vals[q]),tuple(sorted([x for x in opened if x!=old]+[int(closed[q])]))))
   winner=current
   for lower,choice in sorted(set(cand)):
    if lower>=winner[0]-1e-7:break
    if time.monotonic()>start+seconds*.68:break
    z=transport(choice)
    if z and z[0]<winner[0]-1e-6:winner=list(z)
   if winner[0]>=current[0]-1e-6:break
   current=winner
 # MIP on union of competitive local supports. Its bound is restricted, not global.
 support=set(best[1]);
 for z in sorted(cache.values(),key=lambda z:z[0])[:8]:support.update(z[1])
 if len(support)>35:
  counts=np.zeros(m)
  for z in sorted(cache.values(),key=lambda z:z[0])[:8]:counts[list(z[1])]+=1
  support=set(best[1])|set(np.argsort(-counts)[:28])
 opened=np.array(sorted(support));k=len(opened);q=n*k;x=np.arange(q).reshape(n,k);y=q+np.arange(k)
 rr=np.r_[np.repeat(np.arange(n),k),n+np.tile(np.arange(k),n),n+np.arange(k),n+k+np.arange(q),n+k+np.arange(q)]
 cc=np.r_[x.ravel(),x.ravel(),y,x.ravel(),np.tile(y,n)];vv=np.r_[np.ones(q),np.repeat(dem,k),-cap[opened],np.ones(q),-np.ones(q)]
 A=coo_matrix((vv,(rr,cc)),shape=(n+k+q,q+k)).tocsc()
 remain=deadline-time.monotonic();res=None
 if remain>.1:
  res=milp(np.r_[c[:,opened].ravel(),f[opened]],integrality=np.r_[np.zeros(q),np.ones(k)],bounds=Bounds(0,1),constraints=LinearConstraint(A,np.r_[np.ones(n),np.full(k+q,-np.inf)],np.r_[np.ones(n),np.zeros(k+q)]),options={'threads':1,'time_limit':remain,'mip_rel_gap':1e-8})
  if res.x is not None and res.fun<best[0]:
   active=res.x[y]>.5;candidate=res.x[:q].reshape(n,k)[:,active]
   if candidate.shape[1] and np.max(abs(candidate.sum(axis=1)-1))<=1e-6 and np.max(dem@candidate-cap[opened[active]])<=1e-5:accept([float(res.fun),tuple(opened[active]),candidate])
 result=pack(best)
 result['method']='Multistart opening search; exact transportation subproblems screen add/drop/swap neighborhoods; restricted-support MIP polish'
 result['evidence'].update({'transport_solves':calls,'restricted_facilities':k,'restricted_mip_status':None if res is None else int(res.status),'restricted_bound_scope':'support only; never treated as global'})
 if res is not None and getattr(res,'mip_dual_bound',None) is not None and np.isfinite(res.mip_dual_bound):
  result['evidence']['restricted_bound']=float(res.mip_dual_bound)
  if k==m:
   result['evidence']['best_valid_bound']=max(global_bound,float(res.mip_dual_bound));result['evidence']['bound_scope']='global full support'
   if res.status==0 and abs(float(res.fun)-result['objective'])<=1e-6:result['status']='optimal'
 # Use unused budget to strengthen the global guarantee, preserving incumbent search.
 if result['status']!='optimal' and deadline-time.monotonic()>.1:
  from .facility_bounds import strengthen
  proof=strengthen(c,f,dem,cap,result['witness']['allocations'],min(8.,deadline-time.monotonic()-.05))
  result['evidence']['global_bound_certificate']=proof
  if proof.get('valid_bound',-np.inf)>result['evidence']['best_valid_bound']:
   result['evidence']['best_valid_bound']=proof['valid_bound'];result['evidence']['bound_scope']=proof['bound_scope']
 result['evidence']['seconds']=time.monotonic()-start
 result['evidence']['relative_gap']=(result['objective']-result['evidence']['best_valid_bound'])/max(1,abs(result['objective']))
 return numeric(result)

"""Cached regret repair and route-pool search for general deterministic VRPTW."""
import math,time
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import coo_matrix,vstack,csc_matrix
from .optimization_common import numeric

def solve(d,seconds=60,seed=17,checkpoint=None,initial_routes=None):
    start=time.monotonic();deadline=start+max(.03,seconds-.12);a=np.asarray(d['customers_including_depot'],float);n=len(a)-1
    dist=np.sqrt(((a[:,None,1:3]-a[None,:,1:3])**2).sum(axis=2));dem=a[:,3];ready=a[:,4];due=a[:,5];svc=a[:,6];cap=float(d['vehicle_capacity']);maxv=int(d['max_vehicles']);rng=np.random.default_rng(seed)
    weight=float(max(n,maxv)*max(1.,due[0])+1);pool={};best=None;bestscore=(math.inf,math.inf);iterations=0;accepted=0;masters=[]
    def length(r):return float(sum(dist[i,j] for i,j in zip([0]+list(r),list(r)+[0])))
    def feasible(r):
        clock=0.;last=0;load=0.
        for i in r:
            clock=max(ready[i],clock+svc[last]+dist[last,i]);load+=dem[i]
            if clock>due[i]+1e-8:return False
            last=i
        return load<=cap+1e-8 and clock+svc[last]+dist[last,0]<=due[0]+1e-8
    def score(routes):return len(routes),sum(length(r) for r in routes)
    def record(routes,force=False):
        for route in routes:
            t=tuple(route)
            if t and t not in pool and (len(pool)<30000 or force):pool[t]=length(t)
    def accept(routes):
        nonlocal best,bestscore
        if routes is None:return
        record(routes);s=score(routes)
        if s[0]<=maxv and s<bestscore and sorted(x for r in routes for x in r)==list(range(1,n+1)) and all(feasible(r) for r in routes):
            best=[list(r) for r in routes];bestscore=s;record(best,True)
            if checkpoint:checkpoint({'status':'feasible','objective':s[1],'witness':{'routes':best},'evidence':{'seconds':time.monotonic()-start,'threads':1}})
    def info(route):
        ns=np.array([0]+list(route)+[0],int);earliest=np.zeros(len(ns));latest=np.zeros(len(ns));latest[-1]=due[0]
        for k in range(1,len(ns)):earliest[k]=max(ready[ns[k]],earliest[k-1]+svc[ns[k-1]]+dist[ns[k-1],ns[k]])
        for k in range(len(ns)-2,-1,-1):latest[k]=min(due[ns[k]],latest[k+1]-svc[ns[k]]-dist[ns[k],ns[k+1]])
        return ns,earliest,latest,float(dem[ns].sum())
    def options(U,route):
        ns,e,l,load=info(route);prev=ns[:-1];nxt=ns[1:]
        st=np.maximum(ready[U,None],e[None,:-1]+svc[prev][None,:]+dist[U[:,None],prev])
        ok=(st<=due[U,None]+1e-9)&(st+svc[U,None]+dist[U[:,None],nxt]<=l[None,1:]+1e-9)&(dem[U,None]+load<=cap+1e-9)
        costs=dist[prev[None,:],U[:,None]]+dist[U[:,None],nxt]-dist[prev,nxt][None,:];costs=np.where(ok,costs,np.inf);pos=costs.argmin(axis=1)
        return costs[np.arange(len(U)),pos],pos
    def repair(partial,removed,noise=0.,regret=2):
        routes=[list(r) for r in partial if r];U=np.array(list(removed),int)
        if len(U)==0:return routes
        costs=np.full((len(U),n+1),np.inf);positions=np.zeros((len(U),n+1),int)
        for k,r in enumerate(routes):costs[:,k],positions[:,k]=options(U,r)
        while len(U):
            if time.monotonic()>deadline:return None
            nr=len(routes);costs[:,nr]=weight+2*dist[0,U];positions[:,nr]=0
            ranked=costs[:,:nr+1].copy()
            if noise:ranked+=rng.uniform(-noise,noise,ranked.shape)
            idx=ranked.argmin(axis=1);small=ranked[np.arange(len(U)),idx]
            kth=min(regret-1,nr);other=np.partition(ranked,kth,axis=1)[:,kth];priority=np.minimum(other,small+2*weight)-small+1e-5*dist[0,U]
            pick=int(priority.argmax());ri=int(idx[pick]);customer=int(U[pick]);position=int(positions[pick,ri])
            if ri==nr:routes.append([customer])
            else:routes[ri].insert(position,customer)
            keep=np.arange(len(U))!=pick;U=U[keep];costs=costs[keep];positions=positions[keep]
            if len(U):costs[:,ri],positions[:,ri]=options(U,routes[ri])
        return routes
    def partition(limit):
        record(best or [],True);routes=list(pool);K=len(routes)
        if not K or time.monotonic()>deadline-.06:return None
        rows=[];cols=[]
        for k,route in enumerate(routes):rows.extend(x-1 for x in route);cols.extend([k]*len(route))
        A=coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(n,K)).tocsc();A=vstack([A,csc_matrix(np.ones((1,K)))],format='csc')
        budget=min(limit,deadline-time.monotonic())
        if budget<=.02:return None
        result=milp(weight+np.array([pool[r] for r in routes]),integrality=np.ones(K),bounds=Bounds(0,1),constraints=LinearConstraint(A,np.r_[np.ones(n),0],np.r_[np.ones(n),maxv]),options={'time_limit':budget,'mip_rel_gap':1e-8,'threads':1})
        masters.append({'columns':K,'status':int(result.status),'scope':'restricted route pool only','weighted_bound':float(result.mip_dual_bound) if getattr(result,'mip_dual_bound',None) is not None and np.isfinite(result.mip_dual_bound) else None})
        if result.x is not None:return [list(routes[k]) for k in np.flatnonzero(result.x>.5)]
        return None
    record([[i] for i in range(1,n+1)])
    if initial_routes is not None:accept(initial_routes)
    current=None;curval=math.inf
    for trial in range(4):
        plan=repair([],rng.permutation(np.arange(1,n+1)).tolist(),noise=trial*3.,regret=2+trial%2)
        if plan is not None:
            accept(plan);s=score(plan);v=weight*s[0]+s[1]
            if v<curval:current=plan;curval=v
        if time.monotonic()>start+seconds*.18:break
    if best is not None:current=[r[:] for r in best];curval=weight*bestscore[0]+bestscore[1]
    if current is None:return {'status':'failed','objective':None,'witness':{},'method':'Cached-regret VRPTW search','evidence':{'reason':'No complete construction within budget','threads':1}}
    last_master=start;stagnation=0;search_stop=start+seconds*.81
    while time.monotonic()<min(search_stop,deadline):
        iterations+=1;flat=[x for r in current for x in r];q=int(rng.integers(1,min(30,n)+1));kind=int(rng.choice(4,p=[.3,.3,.15,.25]))
        if kind==0:removed=set(rng.choice(flat,min(q,len(flat)),replace=False).tolist())
        elif kind==1:
            pivot=int(rng.choice(flat));scores=dist[pivot,flat]+.12*np.abs(ready[pivot]-ready[flat])+rng.random(len(flat))*10;removed={flat[i] for i in np.argsort(scores)[:q]}
        elif kind==2:
            values=[]
            for route in current:
                for pos,x in enumerate(route):
                    p=route[pos-1] if pos else 0;z=route[pos+1] if pos+1<len(route) else 0;values.append((dist[p,x]+dist[x,z]-dist[p,z]+rng.random()*15,x))
            removed={x for value,x in sorted(values,reverse=True)[:q]}
        else:
            idx=int(np.argmin([len(r)+rng.random()*3 for r in current]));removed=set(current[idx]);rest=[x for x in flat if x not in removed]
            if len(removed)<q and rest:removed.update(rng.choice(rest,min(q-len(removed),len(rest)),replace=False).tolist())
        partial=[[x for x in route if x not in removed] for route in current];plan=repair(partial,removed,noise=float(rng.choice([0,0,2,5,12])),regret=int(rng.choice([2,2,3])))
        if plan is None:break
        previous_best=bestscore;accept(plan);s=score(plan);value=weight*s[0]+s[1];delta=value-curval;temp=18+45*(1-min(1,(time.monotonic()-start)/max(.1,seconds*.81)))
        if delta<0 or (abs(delta)<weight*.1 and rng.random()<math.exp(-max(0,delta)/temp)):current=plan;curval=value;accepted+=1
        stagnation=stagnation+1 if best is None or s>=previous_best else 0
        if stagnation>180 and best is not None:current=[r[:] for r in best];curval=weight*bestscore[0]+bestscore[1];stagnation=0
        if time.monotonic()-last_master>max(1.,seconds*.23) and time.monotonic()<start+seconds*.69:
            accept(partition(min(1.4,seconds*.04)));last_master=time.monotonic()
            if best is not None:current=[r[:] for r in best];curval=weight*bestscore[0]+bestscore[1]
    accept(partition(max(.01,deadline-time.monotonic()-.05)))
    if best is None:return {'status':'failed','objective':None,'witness':{},'method':'Cached-regret VRPTW search','evidence':{'reason':'No plan within fleet limit','iterations':iterations,'threads':1}}
    details=[]
    for route in best:
        ns,e,l,load=info(route);details.append({'load':load,'distance':length(route),'service_start':e[1:-1].tolist(),'depot_return':float(e[-1])})
    lower=math.ceil(float(dem.sum())/cap);clique=[]
    if time.monotonic()<deadline-.03:
        conflicts=np.zeros((n,n),bool)
        for i in range(1,n+1):
            if time.monotonic()>deadline:break
            for j in range(i+1,n+1):conflicts[i-1,j-1]=conflicts[j-1,i-1]=not feasible([i,j]) and not feasible([j,i])
        for i in np.argsort(-conflicts.sum(axis=1)):
            if all(conflicts[i,j] for j in clique):clique.append(int(i))
        lower=max(lower,len(clique))
    return numeric({'status':'feasible','objective':float(bestscore[1]),'witness':{'routes':best,'vehicle_count':len(best),'distance':float(bestscore[1])},'method':'Cached incremental regret repair, four destroy operators, annealed search and fleet-constrained route-pool MIP; double-precision Euclidean travel','evidence':{'seconds':time.monotonic()-start,'threads':1,'iterations':iterations,'accepted':accepted,'route_pool_count':len(pool),'restricted_masters':masters,'bound_scope':'Observed route pools only; not a global optimum certificate','vehicle_lower_bound':lower,'incompatibility_clique':[i+1 for i in clique],'route_details':details,'lexicographic_weight':weight}})

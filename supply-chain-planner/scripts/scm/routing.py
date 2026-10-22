"""Double-precision VRPTW search with validated DAG pricing and general ALNS fallback."""
import time,math,warnings
import numpy as np
from scipy.optimize import milp,linprog,Bounds,LinearConstraint
from scipy.sparse import coo_matrix,vstack,csc_matrix
from .optimization_common import array,numeric

def solve(d,seconds=60,seed=17,checkpoint=None):
 begin=time.monotonic()
 if not np.isfinite(seconds) or seconds<=0:raise ValueError('seconds must be positive and finite')
 a=array(d['customers_including_depot'],nonnegative=False)
 if a.ndim!=2 or a.shape[1]!=7 or len(a)<2 or not np.array_equal(a[:,0],np.arange(len(a))):raise ValueError('Require contiguous integer IDs 0..n with depot first')
 array(a[:,3:]);cap=float(d['vehicle_capacity']);vehicles=d['max_vehicles']
 if not np.isfinite(cap) or cap<=0 or int(vehicles)!=vehicles or vehicles<=0 or np.any(a[:,4]>a[:,5]) or a[0,3]!=0 or a[0,6]!=0:raise ValueError('Invalid capacity, windows, fleet or depot')
 if a[0,4]!=0:raise ValueError('Current routing contract requires depot ready time 0')
 if np.any(a[1:,3]>cap):raise ValueError('A customer exceeds vehicle capacity; split delivery is unsupported')
 xy=a[:,1:3];dist=np.sqrt(((xy[:,None,:]-xy[None,:,:])**2).sum(axis=2));n=len(a)-1
 def pair(i,j):
  t=max(a[i,4],dist[0,i]);u=max(a[j,4],t+a[i,6]+dist[i,j])
  return t<=a[i,5]+1e-9 and u<=a[j,5]+1e-9 and u+a[j,6]+dist[j,0]<=a[0,5]+1e-9 and a[i,3]+a[j,3]<=cap
 dag=all(a[j,4]>a[i,4] or not pair(i,j) for i in range(1,n+1) for j in range(1,n+1) if i!=j)
 integral=cap==int(cap) and np.all(a[:,3]==np.rint(a[:,3])) and cap<=100000
 for i in range(1,n+1):
  if max(a[i,4],dist[0,i])>a[i,5]+1e-9 or max(a[i,4],dist[0,i])+a[i,6]+dist[i,0]>a[0,5]+1e-9:raise ValueError('An individual customer is unreachable')
 with warnings.catch_warnings():
  warnings.filterwarnings('ignore',message='Unrecognized options detected')
  remaining=max(.01,seconds-(time.monotonic()-begin))
  from .routing_fast import solve as cached_search
  if dag and integral:
   result=dag_search(d,remaining,seed,checkpoint)
   leftover=seconds-(time.monotonic()-begin)
   if leftover>1.:
    alternative=cached_search(d,leftover,seed+1,checkpoint,result['witness']['routes'])
    oldscore=(len(result['witness']['routes']),result['objective'])
    newscore=(len(alternative.get('witness',{}).get('routes',[])),alternative.get('objective',float('inf')))
    if alternative.get('objective') is not None and newscore<oldscore:
     alternative['evidence']['vehicle_lower_bound']=max(alternative['evidence']['vehicle_lower_bound'],result['evidence']['vehicle_lower_bound']);alternative['evidence']['initial_dag_objective']=result['objective'];result=alternative
  else:result=cached_search(d,remaining,seed,checkpoint)
 result['evidence']['dag_verified']=dag
 result['evidence']['total_seconds']=time.monotonic()-begin
 return numeric(result)
def alns(d,seconds=60,seed=17,checkpoint=None):
 start=time.monotonic();a=np.array(d['customers_including_depot'],float);xy=a[:,1:3];dem=a[:,3];ready=a[:,4];due=a[:,5];service=a[:,6];D=np.sqrt(((xy[:,None,:]-xy[None,:,:])**2).sum(axis=2));n=len(a)-1;capacity=d['vehicle_capacity'];rng=np.random.default_rng(seed);pool={};penalty=float(d['max_vehicles']*max(1,due[0]-ready[0])+1)
 def info(route):
  nodes=np.array([0]+list(route)+[0],int);E=np.zeros(len(nodes));L=np.zeros(len(nodes));L[-1]=due[0]
  for k in range(1,len(nodes)):E[k]=max(ready[nodes[k]],E[k-1]+service[nodes[k-1]]+D[nodes[k-1],nodes[k]])
  for k in range(len(nodes)-2,-1,-1):L[k]=min(due[nodes[k]],L[k+1]-service[nodes[k]]-D[nodes[k],nodes[k+1]])
  return nodes,E,L,float(dem[nodes].sum()),float(D[nodes[:-1],nodes[1:]].sum())
 def valid(route):
  nodes,E,L,load,dist=info(route);return load<=capacity+1e-8 and np.all(E<=due[nodes]+1e-8)
 def routecost(route):return float(sum(D[x,y] for x,y in zip([0]+list(route),list(route)+[0])))
 def remember(routes):
  for r in routes:
   if r:
    t=tuple(r)
    if t not in pool:pool[t]=routecost(r)
 def score(routes):return penalty*len(routes)+sum(routecost(r) for r in routes)
 def save_checkpoint(routes):
  if checkpoint and len(routes)<=d['max_vehicles'] and all(valid(r) for r in routes):checkpoint({'status':'feasible','objective':sum(routecost(r) for r in routes),'witness':{'routes':routes},'evidence':{'seconds':time.monotonic()-start,'threads':1}})
 def repair(routes,removed,noise=0.,regret_k=2):
  routes=[r[:] for r in routes if r];cache=[info(r) for r in routes];U=list(removed)
  while U:
   us=np.array(U,int);nr=len(routes);costs=np.full((len(U),nr+1),np.inf);positions=np.zeros((len(U),nr),int)
   for rr,(nodes,E,L,load,dist) in enumerate(cache):
    prev=nodes[:-1];nxt=nodes[1:]
    st=np.maximum(ready[us,None],E[None,:-1]+service[prev][None,:]+D[us[:,None],prev[None,:]])
    ok=(st<=due[us,None]+1e-9)&(st+service[us,None]+D[us[:,None],nxt[None,:]]<=L[None,1:]+1e-9)&(load+dem[us,None]<=capacity+1e-9)
    delta=D[prev[None,:],us[:,None]]+D[us[:,None],nxt[None,:]]-D[prev,nxt][None,:]
    if noise:delta=delta*(1+rng.uniform(-noise,noise,delta.shape))
    delta=np.where(ok,delta,np.inf);pp=np.argmin(delta,axis=1);positions[:,rr]=pp;costs[:,rr]=delta[np.arange(len(U)),pp]
   costs[:,-1]=penalty+2*D[0,us]
   if nr+1>=regret_k:
    so=np.partition(costs,regret_k-1,axis=1);regret=so[:,regret_k-1]-np.min(costs,axis=1)
   else:regret=np.full(len(U),penalty)
   regret=np.where(np.isfinite(regret),regret,2*penalty)
   priority=regret+.03*2*D[0,us]+rng.random(len(U))*1e-4
   pick=int(np.argmax(priority));u=U.pop(pick);rr=int(np.argmin(costs[pick]))
   if rr==nr:routes.append([u]);cache.append(info([u]))
   else:
    routes[rr].insert(int(positions[pick,rr]),u);cache[rr]=info(routes[rr])
  return routes
 def relocate(routes,deadline):
  routes=[r[:] for r in routes];moves=0
  while moves<8 and time.monotonic()<deadline:
   cache=[info(r) for r in routes];bestmove=None;bestdelta=-1e-7
   for ra,r in enumerate(routes):
    for pos,u in enumerate(r):
     prv=0 if pos==0 else r[pos-1];nxt=0 if pos==len(r)-1 else r[pos+1];saving=D[prv,u]+D[u,nxt]-D[prv,nxt]+(penalty if len(r)==1 else 0)
     for rb,(nodes,E,L,load,dist) in enumerate(cache):
      if rb==ra or load+dem[u]>capacity:continue
      prev=nodes[:-1];nxts=nodes[1:];st=np.maximum(ready[u],E[:-1]+service[prev]+D[prev,u]);ok=(st<=due[u]+1e-8)&(st+service[u]+D[u,nxts]<=L[1:]+1e-8)
      delta=np.where(ok,D[prev,u]+D[u,nxts]-D[prev,nxts]-saving,np.inf);pp=int(np.argmin(delta))
      if delta[pp]<bestdelta:bestdelta=float(delta[pp]);bestmove=(ra,pos,rb,pp,u)
   if bestmove is None:break
   ra,pos,rb,pp,u=bestmove;routes[ra].pop(pos);routes[rb].insert(pp,u);routes=[r for r in routes if r];moves+=1
  return routes
 # Greedy incompatibility cliques are rigorous lower bounds on route count.
 compatible=np.zeros((n,n),bool)
 for i in range(1,n+1):
  for j in range(i+1,n+1):compatible[i-1,j-1]=compatible[j-1,i-1]=valid([i,j]) or valid([j,i])
 conflict=~compatible;np.fill_diagonal(conflict,False);clique=[]
 for it in range(100):
  rem=set(range(n));cur=[]
  while rem:
   cand=list(rem);v=max(cand,key=lambda q:sum(conflict[q,t] for t in cand)+rng.random()*.5);cur.append(v);rem={q for q in rem if conflict[v,q]}
  if len(cur)>len(clique):clique=cur
 best=None;bestscore=math.inf
 for it in range(3):
  rs=repair([],range(1,n+1),noise=.1*it,regret_k=2+(it%2));remember(rs);ss=score(rs)
  if ss<bestscore:best=rs;bestscore=ss
 save_checkpoint(best)
 current=[r[:] for r in best];cs=bestscore;iterations=0;lastprint=start
 while time.monotonic()-start<seconds*.75:
  iterations+=1
  if iterations%40==0:current=[r[:] for r in best];cs=bestscore
  nr=len(current);mode=iterations%5
  if mode in [0,1]:
   count=1 if mode==0 else min(3,nr);weights=np.array([1/(len(r)+.3)**2 for r in current]);weights/=weights.sum();chosen=set(rng.choice(nr,size=count,replace=False,p=weights).tolist());removed=[u for r,route in enumerate(current) if r in chosen for u in route];partial=[route[:] for r,route in enumerate(current) if r not in chosen]
  else:
   allnodes=[u for r in current for u in r];q=int(rng.integers(1,min(n,29)+1))
   if mode==2:
    seed=int(rng.choice(allnodes));related=[(D[seed,u]+.4*abs(ready[seed]-ready[u])+rng.random()*20,u) for u in allnodes];removed=[u for _,u in sorted(related)[:q]]
   elif mode==3:
    benefits=[]
    for r in current:
     for k,u in enumerate(r):
      prev=0 if k==0 else r[k-1];nxt=0 if k==len(r)-1 else r[k+1];benefits.append(((D[prev,u]+D[u,nxt]-D[prev,nxt])*rng.uniform(.5,1.5),u))
    removed=[u for _,u in sorted(benefits,reverse=True)[:q]]
   else:removed=rng.choice(allnodes,size=q,replace=False).tolist()
   rem=set(removed);partial=[[u for u in r if u not in rem] for r in current]
  candidate=repair(partial,removed,noise=float(rng.choice([0,.1,.25,.45])),regret_k=int(rng.choice([2,2,3])))
  if iterations%12==0 and time.monotonic()-start<seconds*.69:candidate=relocate(candidate,min(start+seconds*.73,time.monotonic()+.35))
  remember(candidate);ss=score(candidate);elapsed=time.monotonic()-start;temperature=10+50*(1-elapsed/max(.1,seconds*.76))
  if ss<cs or (len(candidate)==len(current) and rng.random()<math.exp(min(0,(cs-ss)/temperature))):current=candidate;cs=ss
  if len(candidate)<=d['max_vehicles'] and ss<bestscore:
   best=[r[:] for r in candidate];bestscore=ss;save_checkpoint(best)

 # Combine every feasible route observed using set partitioning.
 remember(best);routes=list(pool);cost=np.array([penalty+pool[r] for r in routes]);rows=[];cols=[]
 for k,r in enumerate(routes):
  for u in r:rows.append(u-1);cols.append(k)
 A=coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(n,len(routes))).tocsc();A=vstack([A,csc_matrix(np.ones((1,len(routes))))],format='csc');limit=max(.1,(seconds-.5)-(time.monotonic()-start))
 res=milp(cost,integrality=np.ones(len(routes)),bounds=Bounds(0,1),constraints=LinearConstraint(A,np.r_[np.ones(n),0],np.r_[np.ones(n),d['max_vehicles']]),options={'time_limit':limit,'mip_rel_gap':1e-9,'threads':1})
 if res.x is not None:
  cand=[list(routes[k]) for k in np.flatnonzero(res.x>.5)]
  if len(cand)<=d['max_vehicles'] and score(cand)<bestscore:best=cand;bestscore=score(cand)
 assert sorted(u for r in best for u in r)==list(range(1,n+1));assert all(valid(r) for r in best);assert len(best)<=d['max_vehicles']
 distance=sum(routecost(r) for r in best);route_details=[]
 for r in best:
  nodes,E,L,load,dist=info(r);route_details.append({'load':load,'distance':dist,'service_start':E[1:-1].tolist(),'depot_return':float(E[-1])})
 ev={'elapsed_seconds':time.monotonic()-start,'time_budget_seconds':seconds,'route_generation_iterations':iterations,'route_pool_size':len(pool),'pool_mip_time_limit':limit,'pool_mip_status':int(res.status),'pool_mip_message':str(res.message),'pool_mip_dual_bound':float(res.mip_dual_bound) if getattr(res,'mip_dual_bound',None) is not None and math.isfinite(res.mip_dual_bound) else None,'pool_bound_scope':'restricted observed route pool only; not a global routing lower bound','vehicle_lower_bound':max(len(clique),math.ceil(float(sum(dem))/capacity)),'incompatibility_clique':[x+1 for x in clique],'route_details':route_details,'threads':1}
 sol={'status':'feasible','objective':float(distance),'witness':{'routes':best,'vehicle_count':len(best),'distance':float(distance)},'method':'Randomized regret insertion and adaptive destroy/repair, cross-route relocation, then restricted-route exact set partitioning; hierarchical weight exceeds all feasible total distances','evidence':ev}
 return numeric(sol)

def dag_search(d,seconds=60,seed=17,checkpoint=None):
 t0=time.monotonic();deadline=t0+max(.01,seconds-.5);a=np.array(d['customers_including_depot'],float);xy=a[:,1:3];dist=np.sqrt(((xy[:,None,:]-xy[None,:,:])**2).sum(axis=2));ready=a[:,4];due=a[:,5];demand=a[:,3].astype(int);service=a[:,6];n=len(a)-1;cap=int(d['vehicle_capacity']);big=float(d['max_vehicles']*max(1,due[0])+1);rng=np.random.default_rng(seed)
 pool={};routes=[];lengths=[]
 def length(r):return float(sum(dist[i,j] for i,j in zip([0]+list(r),list(r)+[0])))
 def feasible(r):
  t=0.;prev=0;load=0
  for i in r:
   t=max(ready[i],t+dist[prev,i])
   if t>due[i]+1e-9:return False
   t+=service[i];load+=demand[i];prev=i
  return load<=cap and t+dist[prev,0]<=due[0]+1e-9
 def add(r):
  k=tuple(r)
  if k and k not in pool:pool[k]=len(routes);routes.append(k);lengths.append(length(k))
 for i in range(1,n+1):add([i])
 order=sorted(range(1,n+1),key=lambda i:ready[i]);adj={i:[j for j in order if ready[j]>ready[i] and ready[i]+service[i]+dist[i,j]<=due[j]+1e-9] for i in order}
 for i in order:
  for j in adj[i]:
   if feasible([i,j]):add([i,j])
 # Diverse complete solutions provide incumbent route combinations.
 best=None;bestval=float('inf');constructive_count=0
 while time.monotonic()<t0+min(3.,seconds*.08):
  remaining=set(range(1,n+1));plan=[];alpha=float(rng.uniform(.3,2));beta=float(rng.uniform(0,.3));noise=float(rng.uniform(0,8))
  while remaining:
   if constructive_count%3==0:seed=min(remaining,key=lambda i:due[i]+rng.uniform(0,30))
   elif constructive_count%3==1:seed=max(remaining,key=lambda i:dist[0,i]+rng.uniform(0,15))
   else:seed=int(rng.choice(list(remaining)))
   r=[seed];remaining.remove(seed)
   while remaining:
    candidates=[]
    for i in remaining:
     # Increasing ready times fix route visit order for this instance.
     k=next((k for k,j in enumerate(r) if ready[j]>ready[i]),len(r));rr=r[:k]+[i]+r[k:]
     if feasible(rr):
      before=0 if k==0 else r[k-1];after=0 if k==len(r) else r[k]
      score=dist[before,i]+dist[i,after]-dist[before,after]-alpha*dist[0,i]+beta*ready[i]+rng.uniform(0,noise)
      candidates.append((score,i,rr))
    if not candidates:break
    _,i,r=min(candidates,key=lambda z:z[0]);remaining.remove(i)
   plan.append(r);add(r)
  val=big*len(plan)+sum(length(r) for r in plan)
  if len(plan)<=d['max_vehicles'] and val<bestval:best=plan;bestval=val
  constructive_count+=1
 if checkpoint and best is not None:checkpoint({'status':'feasible','objective':sum(length(r) for r in best),'witness':{'routes':best}})
 def matrix():
  rows=[];cols=[]
  for k,r in enumerate(routes):rows.extend(i-1 for i in r);cols.extend([k]*len(r))
  return coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(n,len(routes))).tocsc()
 def price(dual,stop):
  labels={i:[(max(ready[i],dist[0,i])+service[i],int(demand[i]),float(dist[0,i]-dual[i-1]),(i,))] for i in order};new=[];rcmin=float('inf');labelcount=0;complete=True
  for i in order:
   if time.monotonic()>stop:complete=False;break
   ls=labels[i];ls.sort(key=lambda z:(z[0],z[1],z[2]));bestc=np.full(cap+1,np.inf);keep=[]
   for tt,load,rc,path in ls:
    if rc<bestc[load]-1e-8:
     keep.append((tt,load,rc,path));bestc[load:]=np.minimum(bestc[load:],rc)
   labelcount+=len(keep)
   feasibleends=[(rc+dist[i,0]+big,path) for tt,load,rc,path in keep if tt+dist[i,0]<=due[0]+1e-9]
   if feasibleends:
    rcmin=min(rcmin,min(z[0] for z in feasibleends))
    for red,path in sorted(feasibleends)[:16]:
     if red< -1e-6 and path not in pool:new.append((red,path))
   js=np.array(adj[i],dtype=int)
   if not len(js):continue
   ds=dist[i,js];rr=ready[js];dd=due[js];dem=demand[js];sv=service[js]
   for tt,load,rc,path in keep:
    starts=np.maximum(rr,tt+ds);oks=np.flatnonzero((starts<=dd+1e-9)&(load+dem<=cap)&(starts+sv+dist[js,0]<=due[0]+1e-9))
    for k in oks:
     j=int(js[k]);labels[j].append((float(starts[k]+sv[k]),int(load+dem[k]),float(rc+ds[k]-dual[j-1]),path+(j,)))
  return new,rcmin,complete,labelcount
 bounds=[];iterations=[];last_lp=None
 while time.monotonic()<t0+seconds*.45:
  A=matrix();remaining=t0+seconds*.46-time.monotonic()
  if remaining<.2:break
  c=big+np.array(lengths)
  lp=linprog(c,A_eq=A,b_eq=np.ones(n),bounds=(0,None),method='highs',options={'threads':1,'time_limit':min(3.,remaining)})
  if not lp.success:break
  last_lp=lp
  new,rcmin,complete,nlabels=price(lp.eqlin.marginals,min(t0+seconds*.48,time.monotonic()+5.0))
  if complete:
   bounds.append(float(lp.fun+d['max_vehicles']*min(0.,rcmin)))
  iterations.append({'columns':len(routes),'restricted_lp':float(lp.fun),'min_reduced_cost':float(rcmin),'pricing_complete':complete,'retained_labels':nlabels,'new_routes':len(new),'elapsed':time.monotonic()-t0})
  for _,r in sorted(new):add(r)
  if not new:break

 # Perturbed duals diversify integer route combinations; never used as valid bounds.
 if last_lp is not None:
  for iteration in range(18):
   if time.monotonic()>t0+seconds*.57:break
   dual=last_lp.eqlin.marginals+rng.normal(0,3+iteration%4,n)
   new,_,_,_=price(dual,min(t0+seconds*.59,time.monotonic()+.6))
   for _,route in sorted(new)[:500]:add(route)
 # A clique of pairwise incompatible customers is an independently valid vehicle lower bound.
 compatible=np.zeros((n+1,n+1),bool)
 for i in range(1,n+1):
  for j in range(i+1,n+1):compatible[i,j]=compatible[j,i]=feasible([i,j]) or feasible([j,i])
 clique=[]
 for trial in range(200):
  cand=list(range(1,n+1));cc=[]
  while cand:
   if trial==0:i=min(cand,key=lambda x:sum(compatible[x,j] for j in cand))
   else:i=min(cand,key=lambda x:sum(compatible[x,j] for j in cand)+rng.uniform(0,5))
   cc.append(i);cand=[j for j in cand if j!=i and not compatible[i,j]]
  if len(cc)>len(clique):clique=cc
 A=matrix();c=big+np.array(lengths);conA=vstack([A,csc_matrix(np.ones((1,len(routes))))],format='csc');rhslo=np.r_[np.ones(n),0];rhshi=np.r_[np.ones(n),d['max_vehicles']]
 remaining=max(.1,deadline-time.monotonic())
 r=milp(c,integrality=np.ones(len(routes)),bounds=Bounds(np.zeros(len(routes)),np.ones(len(routes))),constraints=LinearConstraint(conA,rhslo,rhshi),options={'threads':1,'time_limit':remaining,'mip_rel_gap':1e-9})
 if r.x is not None:
  chosen=[list(routes[k]) for k in np.flatnonzero(r.x>.5)];v=big*len(chosen)+sum(length(x) for x in chosen)
  if v<bestval:best=chosen;bestval=v
 if best is None:raise RuntimeError('No feasible within-fleet solution found')
 assert sorted(i for rr in best for i in rr)==list(range(1,n+1)) and all(feasible(rr) for rr in best)
 total=sum(length(rr) for rr in best);globlb=max(bounds) if bounds else None;vehiclelb=max(math.ceil(demand.sum()/cap),len(clique),math.ceil((globlb-d['max_vehicles']*due[0])/big-1e-9) if globlb is not None else 0)
 sol={'status':'feasible','objective':float(total),'witness':{'routes':best,'vehicle_count':len(best),'distance':float(total)},'method':f'Heuristic route-pool set partitioning: diverse full constructive plans, column generation using acyclic resource-constrained route pricing, then binary restricted master with lexicographic weight {big:g}; Euclidean arcs remain unrounded double precision. Restricted optimality does not certify globally shortest routes.','evidence':{'seconds':time.monotonic()-t0,'threads':1,'solver_status':int(r.status),'solver_message':r.message,'solver_restricted_gap':float(r.mip_gap) if getattr(r,'mip_gap',None) is not None and np.isfinite(r.mip_gap) else None,'route_pool_count':len(routes),'constructive_plans':constructive_count,'vehicle_lower_bound':vehiclelb,'incompatibility_clique':clique,'global_weighted_lower_bound':globlb,'pricing_bound_formula':f'sum master duals + {int(d["max_vehicles"])}*min(0, minimum route reduced cost), only on fully completed pricing rounds; every feasible customer pair was checked to verify the increasing-ready-time DAG condition','column_generation':iterations,'route_distances':[length(rr) for rr in best],'route_loads':[int(demand[rr].sum()) for rr in best]}}

 return numeric(sol)

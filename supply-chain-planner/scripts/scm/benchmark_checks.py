"""Independent all-decision checks; imports no Skill formulation or checker."""
import math
import numpy as np

def grade(data,result,reference):
    out={'feasible':False,'target_met':False,'objective':None,'vehicles':None,'gap_pct':None,'certificate_valid':None}
    try:
        if result.get('objective') is None:raise ValueError('No complete returned solution')
        w=result['witness'];reported=float(result['objective'])
        if not math.isfinite(reported):raise ValueError('Nonfinite objective')
        if 'allocation_cost_all_customer_demand' in data:
            cost=np.asarray(data['allocation_cost_all_customer_demand'],float);n,m=cost.shape;demand=np.asarray(data['demand']);capacity=np.asarray(data['capacity']);fixed=np.asarray(data['fixed_cost']);x=np.zeros((n,m));opened=w['open_warehouses'];y=np.zeros(m)
            assert len(set(opened))==len(opened) and all(type(i)==int and 1<=i<=m for i in opened)
            y[np.array(opened,int)-1]=1
            for i,j,f in w['allocations']:
                assert type(i)==int and type(j)==int and 1<=i<=m and 1<=j<=n and math.isfinite(float(f));x[j-1,i-1]+=f
            assert x.min()>=-1e-7 and np.abs(x.sum(1)-1).max()<=1e-5 and np.max(demand@x-capacity*y)<=1e-5 and np.max(x-y)<=1e-7
            obj=float((cost*x).sum()+fixed@y);out['gap_pct']=100*(obj-reference['objective'])/reference['objective'];out['target_met']=out['gap_pct']<=.1
            evidence=result.get('evidence',{});lb=evidence.get('best_valid_bound');out['valid_bound']=lb
            if lb is not None:
                assert math.isfinite(lb);out['certificate_valid']=lb<=reference['objective']+max(.001,reference['objective']*1e-8) and lb<=obj+max(.001,abs(obj)*1e-8)
            proof=evidence.get('global_bound_certificate',{})
            if proof.get('valid_bound') is not None:
                a=np.asarray(proof['alpha_customer']);b=np.asarray(proof['beta_capacity']);assert a.shape==(n,) and b.shape==(m,) and np.isfinite(a).all() and np.isfinite(b).all() and b.max()<=0
                full=float(a.sum()+np.minimum(0,fixed+capacity*b+np.minimum(0,cost-a[:,None]-demand[:,None]*b).sum(axis=0)).sum())
                out['certificate_valid']=bool(out['certificate_valid'] and proof['valid_bound']<=full+max(1e-6,abs(full)*1e-10));out['replayed_lagrangian_bound']=full
            if out['certificate_valid'] is False:out['target_met']=False
        else:
            a=np.asarray(data['customers_including_depot'],float);seen=[];obj=0.;routes=w['routes'];assert len(routes)<=data['max_vehicles']
            for route in routes:
                assert route and all(type(i)==int and 1<=i<len(a) for i in route);seen.extend(route);assert sum(a[i,3] for i in route)<=data['vehicle_capacity']+1e-7;time=0.;last=0
                for i in route:
                    arc=float(np.linalg.norm(a[last,1:3]-a[i,1:3]));obj+=arc;time=max(a[i,4],time+arc);assert time<=a[i,5]+1e-7;time+=a[i,6];last=i
                arc=float(np.linalg.norm(a[last,1:3]-a[0,1:3]));obj+=arc;assert time+arc<=a[0,5]+1e-7
            assert sorted(seen)==list(range(1,len(a)));out['vehicles']=len(routes);out['distance_gap_comparable']=len(routes)==reference['vehicles']
            if out['distance_gap_comparable']:out['gap_pct']=100*(obj-reference['objective'])/reference['objective']
            out['target_met']=len(routes)<reference['vehicles'] or (out['distance_gap_comparable'] and obj<=reference['objective']*1.01+reference.get('rounding_abs_tolerance',0))
        assert abs(obj-reported)<=1e-6*max(1,abs(obj));out['objective']=obj;out['feasible']=True
    except Exception as e:out.update({'feasible':False,'target_met':False,'error':str(e) or type(e).__name__})
    return out

def compare(old,new,kind):
    if old['feasible'] and not new['feasible']:return 'worse'
    if new['feasible'] and not old['feasible']:return 'better'
    if not old['feasible'] and not new['feasible']:return 'both_failed'
    if kind=='routing' and old['vehicles']!=new['vehicles']:return 'better' if new['vehicles']<old['vehicles'] else 'worse'
    delta=new['objective']-old['objective'];tol=max(1e-6,abs(old['objective'])*1e-6)
    return 'worse' if delta>tol else 'better' if delta< -tol else 'tie'

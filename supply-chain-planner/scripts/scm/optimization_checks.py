"""Direct decision checks, independent from the optimizer formulations."""
import numpy as np
from .optimization_common import array,numeric

def check(kind,d,result):
    if result.get('objective') is None:return {'passed':False,'reason':'No complete decision witness'}
    w=result['witness'];res={};obj=None
    def residual(key,a):res[key]=max(0.,float(np.max(a)))
    if kind=='facility':
        c=array(d['allocation_cost_all_customer_demand']);n,m=c.shape;x=np.zeros((n,m));opened=w['open_warehouses'];y=np.zeros(m)
        if len(set(opened))!=len(opened) or any(type(i)!=int or i<1 or i>m for i in opened):raise ValueError('Invalid warehouse IDs')
        y[np.array(opened)-1]=1
        for i,j,f in w['allocations']:
            if type(i)!=int or type(j)!=int or not 1<=i<=m or not 1<=j<=n:raise ValueError('Invalid shipment IDs')
            x[j-1,i-1]+=float(f)
        array(x,nonnegative=False);residual('nonnegative',-x);residual('customer_balance',abs(x.sum(axis=1)-1));residual('closed_shipments',x-y);residual('capacity',array(d['demand'])@x-array(d['capacity'])*y)
        obj=float(np.sum(c*x)+array(d['fixed_cost'])@y)
    elif kind=='routing':
        r=array(d['customers_including_depot'],nonnegative=False);xy=r[:,1:3];dist=np.sqrt(((xy[:,None,:]-xy[None,:,:])**2).sum(axis=2));flat=[];obj=0.;late=0.;cap=0.;ret=0.
        for route in w['routes']:
            if not route or any(type(i)!=int or not 1<=i<len(r) for i in route):raise ValueError('Invalid route IDs')
            flat+=route;time=0.;prev=0
            for i in route:
                time=max(r[i,4],time+dist[prev,i]);late=max(late,time-r[i,5]);obj+=dist[prev,i];time+=r[i,6];prev=i
            obj+=dist[prev,0];ret=max(ret,time+dist[prev,0]-r[0,5]);cap=max(cap,r[route,3].sum()-d['vehicle_capacity'])
        residual('visits',[0 if sorted(flat)==list(range(1,len(r))) else 1]);residual('windows',[late]);residual('return',[ret]);residual('capacity',[cap]);residual('fleet',[len(w['routes'])-d['max_vehicles']])
    elif kind=='blending':
        b,c,s,u=[array(w[k],nonnegative=False) for k in ['buy','consume','store','use']];T,K=b.shape;p=array(w['produce']);previous=np.vstack([np.broadcast_to(d['init_store'],(K,)),s[:-1]])
        residual('balance',abs(previous+b-c-s));residual('nonnegative',-np.r_[b.ravel(),c.ravel(),s.ravel()]);residual('use_integer',abs(u-np.rint(u)));residual('use_bounds',np.r_[-u.ravel(),u.ravel()-1]);residual('final',abs(s[-1]-d['target_store_per_oil']));residual('storage',s-d['max_store_per_oil']);residual('mass',abs(c.sum(axis=1)-p))
        veg=d.get('vegetable_oil_indices',[i for i,name in enumerate(d['oils']) if name.upper().startswith('VEG')]);other=[i for i in range(K) if i not in veg]
        residual('vegetable_capacity',c[:,veg].sum(axis=1)-d['veg_cap']);residual('other_capacity',c[:,other].sum(axis=1)-d['oil_cap']);hard=c@array(d['hardness']);residual('hardness_lower',d['min_hardness']*p-hard);residual('hardness_upper',hard-d['max_hardness']*p);residual('minimum_lot',d['min_consume']*u-c)
        caps=np.array([d['veg_cap'] if i in veg else d['oil_cap'] for i in range(K)]);residual('use_link',c-u*caps);residual('cardinality',u.sum(axis=1)-d['max_ingredients'])
        deps=d.get('use_implications',[[i,d['oils'].index('OIL3')] for i in veg] if 'OIL3' in d['oils'] else [])
        for i,j in deps:residual('implication_'+str(i),u[:,i]-u[:,j])
        obj=float(d['price']*p.sum()-np.sum(b*array(d['purchase_cost']))-np.sum(s*array(d['holding_cost'])))
    elif kind=='production':
        key=result['evidence'].get('counterfactual_key','extra_borer');counter=d.get('counterfactual',{'machine':'borer','count':1});machine=counter['machine'];idx=d['machines'].index(machine) if isinstance(machine,str) else machine;profits=[]
        for extra,name in [(0,'base'),(counter['count'],key)]:
            v=w[name];ma,se,st,re=[array(v[k],nonnegative=False) for k in ['make','sell','store','repair']];inst=array(d['installed']);inst[idx]+=extra
            residual(name+'_nonnegative',-np.r_[ma.ravel(),se.ravel(),st.ravel(),re.ravel()]);residual(name+'_balance',abs(np.vstack([np.zeros(ma.shape[1]),st[:-1]])+ma-se-st));residual(name+'_sales',se-array(d['max_sales']));residual(name+'_stock',st-d['max_inventory']);residual(name+'_final',abs(st[-1]-d['store_target']));residual(name+'_hours',ma@array(d['processing_hours']).T-d['hours_per_month']*(inst-re));residual(name+'_repair_int',abs(re-np.rint(re)));residual(name+'_repair_total',abs(re.sum(axis=0)-d['down_req']));residual(name+'_distinct_repair',re-array(d['installed']))
            value=float(np.sum(se*array(d['profit_per_sold_unit']))-d['holding_cost']*st.sum());profits.append(value)
            if extra:residual('extra_objective',[abs(value-v['objective'])])
        obj=profits[0];residual('incremental',[abs(profits[1]-profits[0]-w['incremental_profit'])])
    elif kind=='serial':
        s=w['echelon_levels'];loc=w['local_levels'];keys=sorted(s,key=int);residual('local_conversion',[abs(loc[k]-(s[k]-s[str(int(k)-1)] if int(k)>1 else s[k])) for k in keys]);residual('monotonic',[-v for v in loc.values()]);obj=float(w['expected_cost'])
    else:raise ValueError('Unknown optimization kind')
    tolerance=1e-5;agreement=abs(obj-result['objective'])<=1e-6*max(1,abs(obj))
    return numeric({'passed':all(v<=tolerance for v in res.values()) and agreement,'recomputed_objective':obj,'objective_agreement':agreement,'residuals':res})

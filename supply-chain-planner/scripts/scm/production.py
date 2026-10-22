"""Coupled monthly blending and production/maintenance optimization."""
import numpy as np
from .optimization_common import Model, Budget, array, evidence, numeric

def blending(d,seconds=60,seed=17,checkpoint=None):
    clock=Budget(seconds);cost=array(d['purchase_cost']);T,K=cost.shape
    if len(d['months'])!=T or len(d['oils'])!=K:raise ValueError('Month/oil labels do not match arrays')
    hard=array(d['hardness'],(K,));veg=d.get('vegetable_oil_indices',[i for i,name in enumerate(d['oils']) if name.upper().startswith('VEG')])
    other=[i for i in range(K) if i not in veg]
    if not veg or not other or len(set(veg))!=len(veg) or any(i<0 or i>=K for i in veg):raise ValueError('Declare valid vegetable_oil_indices')
    caps=np.array([d['veg_cap'] if i in veg else d['oil_cap'] for i in range(K)],float)
    initial=np.broadcast_to(array(d['init_store']),(K,));target=np.broadcast_to(array(d['target_store_per_oil']),(K,))
    maxstore=np.broadcast_to(array(d['max_store_per_oil']),(K,));holding=np.broadcast_to(array(d['holding_cost']),(T,K))
    if np.any(initial>maxstore) or np.any(target>maxstore) or d['min_hardness']>d['max_hardness']:raise ValueError('Inconsistent inventory/hardness limits')
    dependencies=d.get('use_implications')
    if dependencies is None:
        if 'OIL3' not in d['oils']:raise ValueError('Provide explicit use_implications')
        dependencies=[[i,d['oils'].index('OIL3')] for i in veg]
    mo=Model();b=mo.var((T,K),cost=cost);c=mo.var((T,K),cost=-float(d['price']));s=mo.var((T,K),upper=maxstore,cost=holding);u=mo.var((T,K),upper=1,integer=True)
    for t in range(T):
        for k in range(K):
            terms=[(b[t,k],1),(c[t,k],-1),(s[t,k],-1)]
            if t:terms.append((s[t-1,k],1))
            rhs=-initial[k] if not t else 0;mo.row(terms,rhs,rhs)
            mo.row([(c[t,k],1),(u[t,k],-caps[k])],upper=0)
            mo.row([(c[t,k],1),(u[t,k],-d['min_consume'])],lower=0)
        mo.row([(c[t,veg],1)],upper=d['veg_cap']);mo.row([(c[t,other],1)],upper=d['oil_cap'])
        mo.row([(c[t],hard-d['min_hardness'])],lower=0);mo.row([(c[t],hard-d['max_hardness'])],upper=0)
        mo.row([(u[t],1)],upper=d['max_ingredients'])
        for i,j in dependencies:mo.row([(u[t,i],1),(u[t,j],-1)],upper=0)
    for k in range(K):mo.row([(s[-1,k],1)],target[k],target[k])
    r=mo.solve(clock.remaining());ev=evidence(r,True);ev['seconds']=clock.elapsed()
    if r.x is None:return {'status':'infeasible' if r.status==2 else 'failed','objective':None,'witness':{},'evidence':ev}
    w={'buy':r.x[b],'consume':r.x[c],'store':r.x[s],'use':np.rint(r.x[u]).astype(int),'produce':r.x[c].sum(axis=1)}
    result=numeric({'status':'optimal' if r.status==0 else 'feasible','objective':float(-r.fun),'witness':w,'evidence':ev,'method':'Joint purchase/inventory/refining MILP with binary recipe implications'})
    if checkpoint:checkpoint(result)
    return result

def factory(d,seconds=60,seed=17,checkpoint=None):
    clock=Budget(seconds);sales=array(d['max_sales']);T,P=sales.shape;hours=array(d['processing_hours']);K=hours.shape[0]
    array(hours,(K,P));installed=array(d['installed'],(K,));down=array(d['down_req'],(K,));profit=array(d['profit_per_sold_unit'],(P,))
    if len(d['months'])!=T or len(d['products'])!=P or len(d['machines'])!=K:raise ValueError('Label dimensions differ')
    if np.any(installed!=np.rint(installed)) or np.any(down!=np.rint(down)) or np.any(down>installed):raise ValueError('Maintenance requires distinct original integer machines')
    holding=float(d['holding_cost']);maxstore=float(d['max_inventory']);target=float(d['store_target']);available=float(d['hours_per_month'])
    if min(holding,maxstore,target,available)<0 or target>maxstore:raise ValueError('Invalid stock/capacity data')
    counter=d.get('counterfactual',{'machine':'borer','count':1})
    machine=counter['machine'];index=d['machines'].index(machine) if isinstance(machine,str) else int(machine);count=int(counter['count'])
    if count<0 or count!=counter['count']:raise ValueError('Added machine count must be a nonnegative integer')
    def run(extra,limit):
        inst=installed.copy();inst[index]+=extra;mo=Model();ma=mo.var((T,P));se=mo.var((T,P),upper=sales,cost=-profit);st=mo.var((T,P),upper=maxstore,cost=holding);re=mo.var((T,K),upper=installed,integer=True)
        for t in range(T):
            for p in range(P):
                terms=[(ma[t,p],1),(se[t,p],-1),(st[t,p],-1)]
                if t:terms.append((st[t-1,p],1))
                mo.row(terms,0,0)
            for k in range(K):mo.row([(ma[t],hours[k]),(re[t,k],available)],upper=available*inst[k])
        for p in range(P):mo.row([(st[-1,p],1)],target,target)
        for k in range(K):mo.row([(re[:,k],1)],down[k],down[k])
        r=mo.solve(limit)
        if r.x is None:return {'status':'infeasible' if r.status==2 else 'failed','objective':None,'evidence':evidence(r,True)}
        return numeric({'status':'optimal' if r.status==0 else 'feasible','objective':-r.fun,'make':r.x[ma],'sell':r.x[se],'store':r.x[st],'repair':np.rint(r.x[re]).astype(int),'evidence':evidence(r,True)})
    base=run(0,clock.remaining()/2)
    if base['objective'] is None:return {'status':base['status'],'objective':None,'witness':{},'evidence':base['evidence']}
    result={'status':'feasible','objective':base['objective'],'witness':{'base':base},'evidence':{'seconds':clock.elapsed()}}
    if checkpoint:checkpoint(result)
    extra=run(count,clock.remaining());key='extra_borer' if machine=='borer' else 'extra_machine'
    if extra['objective'] is None:result['evidence']['counterfactual_failed']=extra;return result
    result.update({'status':'optimal' if base['status']==extra['status']=='optimal' else 'feasible','method':'Shared-capacity production and integer maintenance MILP; reoptimized machine-acquisition scenario'})
    result['witness'].update({key:extra,'incremental_profit':extra['objective']-base['objective']});result['evidence']={'base':base['evidence'],'counterfactual':extra['evidence'],'seconds':clock.elapsed(),'counterfactual_key':key}
    if checkpoint:checkpoint(result)
    return numeric(result)

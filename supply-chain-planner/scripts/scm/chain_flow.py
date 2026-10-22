"""Dated procurement, recipe, inventory and interwarehouse planning scenarios.

This is a finite-horizon material-flow model, not an ERP or production MRP.
All costs, quantities, receipt dates and scenario changes come from the input.
"""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from .optimization_common import Budget, Model, atomic_json, evidence, numeric


def number(value, positive=False):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a business quantity')
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise ValueError('Business quantities and costs must be finite and nonnegative')
    return result


def integer(value):
    result = number(value)
    if result != int(result):
        raise ValueError('Lead times and delay shifts must be whole days')
    return int(result)


def prepare(data, changes=None):
    changes = changes or {}
    if set(changes) - {'name', 'purchase_delays', 'capacity_factors'}:
        raise ValueError('Unknown scenario change')
    currency = data['currency']
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
        raise ValueError('Declare one three-letter currency for the entire model')
    days = [date.fromisoformat(x) for x in data['dates']]
    if not days or any(b-a != timedelta(days=1) for a,b in zip(days,days[1:])):
        raise ValueError('dates must be a nonempty consecutive daily horizon')
    locations = data['locations']; items = data['items']; keys = list(items)
    if not locations or not keys or len(set(locations)) != len(locations):
        raise ValueError('Require unique locations and at least one item')
    if any(not isinstance(x,str) or not x for x in locations+keys):
        raise ValueError('Item and location identifiers must be nonempty text')
    T,L,K = len(days),len(locations),len(keys)
    at = {d.isoformat():i for i,d in enumerate(days)};loc = {x:i for i,x in enumerate(locations)};sku = {x:i for i,x in enumerate(keys)}
    holding = np.array([number(items[x]['holding_cost']) for x in keys])
    shortage = np.array([number(items[x]['backlog_cost'],True) for x in keys])
    initial = np.zeros((L,K)); initial_backlog = np.zeros((L,K)); demand = np.zeros((T,L,K))
    for field,target in [('initial_stock',initial),('initial_backlog',initial_backlog)]:
        for row in data.get(field,[]):target[loc[row['location']],sku[row['item']]] += number(row['qty'])
    for row in data['demand']:demand[at[row['date']],loc[row['location']],sku[row['item']]] += number(row['qty'])
    groups = {name:np.array([number(v) for v in values]) for name,values in data.get('capacities',{}).items()}
    factors = changes.get('capacity_factors',{})
    if set(factors)-set(groups):raise ValueError('Scenario names an unknown capacity group')
    for name,values in groups.items():
        if values.shape!=(T,):raise ValueError('Each shared capacity requires one value per day')
        groups[name] = values * number(factors.get(name,1))
    purchases=[]; ids=set(); delays=changes.get('purchase_delays',{})
    for row in data['purchases']:
        name=row['id']
        if not isinstance(name,str) or name in ids:raise ValueError('Duplicate or invalid purchase ID')
        ids.add(name)
        if row.get('currency',currency)!=currency:raise ValueError('Mixed currencies require an explicit external conversion')
        ordered=date.fromisoformat(row['order_date']);arrival=date.fromisoformat(row['arrival_date'])
        if arrival<ordered or ordered>days[-1]:raise ValueError('Receipt precedes order or order is outside horizon')
        if ordered<days[0] and 'fixed_qty' not in row:raise ValueError('A past order must have explicitly committed fixed_qty')
        shifted=arrival+timedelta(days=integer(delays.get(name,0)))
        if shifted<days[0]:raise ValueError('Past receipts belong in initial_stock')
        pack=number(row.get('pack_size',1),True);maximum=number(row['max_qty']);fixed=row.get('fixed_qty')
        if fixed is not None:
            fixed=number(fixed)
            if fixed>maximum+1e-8 or abs(fixed/pack-round(fixed/pack))>1e-8:raise ValueError('Committed quantity contradicts capacity or pack size')
            if fixed>0 and fixed<number(row.get('moq',0))-1e-8:raise ValueError(name+': fixed_qty is below declared moq; correct the commitment or MOQ contract')
        purchases.append({'id':name,'location':loc[row['location']],'item':sku[row['item']],'arrival_index':at.get(shifted.isoformat()),'arrival_date':shifted.isoformat(),'order_date':ordered.isoformat(),'pack':pack,'max_qty':maximum,'min_qty':number(row.get('moq',0)),'fixed_qty':fixed,'unit_cost':number(row['unit_cost']),'order_cost':number(row.get('order_cost',0))})
    if set(delays)-ids:raise ValueError('Scenario names an unknown purchase')
    operations=[]; edges={x:set() for x in keys}; opids=set()
    for row in data.get('production',[]):
        if row['id'] in opids:raise ValueError('Duplicate production ID')
        opids.add(row['id']);out=row['output'];inputs={sku[k]:number(v,True) for k,v in row['inputs'].items()}
        if not inputs or out not in sku or row['capacity_group'] not in groups:raise ValueError('Production requires inputs, output and a shared capacity group')
        for k in row['inputs']:edges[k].add(out)
        operations.append({'id':row['id'],'location':loc[row['location']],'output':sku[out],'inputs':inputs,'lead':integer(row.get('lead_days',0)),'group':row['capacity_group'],'hours':number(row['hours_per_unit'],True),'max_qty':number(row['max_per_day']),'unit_cost':number(row['unit_cost'])})
    visiting=set();done=set()
    def visit(x):
        if x in visiting:raise ValueError('Production item cycles are unsupported')
        if x in done:return
        visiting.add(x)
        for y in edges[x]:visit(y)
        visiting.remove(x);done.add(x)
    for x in keys:visit(x)
    transfers=[]; trids=set()
    for row in data.get('transfers',[]):
        if row['id'] in trids:raise ValueError('Duplicate transfer ID')
        trids.add(row['id']);lead=integer(row['lead_days'])
        if lead<1 or row['from']==row['to']:raise ValueError('Transfers require different locations and at least one day transit')
        transfers.append({'id':row['id'],'from':loc[row['from']],'to':loc[row['to']],'item':sku[row['item']],'lead':lead,'max_qty':number(row['max_per_day']),'unit_cost':number(row['unit_cost'])})
    storage={loc[k]:number(v) for k,v in data.get('storage_capacity_units',{}).items()}
    return {'dates':data['dates'],'locations':locations,'items':keys,'currency':currency,'T':T,'L':L,'K':K,'holding':holding,'shortage':shortage,'initial':initial,'initial_backlog':initial_backlog,'demand':demand,'purchases':purchases,'production':operations,'transfers':transfers,'groups':groups,'storage':storage,'purchase_budget':None if data.get('purchase_budget') is None else number(data['purchase_budget']),'end_backlog_cap':None if data.get('end_backlog_cap') is None else number(data['end_backlog_cap'])}


def solve(data, changes, seconds):
    d=prepare(data,changes);T,L,K=d['T'],d['L'],d['K'];model=Model()
    stock=model.var((T,L,K),cost=d['holding']);back=model.var((T,L,K),cost=d['shortage']);ship=model.var((T,L,K));purchase=[];enabled=[]
    for row in d['purchases']:
        pack=row['pack'];fixed=row['fixed_qty'];maximum=row['max_qty'] if row['arrival_index'] is not None or fixed is not None else 0.
        x=model.var((1,),lower=0 if fixed is None else fixed/pack,upper=maximum/pack if fixed is None else fixed/pack,integer=True,cost=pack*row['unit_cost'])[0]
        y=model.var((1,),upper=1,integer=True,cost=row['order_cost'])[0];purchase.append(x);enabled.append(y)
        model.row([(x,pack),(y,-maximum)],upper=0);model.row([(x,pack),(y,-row['min_qty'])],lower=0)
    p=model.var((T,len(d['production'])),cost=[r['unit_cost'] for r in d['production']])
    tr=model.var((T,len(d['transfers'])),cost=[r['unit_cost'] for r in d['transfers']])
    for t in range(T):
        for j,row in enumerate(d['production']):
            model.row([(p[t,j],1)],upper=row['max_qty'] if t+row['lead']<T else 0.)
        for j,row in enumerate(d['transfers']):model.row([(tr[t,j],1)],upper=row['max_qty'] if t+row['lead']<T else 0.)
        for group,capacity in d['groups'].items():model.row([(p[t,j],row['hours']) for j,row in enumerate(d['production']) if row['group']==group],upper=capacity[t])
        for l,maximum in d['storage'].items():model.row([(stock[t,l],1)],upper=maximum)
        for l in range(L):
            for k in range(K):
                terms=[(stock[t,l,k],1),(ship[t,l,k],1)];backterms=[(back[t,l,k],1),(ship[t,l,k],1)]
                if t:terms.append((stock[t-1,l,k],-1));backterms.append((back[t-1,l,k],-1))
                for j,row in enumerate(d['purchases']):
                    if row['arrival_index']==t and row['location']==l and row['item']==k:terms.append((purchase[j],-row['pack']))
                for j,row in enumerate(d['production']):
                    if row['location']!=l:continue
                    if k in row['inputs']:terms.append((p[t,j],row['inputs'][k]))
                    if row['output']==k and t>=row['lead']:terms.append((p[t-row['lead'],j],-1))
                for j,row in enumerate(d['transfers']):
                    if row['item']!=k:continue
                    if row['from']==l:terms.append((tr[t,j],1))
                    if row['to']==l and t>=row['lead']:terms.append((tr[t-row['lead'],j],-1))
                initial=d['initial'][l,k] if t==0 else 0;required=d['demand'][t,l,k]+(d['initial_backlog'][l,k] if t==0 else 0)
                model.row(terms,lower=initial,upper=initial);model.row(backterms,lower=required,upper=required)
    if d['purchase_budget'] is not None:model.row([(purchase[j],r['pack']*r['unit_cost']) for j,r in enumerate(d['purchases'])]+[(enabled[j],r['order_cost']) for j,r in enumerate(d['purchases'])],upper=d['purchase_budget'])
    if d['end_backlog_cap'] is not None:model.row([(back[-1].ravel(),1)],upper=d['end_backlog_cap'])
    result=model.solve(seconds);out={'name':changes.get('name','base'),'status':'optimal' if result.status==0 else 'feasible' if result.x is not None else 'failed','objective':None if result.x is None else float(result.fun),'evidence':evidence(result)}
    if result.x is None:return out
    x=result.x;out['witness']={'purchase_qty':{r['id']:float(x[purchase[j]]*r['pack']) for j,r in enumerate(d['purchases'])},'purchase_enabled':{r['id']:float(x[enabled[j]]) for j,r in enumerate(d['purchases'])},'production':x[p].tolist(),'transfers':x[tr].tolist(),'stock':x[stock].tolist(),'backlog':x[back].tolist(),'delivered':x[ship].tolist()}
    out['axes']={'dates':d['dates'],'locations':d['locations'],'items':d['items'],'production':[r['id'] for r in d['production']],'transfers':[r['id'] for r in d['transfers']]};out['currency']=d['currency']
    out['metrics']={'delivered_units':float(x[ship].sum()),'end_backlog_units':float(x[back][-1].sum()),'backlog_unit_days':float(x[back].sum()),'end_stock_units':float(x[stock][-1].sum()),'committed_units_receiving_after_horizon':float(sum(out['witness']['purchase_qty'][r['id']] for r in d['purchases'] if r['arrival_index'] is None))}
    out['validation']=validate(data,changes,out)
    if not out['validation']['passed']:raise ValueError('Scenario witness failed independent flow checks')
    return numeric(out)


def validate(data,changes,result):
    """Replay receipts and transformations directly, without LP matrices."""
    d=prepare(data,changes);w=result['witness'];T,L,K=d['T'],d['L'],d['K'];res={}
    arrays={k:np.asarray(w[k],float) for k in ['stock','backlog','delivered','production','transfers']}
    for k,shape in [('stock',(T,L,K)),('backlog',(T,L,K)),('delivered',(T,L,K)),('production',(T,len(d['production']))),('transfers',(T,len(d['transfers'])))]:
        a=arrays[k]
        if a.shape!=shape or not np.isfinite(a).all():raise ValueError('Bad scenario witness shape or numeric value')
        res[k+'_nonnegative']=float(max(0.,-a.min())) if a.size else 0.
    expected=np.repeat(d['initial'][None,:,:],T,axis=0);flows=np.zeros_like(expected);buycost=0.;othercost=0.;violations=[]
    for row in d['purchases']:
        q=float(w['purchase_qty'][row['id']]);y=float(w['purchase_enabled'][row['id']]);violations += [-q,abs(q/row['pack']-round(q/row['pack'])),abs(y-round(y)),-y,y-1,q-row['max_qty']*y,row['min_qty']*y-q]
        if row['fixed_qty'] is not None:violations.append(abs(q-row['fixed_qty']))
        elif row['arrival_index'] is None:violations.append(q)
        if row['arrival_index'] is not None:flows[row['arrival_index'],row['location'],row['item']]+=q
        buycost+=q*row['unit_cost']+y*row['order_cost']
    for j,row in enumerate(d['production']):
        q=arrays['production'][:,j];violations.extend((q-row['max_qty']).tolist());othercost+=float(q.sum()*row['unit_cost'])
        for k,units in row['inputs'].items():flows[:,row['location'],k]-=q*units
        for t in range(T):
            if t+row['lead']<T:flows[t+row['lead'],row['location'],row['output']]+=q[t]
            else:violations.append(q[t])
    for group,capacity in d['groups'].items():
        use=np.zeros(T)
        for j,row in enumerate(d['production']):
            if row['group']==group:use+=arrays['production'][:,j]*row['hours']
        violations.extend((use-capacity).tolist())
    for j,row in enumerate(d['transfers']):
        q=arrays['transfers'][:,j];violations.extend((q-row['max_qty']).tolist());othercost+=float(q.sum()*row['unit_cost']);flows[:,row['from'],row['item']]-=q
        for t in range(T):
            if t+row['lead']<T:flows[t+row['lead'],row['to'],row['item']]+=q[t]
            else:violations.append(q[t])
    expected+=np.cumsum(flows-arrays['delivered'],axis=0);expected_back=d['initial_backlog'][None,:,:]+np.cumsum(d['demand']-arrays['delivered'],axis=0)
    res['stock_balance']=float(np.abs(expected-arrays['stock']).max());res['demand_balance']=float(np.abs(expected_back-arrays['backlog']).max())
    for l,maximum in d['storage'].items():violations.extend((arrays['stock'][:,l].sum(axis=1)-maximum).tolist())
    if d['purchase_budget'] is not None:violations.append(buycost-d['purchase_budget'])
    if d['end_backlog_cap'] is not None:violations.append(arrays['backlog'][-1].sum()-d['end_backlog_cap'])
    res['business_constraints']=max(0.,max(violations,default=0.));obj=buycost+othercost+float((arrays['stock']*d['holding']).sum()+(arrays['backlog']*d['shortage']).sum());res['objective_error']=abs(obj-result['objective'])
    return {'passed':all(v<=1e-5 for k,v in res.items() if k!='objective_error') and res['objective_error']<=1e-7*max(1,abs(obj)),'residuals':res,'recomputed_objective':obj}


def run(input_path,out,seconds=60):
    raw=Path(input_path).read_bytes();data=json.loads(raw);dest=Path(out)
    if dest.exists():raise ValueError('Output directory already exists')
    scenarios=[{'name':'base'}]+data.get('scenarios',[]);names=[s['name'] for s in scenarios]
    if len(set(names))!=len(names):raise ValueError('Scenario names must be unique')
    for s in scenarios:prepare(data,s)
    dest.mkdir(parents=True);budget=Budget(seconds);results=[]
    try:
        for index,scenario in enumerate(scenarios):
            if budget.remaining()<=.02:raise ValueError('No remaining budget for all scenarios')
            result=solve(data,scenario,budget.remaining()/(len(scenarios)-index));results.append(result);atomic_json(dest/'checkpoint.json',{'scenarios':results})
        from . import VERSION
        base=results[0];deltas=[]
        for r in results[1:]:
            if r['objective'] is not None and base['objective'] is not None:deltas.append({'name':r['name'],'cost_change':r['objective']-base['objective'],'end_backlog_change':r['metrics']['end_backlog_units']-base['metrics']['end_backlog_units'],'backlog_unit_days_change':r['metrics']['backlog_unit_days']-base['metrics']['backlog_unit_days']})
        count=sum(r['objective'] is not None and r.get('validation',{}).get('passed',False) for r in results)
        answer={'kind':'chain','status':'ready_for_review' if count==len(results) else 'partial' if count else 'blocked','feasible_scenarios':count,'engine_version':VERSION,'currency':data['currency'],'scenarios':results,'deltas':deltas,'input_sha256':hashlib.sha256(raw).hexdigest(),'parameters':{'seconds':seconds,'threads':1},'scope':['Finite daily horizon; all demand backordered; quantities served before future demand cannot be borrowed.','Purchases respect explicitly declared receipt dates, MOQ, pack size and commitment. Shared production hours and positive transit times apply.','Production has fixed acyclic recipes and continuous batch quantities. It is not sequence scheduling or production MRP.','All modeled procurement is charged; no terminal salvage value or stochastic service guarantee is assumed. Scenarios are deterministic stress tests.']}
        atomic_json(dest/'report.json',answer)
        from .optimization_delivery import write_html
        write_html(answer,dest/'report.html')
        return answer
    except Exception as error:
        atomic_json(dest/'failure.json',{'error':str(error),'checkpoint_retained':(dest/'checkpoint.json').exists()});raise

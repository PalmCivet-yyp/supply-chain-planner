"""All-arc Lagrangian lower bounds with independently replayable multipliers."""
import time
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

def replay_bound(cost,fixed,demand,capacity,alpha,beta):
    """Minimize the relaxed objective analytically over 0<=x_ji<=y_i<=1.

    Customer equations use alpha (free); capacity <= rows use beta <= 0.
    Every ORIGINAL arc is priced, including arcs omitted from the auxiliary LP.
    Thus auxiliary infeasibility/omission cannot turn its bound into a false
    full-model certificate. Any finite alpha/beta with beta<=0 is valid.
    """
    c=np.asarray(cost,float);f=np.asarray(fixed,float);dem=np.asarray(demand,float);cap=np.asarray(capacity,float)
    a=np.asarray(alpha,float);b=np.asarray(beta,float)
    if a.shape!=(c.shape[0],) or b.shape!=(c.shape[1],) or not np.isfinite(a).all() or not np.isfinite(b).all() or np.any(b>0):raise ValueError('Invalid dual multipliers')
    reduced=np.minimum(0.,c-a[:,None]-dem[:,None]*b[None,:])
    site=f+cap*b+reduced.sum(axis=0)
    terms=np.r_[a,np.minimum(site,0.)]
    outward=1e-10*max(1.,float(np.abs(terms).sum()))
    return float(terms.sum()-outward)

def strengthen(cost,fixed,demand,capacity,allocations,seconds):
    start=time.monotonic();c=np.asarray(cost,float);f=np.asarray(fixed,float);dem=np.asarray(demand,float);cap=np.asarray(capacity,float);n,m=c.shape
    if seconds<=.05:return {'status':'not_run','reason':'No unused solve budget'}
    k=min(m,18)
    if n*m<=20000:arcs={(j,i) for j in range(n) for i in range(m)}
    else:arcs={(j,int(i)) for j in range(n) for i in np.argpartition(c[j],k-1)[:k]}
    arcs.update((j-1,i-1) for i,j,x in allocations if x>0)
    arcs=sorted(arcs);K=len(arcs);js=np.array([j for j,i in arcs]);ii=np.array([i for j,i in arcs]);cols=np.arange(K)
    rows=np.r_[js,n+ii,n+m+cols,n+m+cols,n+np.arange(m)]
    cc=np.r_[cols,cols,cols,K+ii,K+np.arange(m)]
    vv=np.r_[np.ones(K),dem[js],np.ones(K),-np.ones(K),-cap]
    A=coo_matrix((vv,(rows,cc)),shape=(n+m+K,K+m)).tocsc();remaining=seconds-(time.monotonic()-start)
    if remaining<=.02:return {'status':'not_run','reason':'Matrix construction used remaining budget'}
    r=linprog(np.r_[c[js,ii],f],A_eq=A[:n],b_eq=np.ones(n),A_ub=A[n:],b_ub=np.zeros(m+K),bounds=(0,1),method='highs',options={'time_limit':remaining,'threads':1})
    result={'status':'computed' if r.status==0 else 'no_certificate','auxiliary_status':int(r.status),'auxiliary_arcs':K,'original_arcs':n*m,'seconds':time.monotonic()-start,'auxiliary_bound_scope':'Restricted LP only; not a full-model bound'}
    if r.status==0:
        alpha=r.eqlin.marginals;beta=np.minimum(r.ineqlin.marginals[:m],0.)
        result.update({'valid_bound':replay_bound(c,f,dem,cap,alpha,beta),'alpha_customer':alpha.tolist(),'beta_capacity':beta.tolist(),'all_original_arcs_priced':True,'bound_scope':'global all-arc Lagrangian relaxation','formula':'sum(alpha)+sum_i min(0,f_i+cap_i*beta_i+sum_j min(0,c_ji-alpha_j-demand_j*beta_i))'})
    return result

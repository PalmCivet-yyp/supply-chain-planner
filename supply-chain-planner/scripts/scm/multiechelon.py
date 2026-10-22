"""Normal-demand serial stochastic-service recursion with explicit grid convergence."""
import math
import numpy as np
from scipy.signal import fftconvolve
from scipy.special import ndtr
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize_scalar
from .optimization_common import Budget, array, numeric

def solve(d,seconds=60,seed=17,checkpoint=None):
    clock=Budget(seconds);order=d['node_order_upstream_to_downstream'];N=len(order)
    if order!=list(range(N,0,-1)):raise ValueError('Serial node order must be N..1 with node 1 downstream')
    h=array([d['echelon_holding_cost'][str(j)] for j in range(1,N+1)]);local=array([d['local_holding_cost'][str(j)] for j in range(1,N+1)])
    lead=array([d['shipment_lead_time'][str(j)] for j in range(1,N+1)]);mu=float(d['per_period_normal_demand_mean']);sd=float(d['per_period_normal_demand_sd']);p=float(d['stockout_cost'])
    array([mu,sd,p]);
    if min(sd,p)<=0 or np.any(h<=0) or not np.allclose(local,np.cumsum(h[::-1])[::-1],rtol=1e-9,atol=1e-9):raise ValueError('Require positive sd, stockout/echelon costs and telescoping local costs')
    baseline={str(k):float(v) for k,v in d['baseline_echelon_levels'].items()}
    if set(baseline)!=set(map(str,range(1,N+1))):raise ValueError('Baseline policy keys differ from serial nodes')
    totalmu=mu*lead.sum();totalsd=sd*np.sqrt(lead.sum());extent=max(10.,totalmu+12*totalsd+10,max(abs(v) for v in baseline.values())+12*totalsd)
    scale=max(1.,totalsd/2);penal=p+local[0];convergence=[]
    def evaluate(dx,policy=None):
        size=int(math.ceil(2*extent/dx))+1
        if size>300000:raise ValueError('Numerical grid exceeds 300000 states; change units or explicit method')
        x=np.linspace(-extent,extent,size);dx=float(x[1]-x[0]);levels={};g=None;fun=None
        for j in range(N):
            mean=mu*lead[j];sigma=sd*math.sqrt(lead[j])
            if j==0:
                if sigma:
                    z=(x-mean)/sigma;g=h[j]*(x-mean)+penal*sigma*(np.exp(-z*z/2)/math.sqrt(2*math.pi)-z*ndtr(-z))
                else:g=h[j]*(x-mean)+penal*np.maximum(mean-x,0)
            else:
                s=levels[str(j)];sat=float(fun(s));u=np.where(x<=s,g,sat)
                if sigma:
                    radius=math.ceil(12*sigma/dx);offset=np.arange(-radius,radius+1)*dx;kernel=np.exp(-.5*(offset/sigma)**2);kernel/=kernel.sum()
                    left=x[0]-np.arange(radius,0,-1)*dx
                    means=mu*lead[:j];slope=h[:j].sum()-penal
                    intercept=-sum(h[i]*means[i:].sum() for i in range(j))+penal*means.sum()
                    extended=np.r_[slope*left+intercept,u,np.full(radius,sat)]
                    smoothed=fftconvolve(extended,kernel,mode='valid')
                    # Shift by the lead-time mean; exact affine left tail and saturated right tail.
                    spline=CubicSpline(x,smoothed,extrapolate=False);z=x-mean;values=spline(np.clip(z,x[0],x[-1]))
                    values=np.where(z<x[0],slope*z+intercept,values);values=np.where(z>x[-1],sat,values)
                    g=h[j]*(x-mean)+values
                else:g=h[j]*(x-mean)+np.interp(x-mean,x,u)
            fun=CubicSpline(x,g)
            if policy is None:
                k=int(np.argmin(g))
                if k<3 or k>len(x)-4:raise ValueError('Optimum touches numerical boundary; domain not validated')
                result=minimize_scalar(fun,bounds=(x[k-2],x[k+2]),method='bounded',options={'xatol':1e-11});s=float(result.x)
            else:s=float(policy[str(j+1)])
            levels[str(j+1)]=s
        return levels,float(fun(levels[str(N)]))
    result=None
    for spacing in [.02,.01,.005,.0025]:
        if result is not None and clock.remaining()<.01:break
        levels,cost=evaluate(scale*spacing);_,bc=evaluate(scale*spacing,baseline)
        convergence.append({'grid_spacing':scale*spacing,'normal_tail_sd':12,'echelon_levels':levels,'expected_cost':cost,'baseline_cost':bc})
        locals_={str(j):levels[str(j)]-(levels[str(j-1)] if j>1 else 0) for j in range(1,N+1)}
        result={'status':'feasible','objective':cost,'witness':{'echelon_levels':levels,'local_levels':locals_,'expected_cost':cost,'baseline_cost':bc,'improvement_pct':100*(bc-cost)/bc if bc else 0,'convergence':convergence},'method':'Serial Normal-demand Clark-Scarf recursion; analytic first stage and padded Gaussian convolution','evidence':{'seconds':clock.elapsed(),'guarantee':'Numerical convex recursion; finite integration grid, not a symbolic optimum'}}
        if checkpoint:checkpoint(result)
    delta=abs(convergence[-1]['expected_cost']-convergence[-2]['expected_cost']) if len(convergence)>1 else None
    result['evidence']['last_cost_change']=delta;result['evidence']['seconds']=clock.elapsed()
    result['status']='optimal_numerical' if delta is not None and delta<=max(1e-6,abs(cost)*1e-6) else 'feasible'
    return numeric(result)

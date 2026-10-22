"""Choose between two already calculated plans with identical input identity.

This performs no additional search. It cannot make an isolated timed engine
run monotonically better; it protects adoption when a baseline already exists.
"""
import hashlib,json
from pathlib import Path
from .benchmark_checks import grade,compare
from .optimization_common import atomic_json

def review(input_path,baseline_path,candidate_path,out):
    raw=Path(input_path).read_bytes();data=json.loads(raw);fingerprint=hashlib.sha256(raw).hexdigest();plans={name:json.loads(Path(p).read_text()) for name,p in [('baseline',baseline_path),('candidate',candidate_path)]};dest=Path(out)
    if dest.exists():raise ValueError('Output directory already exists')
    kinds={p.get('kind') for p in plans.values()}
    if len(kinds)!=1 or next(iter(kinds)) not in ['facility','routing']:raise ValueError('Review requires the same facility or routing contract')
    kind=next(iter(kinds));checks={}
    if (kind=='facility')!=('allocation_cost_all_customer_demand' in data):raise ValueError('Plan kind differs from input contract')
    for name,plan in plans.items():
        if plan.get('input_sha256')!=fingerprint:raise ValueError('Plan input fingerprint differs; do not compare different business inputs')
        # This temporary reference only enables direct feasibility/objective replay.
        # Its target score is ignored; no external optimum is inferred from it.
        ref={'objective':max(1.,abs(plan.get('objective') or 0)),'vehicles':len(plan.get('witness',{}).get('routes',[])),'rounding_abs_tolerance':0}
        g=grade(data,plan,ref);checks[name]={k:v for k,v in g.items() if k not in ['target_met','gap_pct','distance_gap_comparable']}
        checks[name]['witness_feasible']=checks[name]['feasible']
        checks[name]['feasible']=checks[name]['feasible'] and checks[name].get('certificate_valid') is not False
    decision=compare(checks['baseline'],checks['candidate'],kind)
    selected='candidate' if decision=='better' else 'baseline' if checks['baseline']['feasible'] else None
    dest.mkdir(parents=True);result={'kind':kind,'input_sha256':fingerprint,'selected':selected,'comparison':decision,'checks':checks,'scope':'No optimization or extra search. Feasible plans with identical input bytes are compared by fleet then distance, or facility cost. Ties retain the baseline. This is an adoption safeguard, not evidence that a standalone engine never regresses.'}
    if selected is not None:atomic_json(dest/'accepted_plan.json',plans[selected])
    atomic_json(dest/'review.json',result)
    return result

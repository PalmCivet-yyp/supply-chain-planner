"""Behavioral checks for fractional plans, failure retention and model semantics."""
import itertools,json,tempfile,unittest,warnings
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from scm.optimization_common import atomic_json
from scm.optimization_checks import check
from scm import facility,routing,production,multiechelon

class AdvancedTests(unittest.TestCase):
    def test_atomic_numpy_and_failed_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'result.json';atomic_json(p,{'id':np.int64(7),'flags':np.array([True]),'x':np.float64(.25)})
            before=p.read_bytes();self.assertEqual(json.loads(before)['id'],7)
            with self.assertRaises(ValueError):atomic_json(p,{'value':float('nan')})
            self.assertEqual(p.read_bytes(),before)
    def test_split_facility_matches_exhaustive_opening_sets(self):
        d={'capacity':[5,5,5],'fixed_cost':[3,1,4],'demand':[7,2],'allocation_cost_all_customer_demand':[[1,8,2],[6,1,3]]}
        costs=np.array(d['allocation_cost_all_customer_demand']);best=float('inf')
        for flags in itertools.product([0,1],repeat=3):
            ids=np.flatnonzero(flags)
            if not len(ids):continue
            k=len(ids);eq=np.kron(np.eye(2),np.ones((1,k)));ub=np.zeros((k,2*k))
            for j in range(2):ub[:,j*k:(j+1)*k]=np.eye(k)*d['demand'][j]
            r=linprog(costs[:,ids].ravel(),A_eq=eq,b_eq=[1,1],A_ub=ub,b_ub=np.array(d['capacity'])[ids],bounds=(0,1),method='highs')
            if r.success:best=min(best,r.fun+np.array(d['fixed_cost'])[ids].sum())
        with warnings.catch_warnings():
            warnings.simplefilter('ignore');result=facility.solve(d,2)
        self.assertAlmostEqual(result['objective'],best,6);self.assertTrue(check('facility',d,result)['passed'])
        self.assertTrue(any(0<f<1 for _,_,f in result['witness']['allocations']))
    def test_facility_insufficient_capacity(self):
        with self.assertRaises(ValueError):facility.solve({'capacity':[1],'fixed_cost':[0],'demand':[2],'allocation_cost_all_customer_demand':[[1]]},1)
    def test_route_waiting_and_duplicate_rejection(self):
        d={'max_vehicles':1,'vehicle_capacity':4,'customers_including_depot':[[0,0,0,0,0,30,0],[1,1,0,1,5,8,1],[2,2,0,1,9,12,1]]}
        s={'objective':4,'witness':{'routes':[[1,2]]}}
        self.assertTrue(check('routing',d,s)['passed']);s['witness']['routes']=[[1,1,2]];self.assertFalse(check('routing',d,s)['passed'])
    def test_routing_rejects_split_customer(self):
        d={'max_vehicles':1,'vehicle_capacity':1,'customers_including_depot':[[0,0,0,0,0,30,0],[1,1,0,2,0,20,1]]}
        with self.assertRaises(ValueError):routing.solve(d,1)
    def test_two_period_recipe_accounts_for_purchases(self):
        d={'months':['a','b'],'oils':['VEG','OIL3'],'purchase_cost':[[2,10],[10,2]],'hardness':[5,5],'price':20,'init_store':0,'target_store_per_oil':0,'max_store_per_oil':10,'holding_cost':1,'veg_cap':2,'oil_cap':2,'min_hardness':4,'max_hardness':6,'min_consume':1,'max_ingredients':2}
        r=production.blending(d,2);self.assertTrue(check('blending',d,r)['passed']);self.assertEqual(r['status'],'optimal')
        r['witness']['use'][0][1]=0;self.assertFalse(check('blending',d,r)['passed'])
    def test_shared_machine_counterfactual(self):
        d={'months':['a','b'],'products':['p'],'machines':['borer'],'max_sales':[[10],[10]],'processing_hours':[[1]],'installed':[1],'down_req':[1],'profit_per_sold_unit':[3],'holding_cost':1,'max_inventory':0,'store_target':0,'hours_per_month':10}
        r=production.factory(d,2);self.assertEqual(r['objective'],30);self.assertEqual(r['witness']['incremental_profit'],30);self.assertTrue(check('production',d,r)['passed'])
    def test_one_stage_recursion_matches_analytic_quantile(self):
        from scipy.special import ndtri
        d={'node_order_upstream_to_downstream':[1],'echelon_holding_cost':{'1':2},'local_holding_cost':{'1':2},'shipment_lead_time':{'1':2},'stockout_cost':8,'per_period_normal_demand_mean':3,'per_period_normal_demand_sd':1,'baseline_echelon_levels':{'1':6}}
        r=multiechelon.solve(d,2);expected=6+np.sqrt(2)*ndtri(.8);self.assertAlmostEqual(r['witness']['echelon_levels']['1'],expected,4);self.assertGreaterEqual(len(r['witness']['convergence']),2)

if __name__=='__main__':unittest.main()

"""Independent small optima, material-flow replay and portable output behavior."""
import copy,itertools,json,tempfile,unittest,warnings
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from scm.facility_bounds import replay_bound,strengthen
from scm.optimization_checks import check
from scm.routing import solve as route
from scm.chain_flow import solve as chain,validate,prepare
from scm.optimization_delivery import export_xlsx,write_html

ROOT=Path(__file__).resolve().parents[1]

class Release31Tests(unittest.TestCase):
    def test_all_arc_dual_is_below_enumerated_optimum(self):
        c=np.array([[3,8,2],[5,2,7]],float);f=np.array([4,3,5.]);dem=np.array([4,3.]);cap=np.array([5,4,6.]);opt=float('inf')
        for flags in itertools.product([0,1],repeat=3):
            ids=np.flatnonzero(flags)
            if not len(ids):continue
            k=len(ids);eq=np.kron(np.eye(2),np.ones((1,k)));ub=np.hstack([np.eye(k)*x for x in dem])
            r=linprog(c[:,ids].ravel(),A_eq=eq,b_eq=[1,1],A_ub=ub,b_ub=cap[ids],bounds=(0,1),method='highs')
            if r.success:opt=min(opt,float(r.fun+f[ids].sum()))
        rng=np.random.default_rng(42)
        for trial in range(50):self.assertLessEqual(replay_bound(c,f,dem,cap,rng.normal(5,8,2),-rng.random(3)*3),opt+1e-7)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore');proof=strengthen(c,f,dem,cap,[[1,1,1],[2,2,1]],1)
        self.assertTrue(proof['all_original_arcs_priced']);self.assertLessEqual(proof['valid_bound'],opt+1e-7);self.assertGreater(proof['valid_bound'],0)
        with self.assertRaises(ValueError):replay_bound(c,f,dem,cap,[1,1],[0,1,0])

    def test_fractional_wide_window_route_has_exact_small_optimum(self):
        d={'max_vehicles':2,'vehicle_capacity':2,'customers_including_depot':[[0,0,0,0,0,100,0],[1,1,0,1.25,0,20,.5],[2,2,0,.75,10,30,.75],[3,-1,0,1.25,0,20,.5],[4,-2,0,.75,10,30,.75]]}
        with warnings.catch_warnings():warnings.simplefilter('ignore');r=route(d,1.2,17)
        self.assertTrue(check('routing',d,r)['passed']);self.assertEqual(len(r['witness']['routes']),2);self.assertAlmostEqual(r['objective'],8,6)

    def test_chain_delay_changes_cost_and_materials_stay_balanced(self):
        d=json.loads((ROOT/'assets/operations/chain.json').read_text());base=chain(d,{'name':'base'},2);late=chain(d,d['scenarios'][0],2);blocked=chain(d,d['scenarios'][1],2)
        self.assertTrue(base['validation']['passed']);self.assertTrue(late['validation']['passed']);self.assertTrue(blocked['validation']['passed'])
        self.assertLess(base['objective'],late['objective']);self.assertLess(late['objective'],blocked['objective']);self.assertEqual(base['metrics']['end_backlog_units'],0);self.assertGreater(blocked['metrics']['backlog_unit_days'],0)
        altered=copy.deepcopy(base);altered['witness']['stock'][0][0][0]+=1
        self.assertFalse(validate(d,{},altered)['passed'])

    def test_chain_never_uses_delayed_purchase_early(self):
        d=json.loads((ROOT/'assets/operations/chain.json').read_text());r=chain(d,d['scenarios'][1],2)
        p=np.array(r['witness']['production']);self.assertTrue(np.all(abs(p[:2])<1e-8));self.assertEqual(r['witness']['purchase_qty']['finished_emergency'],0)

    def test_chain_rejects_currency_cycles_and_unknown_changes(self):
        d=json.loads((ROOT/'assets/operations/chain.json').read_text());bad=copy.deepcopy(d);bad['purchases'][0]['currency']='USD'
        with self.assertRaises(ValueError):prepare(bad)
        with self.assertRaises(ValueError):prepare(d,{'purchase_delays':{'missing':2}})
        bad=copy.deepcopy(d);bad['production'][0]['inputs']={'成品':1}
        with self.assertRaises(ValueError):prepare(bad)
        bad=copy.deepcopy(d);bad['purchases'][0].update(fixed_qty=2,max_qty=2,moq=3)
        with self.assertRaisesRegex(ValueError,'raw_regular.*fixed_qty.*moq'):prepare(bad)

    def test_commitment_outside_horizon_is_not_initial_stock(self):
        d={'currency':'CNY','dates':['2026-01-01','2026-01-02'],'locations':['a'],'items':{'x':{'holding_cost':0,'backlog_cost':1}},'demand':[{'date':'2026-01-01','location':'a','item':'x','qty':1}],'purchases':[{'id':'p','item':'x','location':'a','order_date':'2025-12-30','arrival_date':'2026-01-03','max_qty':1,'fixed_qty':1,'unit_cost':2}]}
        r=chain(d,{},1);self.assertEqual(r['metrics']['delivered_units'],0);self.assertEqual(r['metrics']['end_backlog_units'],1);self.assertEqual(r['metrics']['committed_units_receiving_after_horizon'],1);self.assertAlmostEqual(r['objective'],4)

    def test_optimization_export_preserves_values_and_blocks_formulas(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);r={'kind':'facility','engine_version':'3.1.0','status':'feasible','objective':12.5,'witness':{'allocations':[[1,2,.5]],'label':'=HYPERLINK("http://example.com")'},'validation':{'passed':True},'evidence':{'bound_scope':'global'}}
            (p/'report.json').write_text(json.dumps(r));export_xlsx(p/'report.json',p/'result.xlsx');write_html(r,p/'report.html');w=load_workbook(p/'result.xlsx',data_only=False)
            values=[c for s in w for row in s for c in row];self.assertFalse(any(c.data_type=='f' for c in values));self.assertTrue(any(c.value==.5 for c in values));self.assertTrue(any(str(c.value).startswith("'=HYPERLINK") for c in values));self.assertIn('下载完整结果JSON',(p/'report.html').read_text());w.close()
            with self.assertRaises(ValueError):export_xlsx(p/'report.json',p/'result.xlsx')

    def test_adoption_retains_cheaper_existing_facility(self):
        import hashlib
        from scm.optimization_review import review
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);d={'capacity':[2,2],'fixed_cost':[1,3],'demand':[1],'allocation_cost_all_customer_demand':[[1,3]]};(p/'input.json').write_text(json.dumps(d));h=hashlib.sha256((p/'input.json').read_bytes()).hexdigest()
            def report(i,c):return {'kind':'facility','input_sha256':h,'objective':c,'witness':{'open_warehouses':[i],'allocations':[[i,1,1]]}}
            (p/'old.json').write_text(json.dumps(report(1,2)));(p/'new.json').write_text(json.dumps(report(2,6)));r=review(p/'input.json',p/'old.json',p/'new.json',p/'review');self.assertEqual(r['comparison'],'worse');self.assertEqual(r['selected'],'baseline');self.assertEqual(json.loads((p/'review/accepted_plan.json').read_text())['objective'],2)
            bad=report(1,0);(p/'bad.json').write_text(json.dumps(bad));r=review(p/'input.json',p/'old.json',p/'bad.json',p/'invalid-review');self.assertEqual(r['selected'],'baseline');self.assertFalse(r['checks']['candidate']['feasible'])

    def test_adoption_rejects_different_inputs(self):
        from scm.optimization_review import review
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'input.json').write_text('{}');r={'kind':'routing','input_sha256':'different','objective':1,'witness':{'routes':[[1]]}};(p/'old.json').write_text(json.dumps(r));(p/'new.json').write_text(json.dumps(r))
            with self.assertRaises(ValueError):review(p/'input.json',p/'old.json',p/'new.json',p/'review')

    def test_independent_benchmark_detects_infeasible_mutation(self):
        from scm.benchmark_checks import grade,compare
        d={'capacity':[2],'fixed_cost':[1],'demand':[1],'allocation_cost_all_customer_demand':[[1]]};r={'objective':2,'witness':{'open_warehouses':[1],'allocations':[[1,1,1]]}};g=grade(d,r,{'objective':2});self.assertTrue(g['target_met']);bad=copy.deepcopy(r);bad['witness']['allocations'][0][2]=.5;b=grade(d,bad,{'objective':2});self.assertFalse(b['feasible']);self.assertEqual(compare(g,b,'facility'),'worse')

    def test_chain_cli_returns_failure_for_infeasible_plan(self):
        import contextlib,io
        from supply_chain import main
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);d={'currency':'CNY','dates':['2026-01-01'],'locations':['a'],'items':{'x':{'holding_cost':0,'backlog_cost':1}},'demand':[{'date':'2026-01-01','item':'x','location':'a','qty':1}],'purchases':[],'end_backlog_cap':0};(p/'input.json').write_text(json.dumps(d))
            with contextlib.redirect_stdout(io.StringIO()):status=main(['chain','--input',str(p/'input.json'),'--out',str(p/'out'),'--seconds','1'])
            self.assertEqual(status,2);result=json.loads((p/'out/report.json').read_text());self.assertEqual(result['status'],'blocked');self.assertEqual(result['feasible_scenarios'],0)

if __name__=='__main__':unittest.main()

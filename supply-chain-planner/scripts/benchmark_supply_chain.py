#!/usr/bin/env python3
"""Fetch pinned public instances, compare two engines and expose regressions."""
import argparse,concurrent.futures,hashlib,json,os,subprocess,sys,time,urllib.request
from pathlib import Path
SKILL=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(path)
def facility(raw,capacity=None):
    v=raw.split();m,n=map(int,v[:2]);at=2;cap=[];fixed=[];demand=[];cost=[]
    for i in range(m):cap.append(float(capacity if v[at].lower()=='capacity' else v[at]));fixed.append(float(v[at+1]));at+=2
    for j in range(n):demand.append(float(v[at]));cost.append([float(x) for x in v[at+1:at+1+m]]);at+=m+1
    if at!=len(v):raise ValueError('Unexpected OR-Library token count')
    return {'m':m,'n':n,'capacity':cap,'fixed_cost':fixed,'demand':demand,'allocation_cost_all_customer_demand':cost}
def routing(raw):
    rows=[];fleet=None
    for line in raw.splitlines():
        p=line.split()
        if len(p)==2 and all(x.isdigit() for x in p) and fleet is None:fleet=list(map(int,p))
        if len(p)==7:
            try:a=list(map(float,p))
            except ValueError:continue
            if a[0]==len(rows):rows.append(a)
    if fleet is None or len(rows)!=101:raise ValueError('Expected the full 100-customer Solomon instance')
    return {'max_vehicles':fleet[0],'vehicle_capacity':fleet[1],'customers_including_depot':rows}
def fetch(out):
    root=Path(out)
    if root.exists():raise ValueError('Choose a new dataset destination')
    manifest=json.loads((SKILL/'assets/evaluation/public-optimization.json').read_text());root.mkdir(parents=True);(root/'raw').mkdir();(root/'normalized').mkdir();sources={c['raw_file']:c for c in manifest['cases']}
    def download(row):
        req=urllib.request.Request(row['raw_url'],headers={'User-Agent':'supply-chain-planner/3.1'})
        with urllib.request.urlopen(req,timeout=45) as response:raw=response.read()
        if hashlib.sha256(raw).hexdigest()!=row['raw_sha256']:raise ValueError('Public source changed: '+row['raw_file'])
        (root/'raw'/row['raw_file']).write_bytes(raw)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(download,sources.values()))
    for c in manifest['cases']:
        raw=(root/'raw'/c['raw_file']).read_text();d=facility(raw,c['reference'].get('capacity_variant')) if c['kind']=='facility' else routing(raw);p=root/c['input'];p.write_text(json.dumps(d,separators=(',',':')))
        if sha(p)!=c['input_sha256']:raise ValueError('Normalized data changed: '+c['id'])
    write(root/'manifest.json',manifest);return {'instances':len(manifest['cases']),'source_files':len(sources),'data':str(root)}
def worker(argv):
    package,kind,data,out,seconds,seed=argv
    sys.path.insert(0,str(Path(package)/'scripts'))
    from scm.optimization import run
    r=run(kind,data,out,float(seconds),int(seed));print(json.dumps({'status':r['status'],'objective':r['objective']}))
def compare(args):
    from scm.benchmark_checks import grade,compare as change
    root=Path(args.out);data=Path(args.data).resolve();manifest=json.loads((data/'manifest.json').read_text());cases=[c for c in manifest['cases'] if args.subset=='all' or c['split']==args.subset];seeds=list(map(int,args.seeds.split(',')));packages={'baseline':Path(args.baseline).resolve(),'candidate':Path(args.candidate).resolve()}
    if not seeds or len(set(seeds))!=len(seeds):raise ValueError('Use unique seed values')
    fingerprint={name:{str(p.relative_to(package)):sha(p) for p in (package/'scripts').rglob('*.py') if '__pycache__' not in str(p)} for name,package in packages.items()}
    config={'source_hashes':fingerprint,'manifest_sha256':sha(data/'manifest.json'),'seconds':args.seconds,'seeds':seeds,'subset':args.subset}
    if root.exists():
        if not args.resume or json.loads((root/'config.json').read_text())!=config:raise ValueError('Output exists or resume configuration changed')
    else:root.mkdir(parents=True);write(root/'config.json',config)
    rows=[]
    for index,(case,seed) in enumerate((c,s) for c in cases for s in seeds):
        path=data/case['input']
        if sha(path)!=case['input_sha256']:raise ValueError('Input fingerprint changed')
        row={'id':case['id'],'kind':case['kind'],'split':case['split'],'seed':seed,'arms':{}}
        for name in (['baseline','candidate'] if index%2==0 else ['candidate','baseline']):
            folder=root/(case['id']+'_'+str(seed))/name;metadata=folder/'process.json'
            if not metadata.exists():
                start=time.monotonic()
                try:
                    p=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(packages[name]),case['kind'],str(path),str(folder),str(args.seconds),str(seed)],capture_output=True,text=True,env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'},timeout=args.seconds+35)
                    proc={'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'wall_seconds':time.monotonic()-start}
                except subprocess.TimeoutExpired:proc={'returncode':-1,'error':'Worker timeout'}
                write(metadata,proc)
            result=json.loads((folder/'report.json').read_text()) if (folder/'report.json').exists() else {'objective':None}
            row['arms'][name]=grade(json.loads(path.read_text()),result,case['reference'])
        row['change']=change(row['arms']['baseline'],row['arms']['candidate'],case['kind']);row['target_regression']=row['arms']['baseline']['target_met'] and not row['arms']['candidate']['target_met'];rows.append(row);write(root/'results.json',rows)
        print(json.dumps({'completed_pairs':len(rows),'id':case['id'],'change':row['change']},ensure_ascii=False),flush=True)
    summary={'pairs':len(rows),'target':{name:sum(r['arms'][name]['target_met'] for r in rows) for name in packages},'changes':{name:sum(r['change']==name for r in rows) for name in ['better','tie','worse','both_failed']},'target_regressions':[r['id']+'_'+str(r['seed']) for r in rows if r['target_regression']],'note':'Native-engine paired comparison; references remain outside optimizer inputs. Same time allowance, sequential one-thread subprocesses; no speed or statistical significance claim.'}
    write(root/'summary.json',summary);return summary
def main():
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(sys.argv[2:]);return
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='command',required=True);f=subs.add_parser('fetch');f.add_argument('--out',required=True);c=subs.add_parser('compare');c.add_argument('--data',required=True);c.add_argument('--baseline',required=True);c.add_argument('--candidate',default=str(SKILL));c.add_argument('--out',required=True);c.add_argument('--seconds',type=float,default=10);c.add_argument('--seeds',default='17');c.add_argument('--subset',choices=['all','development','holdout'],default='all');c.add_argument('--resume',action='store_true');args=p.parse_args()
    if args.command=='compare' and (not math_is_positive(args.seconds)):p.error('seconds must be finite and positive')
    result=fetch(args.out) if args.command=='fetch' else compare(args);print(json.dumps(result,ensure_ascii=False))
def math_is_positive(x):
    import math
    return math.isfinite(x) and x>0
if __name__=='__main__':main()

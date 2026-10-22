"""Portable HTML and formula-safe XLSX for complete optimization decisions."""
import html
import json
import os
import tempfile
from pathlib import Path


def flatten(value,path=''):
    if isinstance(value,dict):
        for key,item in value.items():yield from flatten(item,(path+'.' if path else '')+str(key))
    elif isinstance(value,list):
        for index,item in enumerate(value):yield from flatten(item,path+'['+str(index)+']')
    else:yield path,value


def write_html(result,path,data=None):
    path=Path(path);esc=lambda x:html.escape(str(x));kind=result['kind']
    def table(headers,rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    title={'facility':'容量仓网方案','routing':'时间窗配送方案','blending':'采购与配方生产','production':'共享设备与检修计划','serial':'串联库存方案','chain':'采购—生产—库存—调拨情景'}[kind]
    if kind=='chain':
        rows=[[r['name'],r['status'],r['objective'],r.get('metrics',{}).get('end_backlog_units'),r.get('metrics',{}).get('backlog_unit_days'),r.get('validation',{}).get('passed',False)] for r in result['scenarios']]
        main=table(['情景','求解状态','模型成本 / '+result['currency'],'期末欠交 / 件','欠交 / 件·日','约束复算通过'],rows)
        main+='<p>各情景共享同一总计算预算。费用包含模型内采购、生产、调拨、持有与欠交；未纳入税费、残值或真实运营收益。</p>'
        for r in result['scenarios']:
            if 'witness' not in r:continue
            w=r['witness'];axes=r['axes'];daily=[]
            for t,date in enumerate(axes['dates']):
                delivered=sum(sum(v) for v in w['delivered'][t]);backlog=sum(sum(v) for v in w['backlog'][t]);stock=sum(sum(v) for v in w['stock'][t]);daily.append([date,round(delivered,6),round(backlog,6),round(stock,6)])
            main+='<h2>'+esc(r['name'])+'</h2>'+table(['日期','交付 / 件','日末欠交 / 件','日末库存 / 件'],daily)
            main+='<p>期末之后到货的已承诺采购：'+esc(r['metrics']['committed_units_receiving_after_horizon'])+' 件。缺少责任人时应由业务方补充，不自动派单。</p>'
    else:
        e=result.get('evidence',{});v=result.get('validation',{});bound=e.get('best_valid_bound');gap=e.get('relative_gap')
        main=table(['项目','结果'],[['状态',result.get('status')],['目标值',result.get('objective')],['约束复算',v.get('passed')],['原问题有效下界',bound],['有效界差',None if gap is None else str(round(100*gap,6))+'%'],['界的范围',e.get('bound_scope',e.get('pool_bound_scope','见完整证据'))]])
        main+='<p>feasible 表示已得到可行方案；候选仓或路线池内最优不能扩大为原问题全局最优。数值收敛也不等于精确解析证明。</p>'
        w=result.get('witness',{})
        if kind=='facility':main+=table(['仓库','客户','该客户需求比例'],w.get('allocations',[])[:200])+'<p>页面预览前200条，完整分配保留在结果JSON及Excel导出中。</p>'
        elif kind=='routing':main+=table(['车辆','有序客户访问列表'],[[i+1,' → '.join(map(str,r))] for i,r in enumerate(w.get('routes',[]))])
        else:main+=table(['决策路径','值'],list(flatten(w))[:200])+'<p>页面预览前200项，完整矩阵可下载。</p>'
    payload=json.dumps(result,ensure_ascii=False,separators=(',',':')).replace('</',r'<\/')
    css='body{font:15px/1.65 system-ui,sans-serif;background:#f1f5f7;color:#173247;margin:0}main{max-width:1120px;margin:30px auto;background:white;padding:32px;border-radius:14px}h1{font-size:28px}h2{font-size:20px;margin-top:30px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;text-align:left;border-bottom:1px solid #d9e2e8}th{background:#eaf2f5}.scroll{overflow:auto}p{color:#526775}button{background:#087e82;color:white;border:0;padding:11px 20px;border-radius:7px;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;background:#102b3b;color:white;padding:18px}@media(max-width:700px){main{margin:10px;padding:18px}}'
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+css+'</style><main><h1>'+title+'</h1><p>Supply Chain Planner '+esc(result.get('engine_version',''))+' · 输入 SHA256 '+esc(result.get('input_sha256',''))+'</p>'+main+'<button id="download">下载完整结果JSON</button><details><summary>计算范围与完整证据</summary><pre id="detail"></pre></details></main><script id="data" type="application/json">'+payload+'</script><script>const r=JSON.parse(document.getElementById("data").textContent);document.getElementById("detail").textContent=JSON.stringify(r.scope||r.evidence,null,2);document.getElementById("download").onclick=()=>{const u=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:"application/json"})),a=document.createElement("a");a.href=u;a.download="report.json";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};</script></html>'
    fd,tmp=tempfile.mkstemp(prefix='.report-',suffix='.html',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(page);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def export_xlsx(input_path,out):
    from openpyxl import Workbook
    target=Path(out)
    if target.exists():raise ValueError('Output workbook already exists')
    if target.suffix.lower()!='.xlsx':raise ValueError('Use a new .xlsx destination')
    result=json.loads(Path(input_path).read_text());wb=Workbook(write_only=True)
    sheets={k:wb.create_sheet(k) for k in ['Summary','Decisions','Evidence']};counts={k:1 for k in sheets}
    for sheet in sheets.values():sheet.freeze_panes='A2';sheet.append(['path','value'])
    for key,value in flatten(result):
        category='Decisions' if 'witness.' in key else 'Evidence' if 'evidence.' in key else 'Summary'
        def safe(v):
            if isinstance(v,str) and v.startswith(('=','+','-','@')):return "'"+v
            return v
        if isinstance(value,str) and len(value)>32000:chunks=[value[i:i+32000] for i in range(0,len(value),32000)]
        else:chunks=[value]
        for i,chunk in enumerate(chunks):
            counts[category]+=1
            if counts[category]>1048576:raise ValueError('Excel row limit exceeded; use complete JSON')
            sheets[category].append([safe(key if len(chunks)==1 else key+'#part'+str(i+1)),safe(chunk)])
    target.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix='.optimization-',suffix='.xlsx',dir=target.parent);os.close(fd)
    try:wb.save(tmp);os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return {'path':str(target),'sheets':counts,'formulas':0,'scope':'Calculated values and complete decision paths; changing cells does not rerun the optimizer'}

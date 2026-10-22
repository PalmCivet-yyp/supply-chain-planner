// Run a copied builder from a private tmp dir linked to the primary runtime modules.
// Read the session's Spreadsheets skill and run its creation marker before authoring.
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const [inputDir, planDir, backtestDir, outputFile, previewDir] = process.argv.slice(2);
if (!previewDir) throw Error('usage: export_workbook.mjs INPUT_DIR PLAN_DIR BACKTEST_DIR OUTPUT.xlsx PREVIEW_DIR');
try {await fs.access(outputFile); throw Error('output exists');} catch(e) {if (e.code !== 'ENOENT') throw e;}
const plan = JSON.parse(await fs.readFile(path.join(planDir,'report.json'),'utf8'));
const bt = JSON.parse(await fs.readFile(path.join(backtestDir,'report.json'),'utf8'));
const currency=plan.parameters.currency || '未指定币种';
const present=s=>typeof s==='string'?s.replaceAll('CNY',currency):s;
const readCode = "import csv,json,sys,pathlib; p=pathlib.Path(sys.argv[1]); print(json.dumps({n:list(csv.DictReader((p/(n+'.csv')).open(encoding='utf-8-sig',newline=''))) for n in ('items','demand','inbound')}))";
const raw = JSON.parse(execFileSync(process.env.CODEX_PRIMARY_RUNTIME_PYTHON || 'python3', ['-c',readCode,inputDir], {maxBuffer:32*1024*1024,encoding:'utf8'}));
const wb = Workbook.create();
const names=['运行概览','补货建议','回测结果','运行参数','items','demand','inbound'];
const sheets=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const col = n => {let s=''; for(n++;n;n=Math.floor((n-1)/26)) s=String.fromCharCode(65+(n-1)%26)+s; return s;};
const fontFamily=process.env.SCM_FONT_FAMILY || 'Noto Sans SC';
const font={name:fontFamily,size:10,color:'#243145'};
const asDate=v=>v?new Date(v+'T00:00:00Z'):null;
function base(sheet, endRow, endCol, header=1){
  const r=sheet.getRange(`A1:${col(endCol-1)}${endRow}`);
  r.format.font=font; r.format.rowHeight=23; r.format.columnWidth=18;
  r.format.verticalAlignment='center'; sheet.showGridLines=false;
  const h=sheet.getRange(`A${header}:${col(endCol-1)}${header}`);
  h.format={fill:'#233D61',font:{name:fontFamily,size:10,bold:true,color:'#FFFFFF'},rowHeight:30,horizontalAlignment:'center',verticalAlignment:'center'};
  if(endRow>25) sheet.freezePanes.freezeRows(header);
}
function writeTable(name,headers,rows,start=1){
  const s=sheets[name];
  s.getRange(`A${start}:${col(headers.length-1)}${start+rows.length}`).values=[headers.map(present),...rows];
  base(s,start+rows.length,headers.length,start);
  return s;
}
function identifiers(sheet, column, values){
  // Keep stored IDs as strings. Explicit zero masks also preserve zeros in previews.
  let start=2,lastFormat=null;
  for(let i=0;i<=values.length;i++){
    const v=String(values[i]??'');
    const format=i===values.length?null:/^0\d{1,19}$/.test(v)?'0'.repeat(v.length):'@';
    if(i===0){lastFormat=format;continue;}
    if(format!==lastFormat){sheet.getRange(`${column}${start}:${column}${i+1}`).format.numberFormat=lastFormat;start=i+2;lastFormat=format;}
  }
}
const pHeaders=['SKU','仓库','状态','优先级','需求类型','预测方法','原始缺口/件','无预算建议/件','建议数量/件','单位成本/CNY','采购货值/CNY','基本到货日','最晚情景到货日','首次基准短缺日','到货前未即时交付/件','设计缓冲/件'];
const stateLabel={ready_for_review:'可进入复核',scenario_only:'条件情景',blocked:'需补数据'};
const pRows=plan.items.map(p=>[p.sku,p.location,stateLabel[p.recommendation_state],p.priority||'P0',p.segment?.label||'',p.forecast_method||'',p.raw_gap??null,p.unconstrained_order_qty,p.suggested_order_qty,p.unit_cost,null,asDate(p.base_arrival_date),asDate(p.latest_scenario_arrival_date),asDate(p.first_shortage_date_baseline),p.new_unfilled_units_before_base_arrival??null,p.safety_stock??null]);
const ps=writeTable('补货建议',pHeaders,pRows);
ps.tabColor='#233D61';
ps.getRange(`A2:B${pRows.length+1}`).format.numberFormat='@';
identifiers(ps,'A',pRows.map(r=>r[0]));
ps.getRange(`C1:C${pRows.length+1}`).format.columnWidth=25;
ps.getRange(`G2:K${pRows.length+1}`).format.numberFormat='#,##0.00';
ps.getRange(`G1:P${pRows.length+1}`).format.columnWidth=24;
ps.getRange(`L2:N${pRows.length+1}`).format.numberFormat='yyyy-mm-dd';
for(let i=2;i<pRows.length+2;i++) ps.getRange(`K${i}`).formulas=[[`=IF(AND(ISNUMBER(I${i}),ISNUMBER(J${i})),I${i}*J${i},"")`]];
ps.getRange(`I2:J${pRows.length+1}`).format.fill='#FFF4D1';
ps.getRange(`I2:I${pRows.length+1}`).dataValidation={rule:{type:'whole',operator:'greaterThanOrEqual',formula1:0}};
ps.getRange(`I2:I${pRows.length+1}`).conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{font:{bold:true,color:'#1B5FA8'}}});
const bHeaders=['政策','交期种子','即时满足率','复核周期无新增缺口比例','完整复核周期','平均库存/项日','持有费用/CNY','缺货费用/CNY','下单费用/CNY','运营成本/CNY','采购现金/CNY','失销量/件','欠单件日','期末库存/件','期末欠单/件','期末在途/件'];
const br=bt.test_runs.map(r=>[r.policy,r.seed,r.immediate_fill_rate,r.review_cycle_no_new_shortage_rate,r.completed_review_cycles,r.average_stock_per_item_day,r.holding_cost,r.shortage_cost,r.ordering_cost,r.modeled_operating_cost,r.purchase_cash,r.lost_units,r.backlog_unit_days,r.ending_stock,r.ending_backlog,r.ending_pipeline_units]);
const bs=writeTable('回测结果',bHeaders,br);
bs.getRange(`A1:A${br.length+1}`).format.columnWidth=27;
bs.getRange(`B1:P${br.length+1}`).format.columnWidth=25;
bs.getRange(`C2:D${br.length+1}`).format.numberFormat='0.0%';
bs.getRange(`F2:K${br.length+1}`).format.numberFormat='#,##0.00';
let provenance=null; try{provenance=JSON.parse(await fs.readFile(path.join(inputDir,'provenance.json'),'utf8'));}catch{}
const sourceLabel=provenance?.synthetic?`模拟数据；seed=${provenance.seed}`:'用户输入；性质以源文件为准';
const settings=[['数据性质',sourceLabel],['快照日期',plan.parameters.as_of],['引擎版本',plan.engine_version],['缺货模型',plan.parameters.shortage_mode],['预算/CNY',plan.parameters.budget],['单次收货件数上限',plan.parameters.capacity_units],['历史窗口/日',plan.parameters.history_days],['交期情景',JSON.stringify(plan.parameters.lead_time_scenarios)],['训练期',bt.split.training.join(' 至 ')],['验证期',bt.split.validation.join(' 至 ')],['封存测试期',bt.split.test.join(' 至 ')],['初始库存情景',`${bt.initial_state.stock_days_from_training_mean28}天训练均值，初始欠单/在途为0`],['基线政策',bt.selected_baseline.name],['候选政策',bt.selected_adaptive.name],['采用建议',bt.adoption_gate?.recommendation||'retain_baseline'],['缺货成本单位',plan.parameters.shortage_mode==='lost_sales'?'CNY/失销件':'CNY/欠单件/日'],['成本口径','运营成本=持有+缺货+下单费用；采购现金单列'],['重算范围','货值公式可编辑；改输入后重新运行引擎生成计划'],['数据来源',provenance?.synthetic?'内置模拟生成器；不代表真实业务效果':'用户提供的CSV文件；核对原文件与运行哈希']].map(r=>r.map(present));
const cs=writeTable('运行参数',['参数','取值'],settings);
cs.getRange(`A1:A${settings.length+1}`).format.columnWidth=28;
cs.getRange(`B1:B${settings.length+1}`).format.columnWidth=105;
cs.tabColor='#60738D';
const numeric=new Set(['on_hand','reserved','backorders','lead_time_days','review_period_days','service_level','moq','pack_size','unit_cost','holding_cost_per_unit_day','shortage_cost','order_fixed_cost','demand_qty','stockout','qty']);
for(const name of ['items','demand','inbound']){
  const rows=raw[name]; const headers=rows.length?Object.keys(rows[0]):['order_id','sku','location','qty','eta','status'];
  const values=rows.map(r=>headers.map(h=>r[h]===''?null:numeric.has(h)?Number(r[h]):['date','eta'].includes(h)?asDate(r[h]):r[h]));
  const s=writeTable(name,headers,values); s.freezePanes.freezeRows(1);
  headers.forEach((h,j)=>{
    const range=s.getRange(`${col(j)}2:${col(j)}${Math.max(2,values.length+1)}`);
    if(['sku','location','order_id'].includes(h)) identifiers(s,col(j),values.map(r=>r[j]));
    else if(h==='service_level') range.format.numberFormat='0.0%';
    else if(['date','eta'].includes(h)) range.format.numberFormat='yyyy-mm-dd';
    else if(numeric.has(h)) range.format.numberFormat=h.includes('cost')?'0.00':'#,##0';
    if(h.length>15) s.getRange(`${col(j)}1:${col(j)}${values.length+1}`).format.columnWidth=31;
    if(h==='eta') s.getRange(`${col(j)}1:${col(j)}${values.length+1}`).format.columnWidth=22;
  });
}
const ov=sheets['运行概览'];
ov.getRange('A2').values=[['供应链决策工具 2.0']];
ov.getRange('A3').values=[[`${sourceLabel}；${plan.items.length}个SKU/仓库组合，${raw.demand.length}条需求日记录。`]];
ov.getRange('A5:D5').values=[['资源核对','使用量','上限','余额']];
ov.getRange('A6:A7').values=[[present('采购货值/CNY')],['订购件数']];
ov.getRange('B6:D6').formulas=[[`=SUM('补货建议'!K2:K${pRows.length+1})`,`='运行参数'!B6`,'=C6-B6']];
ov.getRange('B7:D7').formulas=[[`=SUM('补货建议'!I2:I${pRows.length+1})`,`='运行参数'!B7`,'=C7-B7']];
ov.getRange('A10:D10').values=[['封存测试均值','基线政策','候选政策','候选减基线']];
ov.getRange('A11:A12').values=[[present('运营成本/CNY')],['即时满足率']];
ov.getRange('F10:G12').values=[['政策标识','模型'],['基线',bt.selected_baseline.name],['候选',bt.selected_adaptive.name]];
const last=br.length+1;
for(const [row,source] of [[11,'J'],[12,'C']]){
  ov.getRange(`B${row}`).formulas=[[`=AVERAGEIF('回测结果'!A2:A${last},$G$11,'回测结果'!${source}2:${source}${last})`]];
  ov.getRange(`C${row}`).formulas=[[`=AVERAGEIF('回测结果'!A2:A${last},$G$12,'回测结果'!${source}2:${source}${last})`]];
  ov.getRange(`D${row}`).formulas=[[`=C${row}-B${row}`]];
}
ov.getRange('A15').values=[['采用建议']];
ov.getRange('F14:G14').values=[['最低满足率',bt.adoption_gate.minimum_immediate_fill_rate]];
ov.getRange('B15').formulas=[['=IF(AND(D11<0,D12>=0,C12>=G14),"进入业务复核","保留基线")']];
ov.getRange('G14').format.numberFormat='0.0%';
ov.getRange('A18').values=[['数量、日期与假设详见补货建议和运行参数。蓝色数量与黄色输入可用于货值试算。']];
ov.getRange('A19').values=[['改动源表后需重新运行引擎；该工作簿不会在Excel内重新求解预测或整数优化。']];
ov.getRange('A20').values=[['运营成本未含税、运费、残值及测试期后影响。种子范围不是业务收益置信区间。']];
base(ov,20,7,5); ov.tabColor='#233D61';
ov.getRange('A2:G2').format.font={name:fontFamily,size:15,bold:true,color:'#233D61'};
ov.getRange('A2:G3').format.rowHeight=28;
ov.getRange('A1:A20').format.columnWidth=30;
ov.getRange('B1:D20').format.columnWidth=22;
ov.getRange('F1:F20').format.columnWidth=18;
ov.getRange('G1:G20').format.columnWidth=27;
ov.getRange('A10:D10').format={fill:'#233D61',font:{name:fontFamily,size:10,bold:true,color:'#FFFFFF'},rowHeight:30,horizontalAlignment:'center'};
ov.getRange('B6:D6').format.numberFormat='#,##0.00';
ov.getRange('B11:D11').format.numberFormat='#,##0.00';
ov.getRange('B12:D12').format.numberFormat='0.00%';
ov.getRange('D6:D7').conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#FDE8E6',font:{color:'#A12D20',bold:true}}});
ov.getRange('B15:D15').format.font={name:fontFamily,size:11,bold:true,color:'#8B451F'};
// Check edit propagation, then restore before final calculation and export.
const originalQty=pRows[0][8], before=ov.getRange('B6').values[0][0];
ps.getRange('I2').values=[[originalQty+1]];
const after=ov.getRange('B6').values[0][0];
if(Math.abs(after-before-pRows[0][9])>1e-6) throw Error('purchase-value formula did not respond to order edit');
ps.getRange('I2').values=[[originalQty]];
wb.recalculate();
const check=await wb.inspect({kind:'table',range:'运行概览!A5:D15',include:'values,formulas',tableMaxRows:11,tableMaxCols:4,maxChars:2500});
console.log(check.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},summary:'formula error scan',maxChars:2000});
console.log(errors.ndjson);
const expectedSpend=plan.items.reduce((s,p)=>s+(p.estimated_order_goods_value||0),0);
if(Math.abs(ov.getRange('B6').values[0][0]-expectedSpend)>1e-6) throw Error('summary spend reconciliation failed');
if(Math.abs(ov.getRange('D11').values[0][0]-bt.paired_comparison.mean_operating_cost_difference)>1e-6) throw Error('backtest summary reconciliation failed');
await fs.mkdir(previewDir,{recursive:true});
for(const name of names){
  const range=name==='运行概览'?'A1:G21':name==='运行参数'?'A1:B20':name==='补货建议'?'A1:K8':name==='回测结果'?'A1:F8':'A1:F9';
  const preview=await wb.render({sheetName:name,range,scale:1.4,format:'png'});
  await fs.writeFile(path.join(previewDir,`${name}.png`),new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputFile),{recursive:true});
const output=await SpreadsheetFile.exportXlsx(wb); await output.save(outputFile);
console.log(JSON.stringify({output:outputFile,sheets:names.length,inputDemandRows:raw.demand.length,editPropagationChecked:true}));

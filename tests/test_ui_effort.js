'use strict';
// 团队卡片上的「思考等级」：沿用每个模型自己的档位名称；Gemini 首选模型下拉框同系列只列一次。
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('ui.html','utf8').match(/<script>([\s\S]*)<\/script>/)[1];
const nodes={};
const node=id=>nodes[id]||(nodes[id]={innerHTML:'',value:'',style:{},dataset:{},scrollTop:0,classList:{add(){},remove(){},toggle(){}},addEventListener(){},querySelectorAll(){return []},focus(){},contains(){return false}});
const ctx={document:{getElementById:node,addEventListener(){},documentElement:{dataset:{}},querySelectorAll(){return []}},window:{},localStorage:{getItem(){return null}},sessionStorage:{getItem(){return null}},addEventListener(){},matchMedia:()=>({matches:false,addEventListener(){}}),setInterval(){},getSelection:()=>null};
vm.createContext(ctx);
vm.runInContext(source.replace('poll(); setInterval(poll, 1500); setInterval(ticks, 1000);', 'globalThis.ui={set:s=>S=s,effortSelect,modelSelect};'),ctx);
const lv=['Low','Medium','High'];
const backends=lv.map(l=>({spec:'agy:gemini-4-carbon-'+l.toLowerCase(),label:'Gemini 4 Carbon ('+l+')'}))
  .concat(['Low','Medium','High','XHigh'].map(l=>({spec:'agy:gemini-4-hydrogen-'+l.toLowerCase(),label:'Gemini 4 Hydrogen ('+l+')'})))
  .concat([{spec:'agy:gemini-solo',label:'Solo'},
    {spec:'codex',label:'GPT',efforts:[{id:'low',desc:''},{id:'medium',desc:''},{id:'ultra',desc:'delegation'}]},
    {spec:'codex:gpt-6-luna',label:'Luna',efforts:[{id:'low',desc:''},{id:'max',desc:''}]},
    {spec:'dsh',label:'DS'},{spec:'claude:opus',label:'Opus',efforts:['low','medium','high','xhigh','max'].map(id=>({id,desc:''}))}]);
ctx.ui.set({backends,config:{effort:{gpt:'ultra',claude:''},codex_effort_default:'max'},agents:[],calls:[],runs:[]});
const es=(name,chain)=>ctx.ui.effortSelect({name,chain});
let h=es('gemini',['agy:gemini-4-carbon-medium']);
assert.ok(h.includes('data-chain="gemini:0"') && h.includes('data-gem="1"'),'Gemini 用换模型的方式调档位');
assert.ok(/value="agy:gemini-4-carbon-medium" selected>Medium</.test(h),'用 Gemini 自己的写法 Medium');
assert.ok(h.includes('>Low<') && h.includes('>High<') && !h.includes('XHigh'),'只列出这个系列真有的档位');
assert.ok(es('gemini',['agy:gemini-4-hydrogen-high']).includes('>XHigh<'),'Hydrogen 有 XHigh');
assert.ok(es('gemini',['agy:gemini-solo']).includes('不分档位'));
h=es('gpt',['codex']);
assert.ok(h.includes('data-effort="gpt"') && /value="ultra" selected/.test(h) && h.includes('最费额度'),'GPT 用自己的档位名，含 ultra 提示');
assert.ok(h.includes('默认（本机设置：max）'));
h=es('gpt',['codex:gpt-6-luna']);
assert.ok(!h.includes('ultra') && h.includes('value="max"'),'不同 GPT 模型档位不同');
h=es('claude',['claude:opus']);
assert.ok(h.includes('data-effort="claude"') && /value="" selected>默认/.test(h) && h.includes('value="xhigh"'));
assert.ok(es('ds',['dsh']).includes('DeepSeek 不支持调节'));
// 首选模型下拉框：Gemini 每个系列只出现一次，不带档位
h=ctx.ui.modelSelect({name:'gemini',chain:['agy:gemini-4-carbon-high']},0);
assert.equal((h.match(/Carbon/g)||[]).length,1,'Carbon 只列一次');
assert.equal((h.match(/Hydrogen/g)||[]).length,1,'Hydrogen 只列一次');
assert.ok(/value="agy:gemini-4-carbon-high" selected>Gemini 4 Carbon</.test(h),'当前系列保持当前档位');
assert.ok(h.includes('value="agy:gemini-4-hydrogen-medium">Gemini 4 Hydrogen<'),'换系列默认 Medium');
// 备用模型下拉框保留完整列表
assert.ok(ctx.ui.modelSelect({name:'gemini',chain:['agy:x','agy:gemini-4-carbon-high']},1).includes('Gemini 4 Carbon (Low)'));
console.log('ui effort: model-native level names, per-model levels, gemini family merge passed');

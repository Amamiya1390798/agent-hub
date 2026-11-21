'use strict';
// 会审、共享进度板、模板和草稿的界面函数检查（Node 虚拟环境，不需要浏览器）。
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('ui.html','utf8').match(/<script>([\s\S]*)<\/script>/)[1];
function boot(store){
  const nodes={};
  const node=id=>nodes[id]||(nodes[id]={innerHTML:'',value:'',textContent:'',style:{},dataset:{},scrollTop:0,classList:{add(){},remove(){},toggle(){}},addEventListener(){},querySelectorAll(){return []},focus(){},contains(){return false}});
  const ss={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v)},removeItem:k=>{delete store[k]}};
  const ctx={document:{getElementById:node,addEventListener(){},documentElement:{dataset:{}},querySelectorAll(){return []}},window:{},localStorage:{getItem(){return null}},sessionStorage:ss,addEventListener(){},matchMedia:()=>({matches:false,addEventListener(){}}),setInterval(){},setTimeout:()=>1,getSelection:()=>null};
  vm.createContext(ctx);
  vm.runInContext(source.replace('schedulePoll(0); setInterval(ticks, 1000);',
    `globalThis.ui={set:s=>S=s,errHtml,chainOf,groups,viewChat,findItem,viewRun,viewNew,items,renderComposer,openKey:k=>open.add(k),settingsHtml,saveDraft,getMode:()=>mode,setMode:m=>mode=m,cache:detail};`),ctx);
  return {ui:ctx.ui,nodes};
}
const agents=['gemini','gpt','ds','claude'].map(name=>({name,profile:'x。',chain:['agy:x'],busy:0,current:[],quota:null}));
const config={planner:'gemini',synthesizer:'gemini',max_parallel:3,timeout:300,min_timeout:900,council_agents:['gemini','gpt','ds'],council_quota:{gpt:'5 小时额度只剩 6%'}};
const run={id:'r2',mode:'council',planner:null,synthesizer:'gemini',status:'done',start:1,end:9,summary:'会审：gemini、ds 各自独立作答',
  participants:['gemini','gpt','ds'],skipped:[{agent:'gpt',reason:'5 小时额度只剩 6%，低于 15%，这次自动跳过'}],timeout_warning:'时限只有 5 分钟，少于 15 分钟。',
  tasks:[{id:'m1',agent:'gemini',title:'gemini 的独立意见',status:'ok',depends_on:[],progress:'列了三条理由',leftover:'价格需要再确认'},
         {id:'m2',agent:'gpt',title:'gpt 的独立意见',status:'skipped',depends_on:[],skip_reason:'5 小时额度只剩 6%，低于 15%，这次自动跳过'},
         {id:'m3',agent:'ds',title:'ds 的独立意见',status:'ok',depends_on:[],why:'快'}]};
const {ui,nodes}=boot({});
ui.set({agents,config,health:{results:{}},calls:[{id:'c_s',run:'r2',kind:'synth',agent:'gemini',status:'ok',start:5,secs:3}],runs:[run],workspace:'/w'});
ui.cache['run:r2']={sig:'x',data:Object.assign({final:'## 建议\n买 A'},run)};
const folded=ui.viewRun({type:'run',id:'r2',title:'问',rec:run,status:'done',start:1,end:9});
assert.ok(folded.includes('买 A') && !folded.includes('进度：列了三条理由'),'做完后先看结果，过程和进度板折起');
ui.openKey('proc:r2');ui.openKey('board:r2');
const html=ui.viewRun({type:'run',id:'r2',title:'问',rec:run,status:'done',start:1,end:9});
for(const t of ['共享进度板','看不到别人的答案','进度：列了三条理由','遗留：价格需要再确认','为什么派给它：快','跳过：gpt','比较共同点和分歧','少于 15 分钟']) assert.ok(html.includes(t),t);
assert.ok(!html.includes('拆解任务、分配人手'),'会审不显示拆任务步骤');
assert.ok(html.includes('2 位成员参与'),'跳过的成员不算参与');
assert.ok(!html.includes('note bad'),'按规则跳过且完成的会审不显示红色错误');
assert.ok(!ui.items()[0].agents.includes('gpt'));
assert.ok(!html.includes('undefined'));
assert.ok(!html.includes('null'));
assert.equal(ui.items()[0].council,true);
// 输入框：会审模式提示、隐藏改文件开关
ui.setMode('council');ui.renderComposer();
assert.ok(nodes.hint.textContent.includes('gemini、ds 各自独立作答'));
assert.ok(nodes.hint.textContent.includes('跳过 gpt'));
ui.set({agents,config:Object.assign({},config,{council_quota:{gemini:'低',gpt:'低'}}),health:{results:{}},calls:[],runs:[],workspace:'/w'});ui.renderComposer();
assert.ok(nodes.hint.textContent.includes('只有 ds 额度充足'),nodes.hint.textContent);
ui.set({agents,config:Object.assign({},config,{council_quota:{gemini:'低'}}),health:{results:{}},calls:[],runs:[],workspace:'/w'});ui.renderComposer();
assert.ok(nodes.hint.textContent.includes('→ gpt 比较'),'综合者低额度时提示实际换上的人');
ui.setMode('不存在的模式');ui.renderComposer();assert.equal(ui.getMode(),'chat');ui.setMode('council');
ui.set({agents,config,health:{results:{}},calls:[{id:'c_s',run:'r2',kind:'synth',agent:'gemini',status:'ok',start:5,secs:3}],runs:[run],workspace:'/w'});ui.renderComposer();
assert.equal(nodes.wtog.style.display,'');  // 会审也能全部放开
assert.ok(nodes.modes.innerHTML.includes('data-v="council"'));
// 设置：会审成员勾选、时限过短提醒
const st=ui.settingsHtml();
assert.ok(st.includes('data-council="claude"'));
assert.ok(!/data-council="claude" checked/.test(st));
assert.ok(/data-council="gpt" checked/.test(st));
assert.ok(st.includes('现在少于 15 分钟'));
// 模板：单一数据源，含会审模板，标题与填入文字一致
const nv=ui.viewNew();
assert.ok(nv.includes('比较几种方案（会审）'));
assert.equal((nv.match(/data-act="sug"/g)||[]).length,6);
// 群聊：气泡式显示、模式按钮、提示、标签
const grun={id:'g1',mode:'group',planner:null,synthesizer:null,status:'running',start:1,end:null,summary:'群聊：gemini、gpt 轮流聊 2 轮',participants:['gemini','gpt'],rounds:2,
  tasks:[{id:'t1',agent:'gemini',title:'第 1 轮 · gemini',status:'ok',depends_on:[],answer:'我先说：音箱选 A',secs:4},
         {id:'t2',agent:'gpt',title:'第 1 轮 · gpt',status:'running',depends_on:[],answer:null,started:2}]};
ui.set({agents,config,health:{results:{}},calls:[],runs:[grun],workspace:'/w'});
ui.cache['run:g1']={sig:'x',data:grun};
const gh=ui.viewRun({type:'run',id:'g1',title:'聊聊音箱',rec:grun,status:'running',start:1,end:null});
for(const t of ['音箱选 A','第 1 轮','正在输入','gemini','gpt']) assert.ok(gh.includes(t),t);
assert.ok(!gh.includes('拆解任务') && !gh.includes('undefined'));
assert.equal(ui.items()[0].group,true);
ui.setMode('group');ui.renderComposer();
assert.ok(nodes.hint.textContent.includes('轮流聊'));
assert.ok(nodes.modes.innerHTML.includes('data-v="group"'));
console.log('ui council: board, skipped member, synthesis label, composer, settings and templates passed');
// 草稿：保存文字和模式；旧版纯文字也能恢复；不保存改文件开关
const store={};
const a=boot(store);a.nodes.txt.value='草稿内容';a.ui.setMode('council');a.ui.saveDraft();
assert.deepEqual(JSON.parse(store['hub.draft']),{text:'草稿内容',mode:'council'});
const b=boot(store);assert.equal(b.nodes.txt.value,'草稿内容');assert.equal(b.ui.getMode(),'council');
const c=boot({'hub.draft':'旧版草稿'});assert.equal(c.nodes.txt.value,'旧版草稿');assert.equal(c.ui.getMode(),'chat');
b.nodes.txt.value='  ';b.ui.saveDraft();assert.ok(!('hub.draft' in store),'清空后不再恢复旧文字');
console.log('ui draft: save, restore, legacy text and clear passed');

// 主联络窗口：一串对话、换人说明、派给团队的卡片能点进项目组
{
  const {ui,nodes}=boot({});
  const calls=[
    {id:'c_a',kind:'chat',agent:'gemini',status:'ok',start:10,end:12,secs:2,display:'第一句',chat:{mode:'auto',handoff:'这次由 gemini 联络：定方案'}},
    {id:'c_b',kind:'chat',agent:'gpt',status:'running',start:20,display:'第二句',follows:{type:'call',id:'c_a'},chat:{mode:'manual',handoff:'现在由 gpt 接手（上一轮是 gemini）：你指定的联络人'},dispatch:{mode:'run',goal:'写个小工具',run:'r9'}}];
  const runs=[{id:'r9',mode:'run',parent_call:'c_b',status:'running',start:21,tasks:[{id:'t1',agent:'gemini',title:'做',status:'ok',depends_on:[]},{id:'t2',agent:'gpt',title:'审',status:'pending',depends_on:['t1']}]}];
  ui.set({agents,config,health:{results:{}},calls,runs,workspace:'/w'});
  ui.cache['call:c_a']={sig:'ok|2|0|{}',data:{answer:'你好，我是对接人'}};
  const it=ui.findItem({type:'call',id:'c_b'});
  const v=ui.viewChat(it);
  for(const t of ['第一句','第二句','你好，我是对接人','现在由 gpt 接手','派给团队（自动分工）','已完成 1/2 件','data-type="run" data-id="r9"','对接人（你指定）','对接人（自动选）']) assert.ok(v.includes(t),t);
  assert.ok(!v.includes('undefined'));
  ui.setMode('chat');ui.renderComposer();
  assert.ok(nodes.contact.innerHTML.includes('value="auto"'));
  assert.equal(nodes.contact.style.display,'');
  ui.setMode('run');ui.renderComposer();assert.equal(nodes.contact.style.display,'none');ui.setMode('chat');ui.renderComposer();
  assert.ok(nodes.hint.textContent.includes('自动选对接人'));
  console.log('ui chat: conversation chain, handoff note, dispatched project card and contact picker passed');
}

{
  const {ui}=boot({});
  const h=ui.errHtml('gemini 没能完成：先用 Gemini Carbon·中等 试了，15 分钟内没做完','print timeout <b>','写到一半','k');
  assert.ok(h.includes('技术细节')&&h.includes('&lt;b&gt;')&&h.includes('未完成')&&h.includes('写到一半'));
  assert.equal(ui.errHtml('',null,null,'k'),'');
  console.log('ui errors: Chinese reason, technical details and partial answer passed');
}

{
  // 分叉的追问链：选中深层那条时，走它所在的分支；派出的项目组归到派它的那轮对话
  const {ui}=boot({});
  const mk=(id,start,f)=>({id,kind:'chat',agent:'gemini',status:'ok',start,display:id,follows:f?{type:'call',id:f}:null});
  const calls=[mk('c_1',1),mk('c_2a',2,'c_1'),mk('c_3a',3,'c_2a'),mk('c_2b',4,'c_1'),
    Object.assign(mk('c_9',10),{dispatch:{mode:'run',run:'r9',goal:'g'}})];
  const runs=[{id:'r9',mode:'run',parent_call:'c_9',status:'done',start:11,tasks:[]}];
  ui.set({agents,config,health:{results:{}},calls,runs,workspace:'/w'});
  assert.deepEqual(ui.chainOf(ui.findItem({type:'call',id:'c_3a'})).map(i=>i.id),['c_1','c_2a','c_3a']);
  assert.deepEqual(ui.chainOf(ui.findItem({type:'call',id:'c_2b'})).map(i=>i.id),['c_1','c_2b']);
  const g=ui.groups().projects.find(x=>x.items.some(i=>i.id==='r9'));
  assert.equal(g.latest.id,'c_9','点项目组卡片回到对话，而不是内部执行页');
  console.log('ui chat: branch-aware chain and dispatched group opens conversation passed');
}

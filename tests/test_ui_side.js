'use strict';
// 旁问小窗：不进左边记录、上下文三种选法、模型档位、叉掉追问后能改回来。
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('ui.html','utf8').match(/<script>([\s\S]*)<\/script>/)[1];
const nodes={};
const node=id=>nodes[id]||(nodes[id]={innerHTML:'',value:'',hidden:true,disabled:false,style:{},dataset:{},scrollTop:0,scrollHeight:0,clientHeight:0,classList:{add(){},remove(){},toggle(){},contains(){return false}},addEventListener(){},querySelectorAll(){return []},focus(){},contains(){return false}});
const posts=[];
const ctx={document:{getElementById:node,addEventListener(){},documentElement:{dataset:{}},querySelectorAll(){return []},body:{classList:{add(){},remove(){},toggle(){},contains(){return false}}}},window:{},localStorage:{getItem(){return null},setItem(){}},sessionStorage:{getItem(){return null},setItem(){},removeItem(){}},addEventListener(){},matchMedia:()=>({matches:false,addEventListener(){}}),setInterval(){},setTimeout:()=>1,clearTimeout(){},getSelection:()=>null,fetch:()=>new Promise(()=>{})};
vm.createContext(ctx);
vm.runInContext(source.replace('schedulePoll(0); setInterval(ticks, 1000);',
  'globalThis.ui={set:s=>S=s,items,renderSide,sideCtlHtml,sideState,renderComposer,open:v=>{sideOpen=v;},setSel:v=>{sel=v;ctx=v;},setCtx:v=>{ctx=v;},setSide:o=>{if("base" in o)sideBase=o.base;if("follow" in o)sideFollow=o.follow;if("agent" in o)sideAgent=o.agent;if("effort" in o)sideEffort=o.effort;},api:f=>{api=f;},sendSide,last,groups,chainOf,findItem,send,fork:(t,i)=>{ctx={type:t,id:i};forking=true;},isForking:()=>forking,setScope:v=>{sideScope=v;},pendImgs,thumbsHtml,viewChat,handPicker,setArm:v=>{handoffArm=v;}};'),ctx);
const agents=[{name:'gemini',chain:['agy:gemini-4-carbon-medium'],profile:'x'},{name:'gpt',chain:['codex'],profile:'x'},{name:'ds',chain:['dsh'],profile:'x'}];
const backends=['low','medium','high'].map(l=>({spec:'agy:gemini-4-carbon-'+l,label:'Gemini 4 Carbon ('+l[0].toUpperCase()+l.slice(1)+')'}))
  .concat([{spec:'codex',label:'GPT',efforts:[{id:'low',desc:''},{id:'ultra',desc:''}]},{spec:'codex:gpt-6-luna',label:'Luna',efforts:[{id:'low',desc:''}]},{spec:'dsh',label:'DS'}]);
const calls=[
  {id:'c_main',kind:'ask',agent:'gemini',status:'ok',start:10,end:12,display:'主线问题',cwd:'/w'},
  {id:'c_side1',kind:'side',agent:'gpt',backend:'codex',status:'ok',start:20,end:25,display:'旁问一下',follows:{type:'call',id:'c_main'},side:{web:true,effort:'low'}},
];
ctx.ui.set({agents,backends,calls,runs:[],config:{effort:{gpt:'low'}},workspace:'/w',health:{results:{}}});
assert.ok(!ctx.ui.items().some(i=>i.id==='c_side1'),'旁问不进左边记录');
ctx.ui.setSel({type:'call',id:'c_main'});
ctx.ui.open(true);
ctx.ui.renderSide();
assert.equal(nodes.sidewin.hidden,false);
assert.ok(nodes['sw-hist'].innerHTML.includes('旁问一下') && nodes['sw-hist'].innerHTML.includes('联网') && nodes['sw-hist'].innerHTML.includes('基于主线记录'));
let h=ctx.ui.sideCtlHtml(ctx.ui.sideState());
assert.ok(h.includes('value="none"') && /value="main" selected>基于当前记录：主线问题/.test(h),'默认基于当前记录');
assert.equal((h.match(/Gemini 4 Carbon</g)||[]).length,1,'Gemini 同系列只列一次');
assert.ok(h.includes('>Medium<') && h.includes('>High<'),'Gemini 档位用它自己的写法');
assert.ok(h.includes('data-sw="web" checked'),'默认联网');
ctx.ui.setSide({agent:'gpt'});
h=ctx.ui.sideCtlHtml(ctx.ui.sideState());
assert.ok(h.includes('跟成员设置一样（low）') && h.includes('ultra'),'GPT 档位按模型自己的');
ctx.ui.setSide({agent:'ds'});
assert.ok(ctx.ui.sideCtlHtml(ctx.ui.sideState()).includes('DeepSeek 不支持调节'));
ctx.ui.setSide({follow:{type:'call',id:'c_side1'},base:'follow',agent:'gpt',effort:'ultra'});
h=ctx.ui.sideCtlHtml(ctx.ui.sideState());
assert.ok(/value="follow" selected>接着旁问：旁问一下/.test(h));
// 发送：带上选中的模型、档位、联网和上下文
(async()=>{
  const state={agents,backends,calls,runs:[],config:{effort:{gpt:'low'}},workspace:'/w',health:{results:{}}};
  ctx.ui.api(async (path,body)=>{if(body===undefined)return state;posts.push([path,body]);return {ok:true};});
  nodes['sw-txt'].value='查一下';
  await ctx.ui.sendSide();
  const b=posts[0][1];
  assert.equal(posts[0][0],'/api/submit');
  assert.deepEqual({mode:b.mode,agent:b.agent,spec:b.spec,effort:b.effort,web:b.web,context:b.context},
    {mode:'side',agent:'gpt',spec:'codex',effort:'ultra',web:true,context:{type:'call',id:'c_side1'}});
  // 叉掉追问后出现「改回接着追问」
  ctx.ui.setCtx(null);
  nodes.txt.value='';
  ctx.ui.renderComposer();
  assert.ok(nodes.ctx.innerHTML.includes('data-act="yesctx"'),'叉掉后能改回来');
  ctx.ui.setCtx({type:'call',id:'c_main'});
  ctx.ui.renderComposer();
  assert.ok(nodes.ctx.innerHTML.includes('data-act="noctx"'));
  // 旁问上下文范围：完整 / 只带这一条
  ctx.ui.setSide({base:'main'}); ctx.ui.setSel({type:'call',id:'c_main'});
  h=ctx.ui.sideCtlHtml(ctx.ui.sideState());
  assert.ok(h.includes('data-sw="scope"') && /value="full" selected>完整上下文/.test(h),'默认完整上下文');
  ctx.ui.setScope('one'); posts.length=0; nodes['sw-txt'].value='只问这条';
  await ctx.ui.sendSide();
  assert.equal(posts[0][1].context_scope,'one');
  ctx.ui.setSide({base:'none'});
  assert.ok(!ctx.ui.sideCtlHtml(ctx.ui.sideState()).includes('data-sw="scope"'),'单独问时不显示范围');
  // 主线分叉：另起一组，链条到分叉处为止
  const fcalls=calls.concat([
    {id:'c_m2',kind:'ask',agent:'gemini',status:'ok',start:30,end:31,display:'主线第二轮',follows:{type:'call',id:'c_main'}},
    {id:'c_f1',kind:'ask',agent:'gemini',status:'ok',start:40,end:41,display:'分叉第一轮',follows:{type:'call',id:'c_main'},fork:true},
    {id:'c_f2',kind:'ask',agent:'gemini',status:'ok',start:50,end:51,display:'分叉第二轮',follows:{type:'call',id:'c_f1'}}]);
  ctx.ui.set(Object.assign({},state,{calls:fcalls}));
  const g=ctx.ui.groups();
  const fg=g.projects.find(p=>p.items.some(i=>i.id==='c_f1')), mg=g.projects.find(p=>p.items.some(i=>i.id==='c_main'));
  assert.ok(fg && mg && fg!==mg,'分叉是独立的一组');
  assert.deepEqual(fg.items.map(i=>i.id),['c_f1','c_f2']);
  assert.ok(fg.kind.includes('分叉'));
  assert.deepEqual(ctx.ui.chainOf(ctx.ui.findItem({type:'call',id:'c_main'})).map(i=>i.id),['c_main','c_m2'],'主线不会走进分叉');
  // 分叉发送
  ctx.ui.setSel({type:'call',id:'c_m2'}); ctx.ui.fork('call','c_main');
  ctx.ui.renderComposer();
  assert.ok(nodes.ctx.innerHTML.includes('分叉') && nodes.ctx.innerHTML.includes('主线问题'));
  posts.length=0; nodes.txt.value='分叉里说的话';
  await ctx.ui.send();
  assert.equal(posts[0][1].fork,true); assert.deepEqual(posts[0][1].context,{type:'call',id:'c_main'});
  assert.equal(ctx.ui.isForking(),false,'发完就不再是分叉状态');
  // 贴图：发送时带上已上传的图，上传中的不带；记录里显示缩略图
  ctx.ui.pendImgs.side.push({id:'att-20261115-010101-aaaaaaaa.png'});
  ctx.ui.setSide({base:'none'}); posts.length=0; nodes['sw-txt'].value='看看这张图';
  await ctx.ui.sendSide();
  assert.deepEqual(posts[0][1].images,['att-20261115-010101-aaaaaaaa.png']);
  assert.equal(ctx.ui.pendImgs.side.length,0,'发完清空');
  ctx.ui.pendImgs.side.push({up:true}); posts.length=0; nodes['sw-txt'].value='还在传';
  await ctx.ui.sendSide();
  assert.equal(posts.length,0,'图片没传完不发');
  ctx.ui.pendImgs.side.length=0;
  const th=ctx.ui.thumbsHtml(['att-1.png" onerror="x']);
  assert.ok(!th.includes('" onerror="') && th.includes('/api/attachment?id='),'缩略图地址转义');
  assert.equal(ctx.ui.thumbsHtml([]),'');
  // 交接：来源组留着，交接卡片进接收的那组，组名用接收的那组；对话里有交接卡片；能选交接到哪
  {
    const hc=[
      {id:'c_a1',kind:'chat',agent:'claude',status:'ok',start:100,end:101,display:'我想学生图'},
      {id:'c_a2',kind:'chat',agent:'claude',status:'ok',start:110,end:111,display:'controlnet 是什么',follows:{type:'call',id:'c_a1'}},
      {id:'c_b1',kind:'ask',agent:'gemini',status:'ok',start:50,end:60,display:'总结B站视频'},
      {id:'c_h',kind:'handoff',agent:'-',status:'ok',start:120,end:120,display:'交接：把「B站」的结果交到这里',follows:{type:'call',id:'c_a2'},handoff:{from:{type:'call',id:'c_b1'},name:'B站'}},
      {id:'c_x',kind:'ask',agent:'ds',status:'ok',start:5,end:6,display:'别的事'}];
    ctx.ui.set(Object.assign({},state,{calls:hc,names:{'call:c_a1':'生图扫盲'}}));
    const gs=ctx.ui.groups();
    const merged=gs.projects.find(p=>p.items.some(i=>i.id==='c_h'));
    assert.ok(!merged.items.some(i=>i.id==='c_b1'),'来源那组照旧留着，不并进来');
    assert.equal(merged.id,'call:c_a1'); assert.equal(merged.title,'生图扫盲','组名用接收的那组');
    const v=ctx.ui.viewChat(ctx.ui.findItem({type:'call',id:'c_h'}));
    assert.ok(v.includes('交接进来') && v.includes('打开来源那一组') && v.includes('我想学生图'),'对话里有交接卡片和原来的对话');
    ctx.ui.setSel({type:'call',id:'c_x'}); ctx.ui.setArm('call:c_x');
    const pk=ctx.ui.handPicker(ctx.ui.findItem({type:'call',id:'c_x'}));
    assert.ok(pk.includes('value="call:c_h"') && pk.includes('生图扫盲'),'交接目标是那一组现在的最后一轮');
  }
  // 上一轮还在做也能接着追问，并提示
  {
    const rc=[{id:'c_r',kind:'chat',agent:'claude',status:'running',start:1,display:'还在做的对话'}];
    ctx.ui.set(Object.assign({},state,{calls:rc}));
    ctx.ui.setSel({type:'call',id:'c_r'}); ctx.ui.renderComposer();
    assert.ok(nodes.ctx.innerHTML.includes('上一轮还在做'),'提示只带已完成的部分');
    posts.length=0; nodes.txt.value='追加材料';
    await ctx.ui.send();
    assert.deepEqual(posts[0][1].context,{type:'call',id:'c_r'},'照样带上上文');
  }
  console.log('ui side: excluded from list, context choices, model levels, send body and ctx restore passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

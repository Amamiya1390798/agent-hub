'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync('ui.html','utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
new Function(script);
const esc = script.slice(script.indexOf('const esc ='),script.indexOf('function dur('));
const markdown = script.slice(script.indexOf('function inline('),script.indexOf('/* ---------- 数据整理'));
const ctx = {};
vm.createContext(ctx); vm.runInContext(esc + markdown,ctx);
const md = ctx.md;
assert.equal(md('# 标题\n\n**粗体** 和 `x<y`'),'<h1>标题</h1><p><strong>粗体</strong> 和 <code>x&lt;y</code></p>');
assert.equal(md('```js\n<a>\n```'),'<pre><code>&lt;a&gt;</code></pre>');
assert.equal(md('~~~\nx\n~~~'),'<pre><code>x</code></pre>');
assert.equal(md('> 引用'),'<blockquote><p>引用</p></blockquote>');
assert.equal(md('- 一\n  - 二\n- 三'),'<ul><li>一<ul><li>二</li></ul></li><li>三</li></ul>');
assert.equal(md('3. 三\n4. 四'),'<ol start="3"><li>三</li><li>四</li></ol>');
assert.ok(md('|甲|乙|\n|---|---|\n|一|二|').includes('<td>二</td>'));
assert.equal(md('[坏](javascript:alert(1))'),'<p>坏</p>');
assert.ok(!md('<img src=x onerror=alert(1)>').includes('<img'));
assert.ok(md('[链接](https://example.org/a_(b)?x=1&y=2)').includes('href="https://example.org/a_(b)?x=1&amp;y=2"'));
assert.ok(!md('[链接](https://example.org/`foo`)').includes('<code>'));
assert.ok(!md('\u00000\u0000\u00010\u0001X\u0002').includes('undefined'));
assert.ok(md('`[x](https://example.org)`').includes('<code>[x](https://example.org)</code>'));
assert.equal(md('---'),'<hr>');
assert.equal(md('````\n```\n````'),'<pre><code>```</code></pre>');
console.log('ui markdown: 15 cases passed');

// 用原生 VM 运行实际事件处理代码，检查错误恢复与重新执行请求。
const listeners = {}, elements = {};
let submitted = [], toastText = '', polls = 0;
const ui = {
  document: {addEventListener:(name,fn)=>listeners[name]=fn},
  S:{}, sel:{type:'call',id:'c_abc'},
  findItem:()=>({type:'call',id:'c_abc',rec:{id:'c_abc',kind:'ask',agent:'gpt',cwd:'/work',write:false,display:'再解释',follows:{type:'call',id:'c_def'}}}),
  api:async(path,body)=>{submitted.push({path,body}); return {submission_id:"own"};},
  toast:t=>{toastText=t;}, poll:()=>{polls++;},
  beginSubmit:()=>{}, clearTimeout:()=>{}, isRemote:()=>false,
  renderView:()=>{}, stopArm:'c_abc', last:{view:'old',rail:'old'}, followLatest:true,
};
vm.createContext(ui);
vm.runInContext(script.slice(script.indexOf('document.addEventListener("click"'),script.indexOf('["mousedown", "keydown", "input"]')),ui);
(async()=>{
  const click = act=>({target:{closest:()=>({dataset:{act,sure:'1'},tagName:'BUTTON'})}});
  await listeners.click(click('retry'));
  assert.equal(submitted[0].body.text,'再解释');
  assert.equal(submitted[0].body.context.id,'c_def');
  assert.equal(submitted[0].body.agent,'gpt');
  ui.api = async()=>{throw Error('失败');};
  await listeners.click(click('stop'));
  assert.equal(ui.stopArm,null); assert.equal(ui.last.view,'');
  await listeners.click(click('retry'));
  assert.equal(ui.followLatest,false);
  let blurred = false;
  await listeners.change({target:{dataset:{cfg:'timeout'},type:'number',value:'bad',blur:()=>{blurred=true;}}});
  assert.ok(blurred); assert.equal(ui.last.rail,''); assert.ok(polls>0);
  console.log('ui actions: retry context and failure recovery passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

const tags = {};
vm.createContext(tags);
vm.runInContext(esc + script.slice(script.indexOf('const fallbackTag ='),script.indexOf('function block(')) + '\nthis.tag=fallbackTag;',tags);
assert.equal(tags.tag('gpt','codex','codex'),'');
assert.ok(tags.tag('gpt','dsh','codex').includes('由后备顶替'));
assert.equal(tags.tag('gpt','codex',null),'');
console.log('ui fallback: historical preferred model passed');

'use strict';
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const script = fs.readFileSync('ui.html', 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];
const pending = [], conn = {}, renders = [], timers = new Map();
let timerId = 0;
const ui = {
  pollSeq:0, appliedPollSeq:0, CID:'test', uiVersion:0, S:null, sel:null, followLatest:false, detailRetryAt:0,
  last:{list:'shown',rail:'shown'}, pollTimer:0, document:{hidden:false},
  api:path=>new Promise((resolve,reject)=>pending.push({path,resolve,reject})),
  $:()=>conn,
  setTimeout:(fn,delay)=>{ timers.set(++timerId,{fn,delay}); return timerId; },
  clearTimeout:id=>timers.delete(id)
};
for (const name of ['checkDone','renderList','renderRail','renderView','renderComposer','renderSide','renderAwake']){
  ui[name] = () => renders.push(name);
}
vm.createContext(ui);
vm.runInContext(script.slice(script.indexOf('async function poll(){'),script.indexOf('/* ---------- 查看回答')), ui);
const full = version => ({version, now:60, calls:[], runs:[], live:{}, client:{remote:true}});

(async()=>{
  const first = ui.poll(), second = ui.poll();
  pending[0].resolve(full('one')); await first; // 慢于轮询间隔也可用
  assert.equal(ui.S.version,'one');
  pending[1].resolve(full('two')); await second;
  const third = ui.poll(), fourth = ui.poll();
  pending[3].resolve(full('four')); await fourth;
  pending[2].resolve(full('three')); await third;
  assert.equal(ui.S.version,'four');
  const fifth = ui.poll(), sixth = ui.poll();
  pending[5].resolve(full('six')); await sixth;
  pending[4].reject(Error('旧请求失败')); await fifth;
  assert.equal(conn.textContent,'已连接');

  ui.S.calls = [{id:'old'},{id:'stays'},{id:'updates',status:'running'}];
  const poll = async state => {
    const request = ui.poll();
    pending[pending.length - 1].resolve(state);
    await request;
  };
  renders.length = 0;
  await poll({version:'six'});
  assert.ok(pending[pending.length - 1].path.includes('&v=six'));
  assert.deepEqual(renders, []);
  assert.equal(ui.S.calls.length, 3);
  await poll({version:'seven', changes:{calls:{
    upsert:[{id:'own',submission_id:'mine'},{id:'updates',status:'ok'}],
    remove:['old'], order:['own','updates','stays']
  }}});
  assert.deepEqual(Array.from(ui.S.calls, c => c.id), ['own','updates','stays']);
  assert.equal(ui.S.calls[1].status,'ok');
  assert.equal(ui.S.client.remote,true);

  ui.followLatest = true;
  ui.pendingSubmission = 'mine';
  ui.items = () => ui.S.calls.map(rec => ({type:'call',id:rec.id,rec}));
  await poll({version:'seven'});
  assert.equal(ui.sel.id,'own'); assert.equal(ui.ctx.id,'own');
  assert.equal(ui.followLatest,false);

  renders.length = 0;
  await poll({version:'eight', changes:{live:{updates:'mtime:1'}}});
  assert.deepEqual(renders, ['renderView']);
  renders.length = 0;
  await poll({version:'nine', changes:{awake:true}});
  assert.deepEqual(renders, ['renderAwake']);
  ui.last.railPending = true; renders.length = 0;
  await poll({version:'nine'});
  assert.deepEqual(renders,['renderRail']);

  // 同一旧版发出两个请求，后完成的补丁仍然合并到各自请求时的状态。
  const a = ui.poll(), b = ui.poll();
  pending[pending.length - 2].resolve({version:'ten',changes:{awake:false}}); await a;
  pending[pending.length - 1].resolve({version:'eleven',changes:{live:{}}}); await b;
  assert.equal(ui.S.awake,true);

  ui.schedulePoll(0);
  assert.equal(timers.get(ui.pollTimer).delay,0);
  ui.document.hidden = true;
  const tick = timers.get(ui.pollTimer).fn();
  pending[pending.length - 1].resolve({version:'eleven'}); await tick;
  assert.equal(timers.get(ui.pollTimer).delay,10000);
  ui.document.hidden = false;
  await (async()=>{
    const tick = timers.get(ui.pollTimer).fn();
    pending[pending.length - 1].resolve({version:'eleven'}); await tick;
  })();
  assert.equal(timers.get(ui.pollTimer).delay,1500);
  console.log('ui polling: versions, ordered patches, targeted renders, slow responses and hidden interval passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

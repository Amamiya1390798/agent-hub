'use strict';
// 左侧「项目组 / 单独提问」分组、展开收起、筛选搜索、选中与转义检查（Node 虚拟环境，不需要浏览器）。
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('ui.html', 'utf8').match(/<script>([\s\S]*)<\/script>/)[1];

function boot(){
  const nodes = {}, docListeners = {};
  const makeClassList = () => {
    const set = new Set();
    return {
      add(...xs){ xs.forEach(x => set.add(x)); },
      remove(...xs){ xs.forEach(x => set.delete(x)); },
      toggle(x, force){ if (force === undefined ? !set.has(x) : force) set.add(x); else set.delete(x); },
      contains(x){ return set.has(x); }
    };
  };
  const node = id => nodes[id] || (nodes[id] = {
    innerHTML: '', value: '', textContent: '', style: {}, dataset: {}, scrollTop: 0,
    classList: makeClassList(), addEventListener(ev, fn){ (this._on || (this._on = {}))[ev] = fn; },
    querySelectorAll(){ return []; }, focus(){}, contains(){ return false; }
  });
  const ctx = {
    document: {
      getElementById: node,
      body: { classList: makeClassList() },
      addEventListener(ev, fn){ docListeners[ev] = fn; },
      documentElement: { dataset: {} },
      querySelectorAll(){ return []; }
    },
    window: {},
    localStorage: { getItem(){ return null; }, setItem(){} },
    sessionStorage: { getItem(){ return null; }, setItem(){}, removeItem(){} },
    addEventListener(){},
    matchMedia: () => ({ matches: false, addEventListener(){} }),
    setInterval(){},
    clearTimeout(){},
    setTimeout: () => 1,
    getSelection: () => null,
    fetch: () => new Promise(() => {})
  };
  vm.createContext(ctx);
  vm.runInContext(source.replace(
    'poll(); setInterval(poll, 1500); setInterval(ticks, 1000);',
    'globalThis.ui={set:s=>{S=s;},groups,items,renderList,select,getSel:()=>sel,getFilter:()=>filter,setFilter:v=>{filter=v;},setQuery:v=>{query=v;},openGroups,last};'
  ), ctx);
  return { ui: ctx.ui, nodes, docListeners };
}

const agents = ['gemini', 'gpt', 'ds', 'claude'].map(name => ({
  name, profile: '说明。', chain: ['agy:x'], busy: 0, current: [], quota: null
}));
const config = { planner: 'gemini', synthesizer: 'gemini', max_parallel: 3, timeout: 900, min_timeout: 900, council_agents: ['gemini', 'gpt', 'ds'] };

(async () => {
  const { ui, nodes, docListeners } = boot();
  const clickAct = dataset => docListeners.click({
    target: { closest: sel => sel === '[data-act]' ? { dataset, tagName: 'BUTTON' } : null }
  });

  // 1) 空状态：完全无记录
  ui.set({ agents, config, health: { results: {} }, calls: [], runs: [], workspace: '/w' });
  ui.renderList();
  assert.ok(nodes.list.innerHTML.includes('还没有记录'), '完全无记录时显示初始空状态');

  // 2) 分组规则：追问链、parent_call 归入对话组、独立会审、单条对话 vs 单条提问/画图
  const calls = [
    // 对接人对话链 + 派出的协作 run (r_chat)
    { id: 'c_chat1', kind: 'chat', agent: 'gemini', status: 'ok', start: 100, end: 105, secs: 5, display: '筹备新专辑' },
    { id: 'c_chat2', kind: 'chat', agent: 'gpt', status: 'ok', start: 110, end: 115, secs: 5, display: '排一下分工和预算', follows: { type: 'call', id: 'c_chat1' }, dispatch: { mode: 'run', goal: '列歌单与预算', run: 'r_chat' } },
    // 普通提问追问链（第一条失败，追问第二条成功 -> 整体应看最新一条为 ok）
    { id: 'c_ask1', kind: 'ask', agent: 'ds', status: 'fail', error: '超时', start: 50, end: 52, secs: 2, display: '先翻第一段' },
    { id: 'c_ask2', kind: 'ask', agent: 'gemini', status: 'ok', start: 60, end: 63, secs: 3, display: '接着翻第二段暗号词', follows: { type: 'call', id: 'c_ask1' } },
    // 单条对接人对话（kind==="chat"，即使只有一条也算项目组）
    { id: 'c_chat_solo', kind: 'chat', agent: 'gemini', status: 'fail', error: '断网', start: 80, end: 81, secs: 1, display: '单独找对接人聊失败' },
    // 单条普通提问 & 单条画图 -> 归入「单独提问」
    { id: 'c_single_ask', kind: 'ask', agent: 'ds', status: 'ok', start: 70, end: 71, secs: 1, display: '帮我改个错别字' },
    { id: 'c_single_img', kind: 'image', agent: 'gpt', status: 'fail', error: '生成失败', start: 90, end: 92, secs: 2, title: '深海灯塔封面' }
  ];
  const runs = [
    // 被 c_chat2 派出的协作 run（进行中）
    {
      id: 'r_chat', mode: 'run', parent_call: 'c_chat2', planner: 'gemini', synthesizer: 'gemini',
      status: 'running', start: 112, end: null, display: '列歌单与预算',
      tasks: [
        { id: 't1', agent: 'gemini', title: '整理曲目初稿', status: 'ok', depends_on: [] },
        { id: 't2', agent: 'claude', title: '预算把关审查', status: 'running', depends_on: ['t1'] }
      ]
    },
    // 没有追问关系的独立会审
    {
      id: 'r_council', mode: 'council', planner: null, synthesizer: 'gemini',
      status: 'done', start: 120, end: 130, goal: '买哪款声卡更稳妥',
      tasks: [
        { id: 'm1', agent: 'gemini', title: 'gemini 的独立意见', status: 'ok', depends_on: [] },
        { id: 'm2', agent: 'ds', title: 'ds 的独立意见', status: 'ok', depends_on: [] }
      ]
    }
  ];

  // 再加一条跟在 c_chat2 之后已完成的对话，验证「组内只要有进行中，整体状态就是进行中」
  calls.push({ id: 'c_chat3', kind: 'chat', agent: 'gemini', status: 'ok', start: 116, end: 118, secs: 2, display: '顺便问一句进度', follows: { type: 'call', id: 'c_chat2' } });

  ui.set({ agents, config, health: { results: {} }, calls, runs, workspace: '/w' });
  const g = ui.groups();

  // 项目组应有 4 组：r_council(120)、c_chat1 组(最新 116)、c_chat_solo(80)、c_ask1 追问链(60)
  assert.equal(g.projects.length, 4, '应有 4 个项目组');
  assert.deepEqual(g.projects.map(p => p.id), ['run:r_council', 'call:c_chat1', 'call:c_chat_solo', 'call:c_ask1'], '按组内最新时间倒序排列');

  // 检查 parent_call 归入对话组、最早标题、去重成员（含 run.tasks）、进行中整体状态
  const chatGroup = g.projects[1];
  assert.equal(chatGroup.title, '筹备新专辑', '组标题取最早那条');
  assert.equal(chatGroup.status, 'running', '组内 r_chat 仍在进行中，整体状态应为进行中');
  assert.equal(chatGroup.kind, '协作');
  assert.deepEqual(chatGroup.items.map(i => i.id), ['c_chat1', 'c_chat2', 'r_chat', 'c_chat3'], '组内按时间正序排列');
  for (const ag of ['gemini', 'gpt', 'claude']) assert.ok(chatGroup.agents.includes(ag), '成员应包含对话与子任务中的 ' + ag);
  assert.equal(new Set(chatGroup.agents).size, chatGroup.agents.length, '成员去重');
  assert.deepEqual({ type: chatGroup.latest.type, id: chatGroup.latest.id }, { type: 'call', id: 'c_chat3' });

  // 检查追问链合成一组 & 最新状态覆盖早期失败
  const askChain = g.projects[3];
  assert.equal(askChain.title, '先翻第一段');
  assert.equal(askChain.status, 'ok', '无进行中时整体状态取最新一条');
  assert.equal(askChain.kind, '对话');
  assert.deepEqual(askChain.items.map(i => i.id), ['c_ask1', 'c_ask2']);

  // 检查独立会审组
  assert.equal(g.projects[0].kind, '会审');
  assert.deepEqual(g.projects[0].agents, ['gemini', 'ds']);

  // 检查「单独提问」区只含单条普通提问和画图，按时间倒序
  assert.deepEqual(g.solos.map(s => s.id), ['c_single_img', 'c_single_ask']);

  // 3) 默认收起、分区顺序、点卡片主体选中最新一条、点 ▸ 展开看到组内行和缩进任务行
  nodes.list.scrollTop = 42;
  ui.renderList();
  const defaultHtml = nodes.list.innerHTML;
  assert.equal(nodes.list.scrollTop, 42, '重绘时保留滚动位置');
  assert.ok(defaultHtml.indexOf('>项目组<') < defaultHtml.indexOf('>单独提问<'), '项目组在上、单独提问在下');
  assert.equal(ui.openGroups.size, 0, '默认全部收起');
  assert.ok(defaultHtml.includes('▸'), '收起态显示 ▸');
  assert.ok(!defaultHtml.includes('整理曲目初稿'), '默认收起时不渲染 run 下面的任务行');
  assert.ok(!defaultHtml.includes('排一下分工和预算'), '默认收起时不渲染组内中间步骤');
  assert.ok(defaultHtml.includes('帮我改个错别字') && defaultHtml.includes('🎨 深海灯塔封面'), '单独提问保持平铺显示');

  // 无变化时重复调用 renderList 不改写 last.list
  const cachedHtml = ui.last.list;
  nodes.list.innerHTML = 'SENTINEL';
  ui.renderList();
  assert.equal(nodes.list.innerHTML, 'SENTINEL', 'last.list 相同则不重复重绘 DOM');
  nodes.list.innerHTML = cachedHtml;

  // 点项目组卡片主体 -> 选中该组最新一条（c_chat3）
  assert.ok(defaultHtml.includes('class="gmain" data-act="select" data-type="call" data-id="c_chat3"'));
  await clickAct({ act: 'select', type: 'call', id: 'c_chat3' });
  assert.deepEqual(ui.getSel(), { type: 'call', id: 'c_chat3' });
  assert.ok(nodes.list.innerHTML.includes('class="gmain sel" data-act="select" data-type="call" data-id="c_chat3"'), '收起态下选中组有选中样式');

  // 点左边 ▸ 按钮展开 call:c_chat1 组
  await clickAct({ act: 'group', id: 'call:c_chat1' });
  assert.ok(ui.openGroups.has('call:c_chat1'));
  const expandedHtml = nodes.list.innerHTML;
  assert.ok(expandedHtml.includes('▾'), '展开后按钮变为 ▾');
  for (const text of ['筹备新专辑', '排一下分工和预算', '列歌单与预算', '顺便问一句进度', '整理曲目初稿', '预算把关审查']) {
    assert.ok(expandedHtml.includes(text), '展开后应看到：' + text);
  }
  assert.ok(
    expandedHtml.indexOf('筹备新专辑') < expandedHtml.indexOf('排一下分工和预算') &&
    expandedHtml.indexOf('排一下分工和预算') < expandedHtml.indexOf('列歌单与预算') &&
    expandedHtml.indexOf('列歌单与预算') < expandedHtml.indexOf('顺便问一句进度'),
    '组内条目按时间正序显示'
  );
  assert.ok(expandedHtml.includes('class="gitem sel" data-act="select" data-type="call" data-id="c_chat3"'), '展开后当前选中的那条有 sel 样式');
  assert.ok(expandedHtml.includes('class="gtask" data-act="select" data-type="run" data-id="r_chat"'), '缩进任务行点击打开所属 run');

  // 点缩进任务行 -> 选中所属 run，且选中样式移到 r_chat 行
  await clickAct({ act: 'select', type: 'run', id: 'r_chat' });
  assert.deepEqual(ui.getSel(), { type: 'run', id: 'r_chat' });
  assert.ok(nodes.list.innerHTML.includes('class="gitem sel" data-act="select" data-type="run" data-id="r_chat"'));
  assert.ok(!nodes.list.innerHTML.includes('class="gitem sel" data-act="select" data-type="call" data-id="c_chat3"'));

  // 再次点 ▾ 收起该组
  await clickAct({ act: 'group', id: 'call:c_chat1' });
  assert.ok(!ui.openGroups.has('call:c_chat1'));
  assert.ok(!nodes.list.innerHTML.includes('整理曲目初稿'), '收起后隐藏任务行');

  // 4) 筛选（全部 / 进行中 / 失败）与搜索（组内任一条标题匹配即显示该组）
  await clickAct({ act: 'filter', v: 'running' });
  assert.equal(ui.getFilter(), 'running');
  assert.ok(nodes.list.innerHTML.includes('筹备新专辑'), '进行中筛选包含有运行中条目的组');
  assert.ok(!nodes.list.innerHTML.includes('买哪款声卡更稳妥'), '已完成会审不在进行中里');
  assert.ok(!nodes.list.innerHTML.includes('单独提问'), '无进行中的单独提问不显示');

  await clickAct({ act: 'filter', v: 'failed' });
  assert.ok(nodes.list.innerHTML.includes('单独找对接人聊失败'), '失败的项目组显示');
  assert.ok(nodes.list.innerHTML.includes('深海灯塔封面'), '失败的单独提问显示');
  assert.ok(!nodes.list.innerHTML.includes('先翻第一段'), '早期失败但最新成功的追问组不算失败');
  assert.ok(!nodes.list.innerHTML.includes('筹备新专辑'), '进行中的组不算失败');
  assert.ok(!nodes.list.innerHTML.includes('帮我改个错别字'), '成功的单独提问不算失败');

  await clickAct({ act: 'filter', v: 'all' });
  // 通过真实搜索框 input 事件触发搜索（匹配非首条追问标题）
  nodes.q._on.input({ target: { value: '  暗号词  ' } });
  assert.ok(nodes.list.innerHTML.includes('先翻第一段'), '组内任一条标题匹配即显示该组');
  assert.ok(!nodes.list.innerHTML.includes('筹备新专辑'));
  assert.ok(!nodes.list.innerHTML.includes('单独提问'));

  nodes.q._on.input({ target: { value: '完全不存在的关键词xyz' } });
  assert.ok(nodes.list.innerHTML.includes('没有符合条件的记录'), '筛选搜索无结果时保留空状态提示');
  nodes.q._on.input({ target: { value: '' } });

  // 验证展开中的项目组在新增追问后组 id 不变、保持展开；同时检查同秒因果序与跳过/仅方案状态
  ui.openGroups.add('call:c_ask1');
  calls.push({ id: 'c_ask3', kind: 'ask', agent: 'claude', status: 'ok', start: 60, end: 64, secs: 4, display: '同秒继续追问', follows: { type: 'call', id: 'c_ask2' } });
  runs.push({
    id: 'r_plan', mode: 'run', parent_call: 'c_ask3', planner: 'gemini', synthesizer: 'gemini', status: 'done', start: 60, end: 65,
    display: '同秒派出的方案',
    tasks: [
      { id: 'tp1', agent: 'gemini', title: '未执行方案项', status: null, depends_on: [] },
      { id: 'tp2', agent: 'gpt', title: '额度跳过项', status: 'skipped', depends_on: [] }
    ]
  });
  ui.renderList();
  assert.ok(ui.openGroups.has('call:c_ask1'), '新增追问后原展开组仍保持展开');
  assert.ok(nodes.list.innerHTML.includes('未执行方案项') && nodes.list.innerHTML.includes('仅方案'), '展开态正确显示仅方案任务');
  assert.ok(nodes.list.innerHTML.includes('额度跳过项') && nodes.list.innerHTML.includes('已跳过'), '展开态正确显示已跳过任务');
  const askExpanded = ui.groups().projects.find(p => p.id === 'call:c_ask1');
  assert.deepEqual(askExpanded.items.map(i => i.id), ['c_ask1', 'c_ask2', 'c_ask3', 'r_plan'], '同秒记录按追问/派出因果顺序排列');

  // 5) XSS 转义：组标题、追问标题、任务标题、单独提问标题含 <script> 与引号均被转义
  ui.set({
    agents, config, health: { results: {} }, workspace: '/w',
    calls: [
      { id: 'c_xss1', kind: 'chat', agent: 'gemini', status: 'ok', start: 10, display: '组标题<script>alert(1)</script>"x"' },
      { id: 'c_xss2', kind: 'chat', agent: 'gemini', status: 'ok', start: 20, display: '追问<img src=x onerror=alert(2)>', follows: { type: 'call', id: 'c_xss1' } },
      { id: 'c_xss_solo', kind: 'ask', agent: 'ds', status: 'ok', start: 30, display: '单问<script>evil()</script>' }
    ],
    runs: [{
      id: 'r_xss', mode: 'run', parent_call: 'c_xss2', planner: 'gemini', synthesizer: 'gemini', status: 'done', start: 25,
      display: '协作<script>run()</script>',
      tasks: [{ id: 't_xss', agent: 'gemini', title: '任务<script>task()</script>', status: 'ok', depends_on: [] }]
    }]
  });
  ui.openGroups.add('call:c_xss1');
  ui.renderList();
  const xssHtml = nodes.list.innerHTML;
  assert.ok(!xssHtml.includes('<script'), 'HTML 中绝不能出现未转义的 <script');
  assert.ok(!xssHtml.includes('<img'), 'HTML 中绝不能出现未转义的 <img');
  assert.ok(xssHtml.includes('&lt;script&gt;alert(1)&lt;/script&gt;&quot;x&quot;'));
  assert.ok(xssHtml.includes('&lt;img src=x onerror=alert(2)&gt;'));
  assert.ok(xssHtml.includes('任务&lt;script&gt;task()&lt;/script&gt;'));
  assert.ok(xssHtml.includes('单问&lt;script&gt;evil()&lt;/script&gt;'));
  assert.ok(!xssHtml.includes('undefined'));

  // 归档：归档的组和单条平时不显示，只在「已归档」里出现；进行中的组没有归档按钮
  {
    const base = { agents, config, health: { results: {} }, calls, runs, workspace: '/w' };
    ui.set(Object.assign({}, base, { archived: ['call:c_ask1', 'call:c_ask2', 'call:c_ask3', 'run:r_plan', 'call:c_single_ask', 'call:c_chat1'] }));
    ui.setFilter('all'); ui.setQuery(''); ui.last.list = ''; ui.last.filters = '';
    ui.renderList();
    let h = nodes.list.innerHTML;
    assert.ok(!h.includes('接着翻第二段暗号词') && !h.includes('先翻第一段'), '整组归档后平时不显示');
    assert.ok(!h.includes('帮我改个错别字'), '归档的单独提问平时不显示');
    assert.ok(h.includes('筹备新专辑'), '组里只归档了一部分（后来又有新追问）时仍显示');
    assert.ok(nodes.filters.innerHTML.includes('已归档 2'), '筛选栏显示归档数量');
    assert.ok(/class="iarch" data-act="archive" data-keys="call:c_single_img" data-on="1"/.test(h), '单独提问卡片上有归档小按钮');
    assert.ok(!/data-act="archive"[^>]*call:c_chat1/.test(h), '进行中的组没有归档按钮');
    ui.setFilter('archived'); ui.last.list = '';
    ui.renderList();
    h = nodes.list.innerHTML;
    assert.ok(h.includes('先翻第一段') && h.includes('帮我改个错别字'), '「已归档」里能看到');
    assert.ok(!h.includes('买哪款声卡更稳妥'), '「已归档」里不出现没归档的');
    assert.ok(h.includes('data-on="0"'), '已归档的组显示取消归档按钮');
    assert.ok(/class="iarch" data-act="archive" data-keys="call:c_single_ask" data-on="0"/.test(h), '已归档的单独提问有取消归档小按钮');
    ui.set(Object.assign({}, base, { archived: [] }));
    ui.last.list = '';
    ui.renderList();
    assert.ok(nodes.list.innerHTML.includes('还没有归档的记录'), '没有归档时的空状态');
    ui.setFilter('all'); ui.last.list = ''; ui.last.filters = '';
  }

  // 项目组名字：有名字就显示名字，搜索也能搜到；卡片上有重命名按钮
  {
    ui.set({ agents, config, health: { results: {} }, calls, runs, workspace: '/w', names: { 'run:r_council': '声卡选购', 'call:c_single_ask': '错别字' } });
    ui.setFilter('all'); ui.setQuery(''); ui.last.list = '';
    const gg = ui.groups();
    assert.equal(gg.projects.find(p => p.id === 'run:r_council').title, '声卡选购');
    ui.renderList();
    assert.ok(nodes.list.innerHTML.includes('声卡选购') && nodes.list.innerHTML.includes('错别字'));
    assert.ok(nodes.list.innerHTML.includes('data-act="rename" data-key="run:r_council" data-name="声卡选购"'));
    ui.setQuery('声卡选购'); ui.last.list = ''; ui.renderList();
    assert.ok(nodes.list.innerHTML.includes('声卡选购') && !nodes.list.innerHTML.includes('筹备新专辑'), '按名字搜索');
    ui.setQuery(''); ui.last.list = '';
  }

  console.log('ui groups: grouping, parent_call merge, solo split, expand/collapse, tasks, filter/search and xss escaping passed');
})().catch(e => {
  console.error(e);
  process.exitCode = 1;
});

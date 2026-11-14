"""会审、共享进度板、排工提示词和时限提醒的离线回归；全部用假后端，不调用任何真实模型。"""
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Fake:
    """按后端名字决定回答；记录每次收到的提示词。"""

    def __init__(self, answers, barrier=None, fail=()):
        self.answers, self.barrier, self.fail = answers, barrier, set(fail)
        self.prompts, self.lock = [], threading.Lock()

    def make(self, g, kind):
        def fn(cfg, mdl, prompt, cwd, write, timeout):
            spec = kind + (":" + mdl if mdl else "")
            with self.lock:
                self.prompts.append((spec, prompt, write))
            synth = "几位成员各自独立回答了同一个问题" in prompt
            if self.barrier and not synth:
                self.barrier.wait(timeout=5)  # 三位必须同时在跑才能一起过这道门
            if spec in self.fail or (synth and "synth" in self.fail):
                raise g['BackendError']("假失败")
            return "综合结论" if synth else self.answers.get(spec, "回答 " + spec)
        return fn


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ, {'HUB_HOME': self.tmp.name}):
            ns = runpy.run_path(str(ROOT / 'hub'))
        self.g = ns['ask'].__globals__
        self.cfg = self.g['load_config']()
        self.g['fetch_quota'] = lambda cfg: None  # 测试里绝不真的去读额度（会访问网络和账号）
        # 每位只留一个后端，后端名字互不相同，便于辨认是谁在答
        self.cfg['agents'] = {'gemini': ['agy:g'], 'claude': ['claude:opus'], 'gpt': ['codex:x'], 'ds': ['dsh']}

    def quota(self, **pcts):
        now = time.time()
        agents = {}
        for name, v in pcts.items():
            pct, age = v if isinstance(v, tuple) else (v, 0)
            agents[name] = {'ts': now - age, 'windows': [{'label': '5 小时', 'remaining': pct, 'resets': now + 3600}]}
        self.g['write_json'](self.g['QUOTA_PATH'], {'ts': now, 'agents': agents})

    def council(self, fake, **kw):
        g = self.g
        backends = {k: fake.make(g, k) for k in ('agy', 'claude', 'codex', 'dsh')}
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(g['BACKENDS'], backends), redirect_stdout(out), redirect_stderr(err):
            try:
                rc = g['run_council'](self.cfg, kw.pop('q', '要不要买新音箱？'), self.tmp.name, **kw)
            except g['BackendError'] as e:
                rc = e
        runs = g['load_runs']()
        return rc, runs[0] if runs else None, err.getvalue()


class CouncilTests(Base):
    def test_parallel_independent_default_members_single_synthesis(self):
        fake = Fake({'agy:g': 'ANS-G', 'codex:x': 'ANS-P', 'dsh': 'ANS-D'}, barrier=threading.Barrier(3))
        rc, run, _ = self.council(fake)
        self.assertEqual(rc, 0)
        self.assertEqual(run['mode'], 'council')
        self.assertEqual(run['participants'], ['gemini', 'gpt', 'ds'])  # 默认没有 Claude
        self.assertFalse(any(spec.startswith('claude') for spec, _, _ in fake.prompts))
        workers = [p for p in fake.prompts if '几位成员各自独立回答' not in p[1]]
        synth = [p for p in fake.prompts if '几位成员各自独立回答' in p[1]]
        self.assertEqual(len(workers), 3)
        self.assertEqual(len(synth), 1)
        for spec, prompt, write in workers:
            self.assertFalse(write)  # 会审只读
            for other in ('ANS-G', 'ANS-P', 'ANS-D'):
                self.assertNotIn(other, prompt)  # 初答看不到别人的答案
            self.assertIn('共享进度板', prompt)
        for a in ('ANS-G', 'ANS-P', 'ANS-D'):
            self.assertIn(a, synth[0][1])
        self.assertEqual(run['status'], 'done')
        self.assertEqual(run['final'], '综合结论')
        self.assertTrue(all(t['status'] == 'ok' and t['progress'] for t in run['tasks']))

    def test_quota_threshold_unknown_and_stale(self):
        self.quota(gpt=14, ds=15, gemini=(3, 7 * 3600))  # gemini 数据过期：当未知，不跳过
        rc, run, err = self.council(Fake({}))
        tasks = {t['agent']: t for t in run['tasks']}
        self.assertEqual(tasks['gpt']['status'], 'skipped')
        self.assertIn('14%', tasks['gpt']['skip_reason'])
        self.assertEqual(tasks['ds']['status'], 'ok')
        self.assertEqual(tasks['gemini']['status'], 'ok')
        self.assertEqual(run['status'], 'done')  # 按规则跳过不算失败，但注明
        self.assertIn('gpt', run['error'])
        self.assertIn('跳过', err)
        self.assertEqual(self.g['quota_skip']('claude')[1], '额度未知')

    def test_low_quota_synthesizer_replaced(self):
        self.quota(gemini=5)
        fake = Fake({})
        rc, run, _ = self.council(fake)
        self.assertEqual(run['synthesizer'], 'gpt')
        synth = [s for s, p, _ in fake.prompts if '几位成员各自独立回答' in p]
        self.assertEqual(synth, ['codex:x'])

    def test_only_one_member_no_synthesis(self):
        self.quota(gpt=1, ds=2)
        fake = Fake({'agy:g': '唯一的回答'})
        rc, run, _ = self.council(fake)
        self.assertEqual(len(fake.prompts), 1)
        self.assertIn('没有形成多方会审', run['final'])
        self.assertIn('唯一的回答', run['final'])
        self.assertEqual(run['status'], 'failed')

    def test_no_member_available(self):
        self.quota(gemini=1, gpt=1, ds=1)
        fake = Fake({})
        rc, run, _ = self.council(fake)
        self.assertIsInstance(rc, self.g['BackendError'])
        self.assertEqual(fake.prompts, [])
        self.assertEqual(run['status'], 'failed')
        self.assertIn('没有成员', run['error'])

    def test_one_failure_keeps_others(self):
        fake = Fake({}, fail=['dsh'])
        rc, run, _ = self.council(fake)
        tasks = {t['agent']: t for t in run['tasks']}
        self.assertEqual(tasks['ds']['status'], 'fail')
        self.assertEqual(tasks['gemini']['status'], 'ok')
        self.assertEqual(run['status'], 'failed')
        self.assertIn('1 位没有答复', run['error'])
        synth = [p for s, p, _ in fake.prompts if '几位成员各自独立回答' in p][0]
        self.assertIn('缺席或失败', synth)

    def test_all_fail_and_synth_fail(self):
        rc, run, _ = self.council(Fake({}, fail=['agy:g', 'codex:x', 'dsh']))
        self.assertEqual(run['error'], '没有成员给出回答')
        rc, run, _ = self.council(Fake({'agy:g': 'A1', 'dsh': 'A3'}, fail=['synth']))
        self.assertEqual(run['error'], '综合失败')
        self.assertIn('A1', run['final'])
        self.assertIn('A3', run['final'])

    def test_same_backend_fallback_is_flagged(self):
        self.cfg['agents']['gpt'] = ['codex:x', 'agy:g']
        rc, run, _ = self.council(Fake({}, fail=['codex:x']))
        self.assertTrue(run['same_backend'])
        self.assertIn('同一个模型', run['final'])

    def test_explicit_members_and_old_config(self):
        rc, run, _ = self.council(Fake({}), members=['ds', 'gemini', 'ds', 'nobody'])
        self.assertEqual(run['participants'], ['ds', 'gemini'])
        cfg = self.g['deep_merge'](self.g['DEFAULT_CONFIG'], {'planner': 'claude'})  # 旧配置没有会审字段
        self.assertEqual(self.g['council_members'](cfg), ['gemini', 'gpt', 'ds'])
        self.assertEqual(cfg['planner'], 'claude')  # 已有的显式设置不被覆盖

    def test_ui_state_mode_and_old_runs(self):
        g = self.g
        old = Path(g['RUNS_DIR']) / '20200101-000000'
        old.mkdir(parents=True)
        (old / 'run.json').write_text(json.dumps({'id': '20200101-000000', 'goal': 'x', 'status': 'done', 'tasks': []}))
        self.council(Fake({}))
        with patch.dict(g, {'refresh_quota': lambda: None, 'backend_choices': lambda c: [],
                            'codex_defaults': lambda: ('', '')}):
            st = g['ui_state'](self.cfg)
        modes = {r['id']: r['mode'] for r in st['runs']}
        self.assertEqual(modes['20200101-000000'], 'run')
        self.assertIn('council', modes.values())
        self.assertEqual(st['config']['council_agents'], ['gemini', 'gpt', 'ds'])

    def test_run_board_shares_progress_and_leftovers(self):
        g = self.g
        plan = json.dumps({'summary': '先查后审', 'tasks': [
            {'id': 't1', 'agent': 'ds', 'title': '查资料', 'why': '快', 'eta_min': 3, 'prompt': '查', 'depends_on': []},
            {'id': 't2', 'agent': 'gpt', 'title': '审查', 'why': '把关', 'eta_min': 'x', 'prompt': '审', 'depends_on': ['t1']}]})
        seen = {}

        def agy(cfg, mdl, prompt, *a):
            return plan if '排工' in prompt else '汇总好了'

        def dsh(cfg, mdl, prompt, *a):
            seen['t1'] = prompt
            return '资料如下\n【进度】三家都查完了\n【遗留】价格可能过时'

        def codex(cfg, mdl, prompt, *a):
            seen['t2'] = prompt
            return '审查通过\n【进度】看完了\n【遗留】无'

        with patch.dict(g['BACKENDS'], {'agy': agy, 'dsh': dsh, 'codex': codex}), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = g['run_goal'](self.cfg, '比较云盘', self.tmp.name, False, 'gemini', 'gemini', 3, 6, False)
        self.assertEqual(rc, 0)
        self.assertIn('你负责：t1', seen['t1'])
        self.assertIn('进度：三家都查完了', seen['t2'])  # 后来的人看得到前面的进度和遗留
        self.assertIn('遗留：价格可能过时', seen['t2'])
        run = g['load_runs']()[0]
        t1, t2 = run['tasks']
        self.assertEqual((t1['progress'], t1['leftover'], t1['why'], t1['eta_min']), ('三家都查完了', '价格可能过时', '快', 3))
        self.assertIsNone(t2['leftover'])
        self.assertIsNone(t2['eta_min'])
        board = (Path(g['RUNS_DIR']) / run['id'] / 'board.md').read_text()
        self.assertIn('价格可能过时', board)

    def test_untouched_old_profiles_upgraded_custom_kept(self):
        g = self.g
        Path(g['CONFIG_PATH']).write_text(json.dumps({'profiles': dict(g['OLD_PROFILES'], gpt='我自己写的')}))
        cfg = g['load_config']()
        self.assertIn('拍板', cfg['profiles']['claude'])
        self.assertIn('主力干活', cfg['profiles']['gemini'])
        self.assertEqual(cfg['profiles']['gpt'], '我自己写的')

    def test_plan_prompt_is_scheduling_and_simple_stays_single(self):
        p = self.g['PLAN_PROMPT']
        for word in ('排工', '只排 1 个任务', '审查', 'eta_min', '{quota_rule}'):
            self.assertIn(word, p)

    def test_quota_guard_switch(self):
        # 默认：低于 15% 自动跳过；用户关掉后照样参加，说明里写清楚
        g = self.g
        now = time.time()
        Path(g['QUOTA_PATH']).write_text(json.dumps({'ts': now, 'agents': {'gpt': {'ts': now, 'windows': [
            {'label': '5 小时', 'remaining': 6, 'resets': now + 3600}]}}}))
        Path(g['CONFIG_PATH']).write_text(json.dumps({}))
        self.assertTrue(g['quota_guard_on']())
        self.assertIsNotNone(g['quota_skip']('gpt')[0])
        Path(g['CONFIG_PATH']).write_text(json.dumps({'quota_guard': False}))
        self.assertFalse(g['quota_guard_on']())
        reason, note = g['quota_skip']('gpt')
        self.assertIsNone(reason)
        self.assertIn('照样', note)

    def test_timeout_warning(self):
        tw = self.g['timeout_warning']
        self.assertIsNone(tw(None))
        self.assertIsNone(tw(900))
        self.assertIn('少于 15 分钟', tw(120))
        self.cfg['timeout'] = 300
        rc, run, err = self.council(Fake({}))
        self.assertIn('提醒', err)
        self.assertTrue(run['timeout_warning'])

    def test_parse_report(self):
        pr = self.g['parse_report']
        self.assertEqual(pr('正文\n**【进度】** 完成一半\n- 【遗留】：第三节没写'), ('完成一半', '第三节没写'))
        self.assertEqual(pr('只有正文')[1], None)
        self.assertEqual(pr('只有正文')[0], '只有正文')


class ChatTests(Base):
    """主联络窗口：联络人选择、直接回答、替用户派活、换人说明。"""

    def test_choose_contact(self):
        cc = self.g['choose_contact']
        BE = self.g['BackendError']
        self.assertEqual(cc(self.cfg, '随便聊聊', 'ds')[0], 'ds')
        with self.assertRaises(BE):
            cc(self.cfg, '随便聊聊')  # 额度全都读不到：自动模式不选人
        self.quota(gemini=80, gpt=50)
        self.assertEqual(cc(self.cfg, '帮我想想周末去哪')[:2], ('gpt', 'plan'))  # 定方案：拍板的人
        name, phase, why = cc(self.cfg, '帮我写个脚本批量改名')
        self.assertEqual((name, phase), ('gemini', 'build'))  # 动手：Gemini 干活
        self.assertIn('动手', why)
        self.quota(gemini=80, gpt=10)
        name, _, why = cc(self.cfg, '帮我想想下一步')
        self.assertEqual(name, 'gemini')
        self.assertIn('gpt', why)  # 说明为什么没选它
        self.assertEqual(cc(self.cfg, '把这段话翻译成英文')[1], 'wrap')
        self.assertNotEqual(cc(self.cfg, '随便聊聊')[0], 'claude')  # Claude 额度读不到，自动模式不选

    def chat(self, answers, msg='你好', meta=None, **kw):
        g = self.g
        fake = Fake(answers)
        backends = {k: fake.make(g, k) for k in ('agy', 'claude', 'codex', 'dsh')}
        env = {'HUB_META': json.dumps(meta or {})}
        with patch.dict(g['BACKENDS'], backends), patch.dict(os.environ, env), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            rc = g['run_chat'](self.cfg, msg, self.tmp.name, **kw)
        chats = [c for c in g['load_calls']() if c.get('kind') == 'chat']
        return rc, chats[0], fake, out.getvalue(), err.getvalue()

    def test_direct_answer(self):
        self.quota(gemini=80)
        rc, call, fake, out, err = self.chat({'agy:g': '你好呀'})
        self.assertEqual((rc, call['status'], call['answer'], call['agent']), (0, 'ok', '你好呀', 'gemini'))
        self.assertEqual(call['chat']['mode'], 'auto')
        self.assertIn('这次由 gemini 联络', call['chat']['handoff'])
        self.assertEqual(len(fake.prompts), 1)

    def test_dispatch_council_reports_back(self):
        self.quota(gemini=80, gpt=50, ds=50)
        rc, call, fake, out, err = self.chat({'agy:g': '【派活】会审：买 A 还是 B？'}, contact='gemini')
        self.assertEqual(call['dispatch']['mode'], 'council')
        run = [r for r in self.g['load_runs']() if r['id'] == call['dispatch']['run']][0]
        self.assertEqual(run['parent_call'], call['id'])
        self.assertIsNone(run['follows'])
        self.assertEqual(run['goal'], '买 A 还是 B？')
        self.assertIn('综合结论', call['answer'])
        self.assertIn('会审', call['answer'])
        self.assertEqual(call['status'], 'ok')
        self.assertEqual(call['chat']['reason'], '你指定的联络人')

    def test_dispatch_run_and_handoff(self):
        self.quota(gemini=80, gpt=50)
        rc, first, *_ = self.chat({'agy:g': '好的'}, contact='gemini')
        plan = json.dumps({'summary': 's', 'tasks': [{'id': 't1', 'agent': 'ds', 'title': '做', 'prompt': 'p'}]})

        def answers():
            return {'codex:x': '【派活】自动分工：写个小工具', 'agy:g': plan, 'dsh': '工具写好了'}
        rc, call, fake, out, err = self.chat(answers(), msg='帮我想想怎么做个小工具',
                                             meta={'follows': {'type': 'call', 'id': first['id']}})
        self.assertEqual(call['agent'], 'gpt')
        self.assertIn('现在由 gpt 接手（上一轮是 gemini）', call['chat']['handoff'])
        self.assertEqual(call['follows'], {'type': 'call', 'id': first['id']})
        self.assertEqual(call['dispatch']['mode'], 'run')
        self.assertIn('工具写好了', call['answer'])
        run = [r for r in self.g['load_runs']() if r['id'] == call['dispatch']['run']][0]
        self.assertEqual(run['parent_call'], call['id'])


class ReviewFixTests(Base):
    """Gemini 4d 审查提出的问题的回归。"""

    def test_readonly_propagates_and_blocks_write(self):
        g = self.g
        envs = []

        def agy(cfg, mdl, prompt, *a):
            envs.append(g['clean_env']())
            return 'ok'
        with patch.dict(g['BACKENDS'], {'agy': agy}):
            g['ask'](self.cfg, 'gemini', 'x', cwd=self.tmp.name, write=False, quiet=True)
            self.assertEqual(envs[-1].get('HUB_READONLY'), '1')
            g['ask'](self.cfg, 'gemini', 'x', cwd=self.tmp.name, write=True, quiet=True)
            self.assertNotIn('HUB_READONLY', envs[-1])
            with patch.dict(os.environ, {'HUB_READONLY': '1'}):
                with self.assertRaises(g['BackendError']):
                    g['ask'](self.cfg, 'gemini', 'x', cwd=self.tmp.name, write=True, quiet=True)

    def test_council_members_get_no_team_note(self):
        fake = Fake({})
        self.council(fake)
        workers = [p for _, p, _ in fake.prompts if '几位成员各自独立回答' not in p]
        self.assertTrue(workers)
        self.assertFalse(any('hub ask' in p for p in workers))

    def test_stopping_blocks_new_processes_and_fallbacks(self):
        g = self.g
        called = []
        g['_stopping'].set()
        try:
            with patch.dict(g['BACKENDS'], {'agy': lambda *a: called.append(1) or 'ok'}):
                with self.assertRaises(g['BackendError']):
                    g['ask'](self.cfg, 'gemini', 'x', cwd=self.tmp.name, quiet=True)
            with self.assertRaises(g['BackendError']):
                g['_run'](['true'], self.tmp.name, dict(os.environ), 5)
        finally:
            g['_stopping'].clear()
        self.assertEqual(called, [])

    def test_failed_synthesizer_replaced_and_error_order(self):
        fake = Fake({}, fail=['agy:g'])
        rc, run, _ = self.council(fake)
        self.assertEqual(run['synthesizer'], 'gpt')
        self.assertEqual(run['final'], '综合结论')
        self.assertIn('1 位没有答复', run['error'])
        rc, run, _ = self.council(Fake({}, fail=['agy:g']), members=['gemini', 'ds'])
        self.assertIn('1 位没有答复', run['error'])
        self.assertIn('未形成多方会审', run['error'])

    def test_report_lines_stripped_and_board_footer(self):
        g = self.g
        self.assertEqual(g['strip_report']('译文\n\n【进度】完成\n**【遗留】无**\n'), '译文')
        self.assertEqual(g['parse_report']('x\n**【遗留】无**')[1], None)
        state = {'goal': '背景\n你负责：别截断\n真正的目标', 'tasks': [{'id': 't1', 'agent': 'ds', 'title': '做', 'status': 'ok'}]}
        txt = g['board_text'](state, '-', True, footer=False)
        self.assertIn('[ds] 做', txt)
        state['display'] = '这次的要求'
        self.assertIn('整体目标：这次的要求', g['board_text'](state, 't1'))

    def test_bad_council_config_types(self):
        cm = self.g['council_members']
        for bad in (3, True, 'gemini', [['x'], 'ds']):
            self.cfg['council_agents'] = bad
            self.assertEqual(cm(self.cfg), [] if bad != [['x'], 'ds'] else ['ds'])


class ErrorTextTests(Base):
    """报错说人话：中文原因 + 建议、说清先后试了谁、原文留在技术细节、超时保留部分回答。"""

    def test_explain_common_errors(self):
        ex = self.g['explain_error']
        raw = ('agy 状态 ERROR：{"status": "ERROR", "response": "", "error": "print timeout after 15m0s with the turn '
               'still in progress; the response is partial"}')
        self.assertEqual(ex(raw)[0], '15 分钟内没做完，被掐断了')
        self.assertIn('拆小', ex(raw)[1])
        self.assertEqual(ex('超时（300s）')[0], '5 分钟内没做完，被掐断了')
        self.assertIn('额度', ex('Error 429: rate limit exceeded')[0])
        self.assertIn('登录', ex('Not logged in. Please run /login')[0])
        self.assertIn('找不到', ex('无法启动 agy：[Errno 2] No such file or directory')[0])
        self.assertIn('网络', ex('Unable to connect to API (ECONNRESET)')[0])
        self.assertIn('手动停止', ex('已手动停止')[0])
        self.assertIn('技术细节', ex('something weird')[0])

    def test_labels_and_failure_sentence(self):
        g = self.g
        self.assertEqual(g['spec_label']('agy:gemini-4-carbon-medium'), 'Gemini Carbon·中等')
        self.assertEqual(g['spec_label']('agy:gemini-4-carbon-high'), 'Gemini Carbon·高')
        self.assertEqual(g['spec_label']('agy:gemini-3.8-flash-high'), 'Gemini Flash·高')
        self.assertEqual(g['spec_label']('dsh'), 'DeepSeek')
        txt = g['failure_text']('gemini', [('agy:gemini-4-carbon-medium', 'print timeout after 15m0s'),
                                           ('agy:gemini-4-carbon-high', 'HTTP 503 Service Unavailable')])
        self.assertIn('先用 Gemini Carbon·中等 试了，15 分钟内没做完', txt)
        self.assertIn('又换 Gemini Carbon·高 试了，网络连接中断了', txt)
        self.assertIn('都没成功', txt)
        self.assertNotIn('后备都失败', txt)

    def test_ask_failure_keeps_detail_and_partial(self):
        g = self.g
        self.cfg['agents']['gemini'] = ['agy:gemini-4-carbon-medium', 'agy:gemini-4-carbon-high']

        def agy(cfg, mdl, prompt, *a):
            live = g['Live']()
            live.add('写到一半的内容 ' + mdl)
            live.close()
            raise g['BackendError']('agy 状态 ERROR：print timeout after 15m0s, the response is partial')
        with patch.dict(g['BACKENDS'], {'agy': agy}), redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(g['BackendError']) as cm:
                g['ask'](self.cfg, 'gemini', 'x', cwd=self.tmp.name)
        self.assertIn('先用 Gemini Carbon·中等', str(cm.exception))
        self.assertIn('换 Gemini Carbon·高 再试', err.getvalue())
        rec = [c for c in g['load_calls']() if c.get('agent') == 'gemini'][0]
        self.assertIn('print timeout after 15m0s', rec['error_detail'])  # 原文不丢
        self.assertEqual(rec['partial'], '写到一半的内容 gemini-4-carbon-high')
        self.assertEqual(rec['attempts'][0]['partial'], '写到一半的内容 gemini-4-carbon-medium')
        self.assertIn('没做完', rec['attempts'][0]['reason'])


class ChatReviewTests(ChatTests):
    """Gemini 4h 审查问题的回归。"""
    test_choose_contact = test_direct_answer = test_dispatch_council_reports_back = test_dispatch_run_and_handoff = None

    def test_weekly_window_counts(self):
        now = time.time()
        self.g['write_json'](self.g['QUOTA_PATH'], {'ts': now, 'agents': {'gpt': {'ts': now, 'windows': [
            {'label': '5 小时', 'remaining': 100, 'resets': now + 60}, {'label': '本周', 'remaining': 3, 'resets': now + 9000}]}}})
        reason, _ = self.g['quota_skip']('gpt')
        self.assertIn('本周', reason)

    def test_no_contact_leaves_failed_record(self):
        g = self.g
        with patch.dict(os.environ, {'HUB_META': json.dumps({'display': '你好', 'submission_id': 'sub1'})}), \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(g['BackendError']):
                g['run_chat'](self.cfg, '你好', self.tmp.name)
        c = [c for c in g['load_calls']() if c.get('kind') == 'chat'][0]
        self.assertEqual((c['status'], c['display'], c['submission_id']), ('fail', '你好', 'sub1'))
        self.assertIn('手动指定', c['error'])

    def test_mentioning_dispatch_mid_answer_does_not_dispatch(self):
        self.quota(gemini=80)
        rc, call, fake, *_ = self.chat({'agy:g': '用法是这样：回答里写 【派活】会审：问题 就行'})
        self.assertNotIn('dispatch', call)
        self.assertEqual(call['status'], 'ok')
        self.assertEqual(len(fake.prompts), 1)

    def test_phase_uses_this_turn_only(self):
        self.quota(gemini=80, gpt=50)
        meta = {'display': '选方案 A 还是 B？'}
        rc, call, *_ = self.chat({}, msg='===== 之前的对话 =====\n写代码 实现 函数\n===== 追问 =====\n选方案 A 还是 B？', meta=meta)
        self.assertEqual((call['agent'], call['chat']['phase']), ('gpt', 'plan'))
        self.assertEqual(call['title'], '联络：选方案 A 还是 B？')

    def test_dispatch_status_consistent_and_low_quota_planner_replaced(self):
        self.quota(gemini=5, gpt=50, ds=50)
        plan = json.dumps({'summary': 's', 'tasks': [{'id': 't1', 'agent': 'ds', 'title': '做', 'prompt': 'p'}]})
        seen = []
        g = self.g

        def codex(cfg, mdl, prompt, *a):
            seen.append(prompt[:20])
            return plan if '排工' in prompt else '【派活】自动分工：做个东西'
        fake = Fake({'dsh': '做好了'})
        with patch.dict(g['BACKENDS'], {'codex': codex, 'dsh': fake.make(g, 'dsh'), 'agy': fake.make(g, 'agy')}), \
                patch.dict(os.environ, {'HUB_META': '{}'}), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = g['run_chat'](self.cfg, '帮我想想', self.tmp.name, write=True)
        call = [c for c in g['load_calls']() if c.get('kind') == 'chat'][0]
        run = [r for r in g['load_runs']() if r['id'] == call['dispatch']['run']][0]
        self.assertEqual(run['planner'], 'gpt')  # gemini 只剩 5%，排工换人
        self.assertEqual((rc, call['status'], run['status']), (0, 'ok', 'done'))
        self.assertTrue(call['chat']['write'])
        self.assertIsNotNone(call['secs'])

    def test_follow_context_through_dispatched_run(self):
        g = self.g
        self.quota(gemini=80)
        rc, call, *_ = self.chat({'agy:g': '【派活】会审：买哪个'}, contact='gemini')
        rid = call['dispatch']['run']
        ctx = g['follow_context']('run', rid)
        self.assertIn('你好', ctx)  # 回到派活那一轮对话
        with patch.dict(os.environ, {'HUB_META': json.dumps({'follows': {'type': 'run', 'id': rid}})}):
            self.assertEqual(g['previous_contact'](), 'gemini')


if __name__ == '__main__':
    unittest.main()

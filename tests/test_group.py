"""群聊的离线回归：轮流发言、后面的人能看到前面的记录、全员「聊完了」提前结束；全用假后端。"""
import io
import os
import runpy
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ, {'HUB_HOME': self.tmp.name}):
            ns = runpy.run_path(str(ROOT / 'hub'))
        self.g = ns['ask'].__globals__
        self.g['fetch_quota'] = lambda cfg: None
        self.cfg = self.g['load_config']()
        self.cfg['agents'] = {'gemini': ['agy:g'], 'claude': ['claude:opus'], 'gpt': ['codex:x']}

    def chat(self, answer, **kw):
        g, prompts = self.g, []

        def mk(kind):
            def fn(cfg, mdl, prompt, cwd, write, timeout):
                prompts.append((kind, prompt, write))
                return answer(kind, prompt)
            return fn
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(g['BACKENDS'], {k: mk(k) for k in ('agy', 'claude', 'codex')}), redirect_stdout(out), redirect_stderr(err):
            try:
                rc = g['run_group'](self.cfg, kw.pop('topic', '聊聊音箱'), self.tmp.name, **kw)
            except g['BackendError'] as e:
                rc = e
        runs = g['load_runs']()
        return rc, runs[0] if runs else None, prompts

    def test_take_turns_and_see_log(self):
        rc, run, prompts = self.chat(lambda k, p: "我是" + k, seats=['gemini', 'gpt'], rounds=2)
        self.assertEqual(rc, 0)
        self.assertEqual(run['mode'], 'group')
        self.assertEqual([t['agent'] for t in run['tasks']], ['gemini', 'gpt', 'gemini', 'gpt'])
        self.assertNotIn('我是', prompts[0][1])           # 第一位还没有记录
        self.assertIn('【gemini】我是agy', prompts[1][1])  # 第二位能看到第一位
        self.assertTrue(all(not w for _, _, w in prompts))  # 只读
        self.assertIn('【gpt】我是codex', run['final'])

    def test_all_say_done_ends_early(self):
        rc, run, prompts = self.chat(lambda k, p: "说完了\n【聊完了】", seats=['gemini', 'claude'], rounds=5)
        self.assertEqual(rc, 0)
        self.assertEqual(len(run['tasks']), 2)
        self.assertNotIn('【聊完了】', run['tasks'][0]['answer'])

    def test_needs_two_members(self):
        rc, run, _ = self.chat(lambda k, p: "x", seats=['gemini'])
        self.assertIsInstance(rc, self.g['BackendError'])

    def test_one_failure_does_not_stop_chat(self):
        def ans(k, p):
            if k == 'codex':
                raise self.g['BackendError']("假失败")
            return "ok " + k
        rc, run, _ = self.chat(ans, seats=['gemini', 'gpt'], rounds=2)
        self.assertEqual(rc, 0)
        self.assertEqual([t['status'] for t in run['tasks']], ['ok', 'fail', 'ok', 'fail'])

    def test_same_agent_two_models(self):
        seen = []

        def ans(k, p):
            return "回答"
        g = self.g
        orig = g['ask']

        def spy(cfg, agent, prompt, **kw):
            seen.append((agent, kw.get('spec')))
            return orig(cfg, agent, prompt, **kw)
        with patch.dict(g, {'ask': spy}):
            rc, run, prompts = self.chat(ans, seats=['gpt=codex:sol', 'gpt=codex:astra'], rounds=1)
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [('gpt', 'codex:sol'), ('gpt', 'codex:astra')])
        self.assertEqual(len(set(t['label'] for t in run['tasks'])), 2)


if __name__ == '__main__':
    unittest.main()

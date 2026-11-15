"""看进展的时限与后备接力；只启动临时假 CLI，不访问账号。"""
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PARTIAL = '已经完成的部分'
CONTINUE = '（前一位做到一半被停下了，以下是它已经写出的部分，请在此基础上接着做完，不要从头再来：）\n'

FAKE = r'''
import json, os, sys, time
from pathlib import Path

kind = Path(sys.argv[0]).name.removeprefix('fake-')
model = next((sys.argv[i + 1] for i, arg in enumerate(sys.argv[:-1]) if arg in ('--model', '-m')), '')
keep = '--input-format' in sys.argv

def send(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)

def text(value):
    if kind == 'agy':
        send({'step_update': {'step_type': 'agent_response', 'step_index': 0, 'text_delta': value}})
    elif kind == 'codex':
        send({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': value}})
    elif kind == 'dsh':
        send({'type': 'text', 'text': value})

def turn(prompt):
    with open(Path(__file__).parent / 'invocations.jsonl', 'a') as f:
        f.write(json.dumps({'model': model, 'prompt': prompt, 'argv': sys.argv}, ensure_ascii=False) + '\n')
    mode = model if model in ('stall', 'next') else prompt
    if mode == 'silent':
        time.sleep(30)
    if mode == 'stall':
        text('已经完成的部分')
        time.sleep(30)
    if mode in ('repeat7', 'repeat8', 'mcp8'):
        text('已经完成的部分')
        for i in range(7 if mode == 'repeat7' else 8):
            if kind == 'agy':
                send({'step_update': {'step_type': 'tool', 'state': 'ACTIVE', 'tool_name': 'read_file',
                                     'tool_info': {'parameters': {'path': '/same.txt'}}}})
            else:
                item = ({'type': 'mcp_tool_call', 'server': 'files', 'tool': 'read', 'arguments': {'path': '/same.txt'}}
                        if mode == 'mcp8' else {'type': 'command_execution', 'command': 'cat /same.txt'})
                send({'type': 'item.started', 'item': item})
        if mode != 'repeat7':
            time.sleep(30)
    if mode in ('active', 'stderr'):
        for i in range(6):
            if mode == 'stderr':
                print('正在干活', file=sys.stderr, flush=True)
            else:
                text('正在干活')
            time.sleep(.1)
    if kind == 'claude':
        if mode == 'delayed':
            time.sleep(.35)
        send({'result': '完成', 'session_id': 'claude-session', 'usage': {'output_tokens': 2}})
    elif kind == 'agy':
        send({'event': 'result', 'result': {'status': 'SUCCESS', 'response': '完成', 'conversation_id': 'conv-1'}})
    elif kind == 'codex':
        Path(sys.argv[sys.argv.index('-o') + 1]).write_text('完成', encoding='utf-8')
    else:
        send({'type': 'final', 'text': '完成'})

if keep:
    for line in sys.stdin:
        turn(json.loads(line)['message']['content'])
else:
    prompt = next((arg[len('--print='):] for arg in sys.argv if arg.startswith('--print=')), None)
    turn(sys.stdin.read() if prompt is None else prompt)
'''


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        with patch.dict(os.environ, {'HUB_HOME': self.tmp.name}):
            ns = runpy.run_path(str(ROOT / 'hub'))
        self.g = ns['ask'].__globals__
        self.cfg = self.g['load_config']()
        self.cfg.update(timeout=.1, idle_timeout=.4, hard_timeout=2, keep_sessions=False)
        for kind in ('agy', 'codex', 'dsh', 'claude'):
            fake = self.home / ('fake-' + kind)
            fake.write_text('#!%s\n%s' % (sys.executable, FAKE), encoding='utf-8')
            fake.chmod(0o755)
            self.cfg['bins'][kind] = str(fake)
        self.addCleanup(self.close_keeps)

    def close_keeps(self):
        for kid in list(self.g['_keep_processes']):
            self.g['keep_close'](kid)

    def backend(self, kind, prompt, **cfg):
        self.g['_ctx'].partial = None
        return self.g['BACKENDS'][kind](dict(self.cfg, **cfg), 'normal', prompt, self.tmp.name, False, .1)

    def ask(self, kind='test'):
        return self.g['ask'](self.cfg, 'gemini', '任务', cwd=self.tmp.name, quiet=True, note=False,
                              meta={'kind': kind})

    def invocations(self):
        return [json.loads(line) for line in (self.home / 'invocations.jsonl').read_text().splitlines()]

    def test_streaming_backends_can_finish_after_soft_limit(self):
        for kind in ('agy', 'codex', 'dsh'):
            with self.subTest(kind=kind):
                start = time.monotonic()
                self.assertEqual(self.backend(kind, 'active'), '完成')
                self.assertGreater(time.monotonic() - start, .5)
        argv = self.invocations()[0]['argv']
        self.assertEqual(argv[argv.index('--print-timeout') + 1], '2s')
        self.assertFalse(self.g['_children'])

    def test_silent_streaming_backends_stop_when_idle(self):
        for kind in ('agy', 'codex', 'dsh'):
            with self.subTest(kind=kind):
                start = time.monotonic()
                with self.assertRaisesRegex(self.g['BackendError'], r'^卡住了（'):
                    self.backend(kind, 'silent')
                elapsed = time.monotonic() - start
                self.assertGreaterEqual(elapsed, self.cfg['idle_timeout'])
                self.assertLess(elapsed, 2)
                self.assertFalse(self.g['_children'])

    def test_stderr_also_counts_as_activity(self):
        self.assertEqual(self.backend('agy', 'stderr'), '完成')

    def test_continuous_output_stops_at_hard_limit_and_keeps_partial(self):
        for kind in ('agy', 'codex', 'dsh'):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(self.g['BackendError'], r'^超时（到总上限 '):
                    self.backend(kind, 'active', hard_timeout=.3)
                self.assertIn('正在干活', self.g['_ctx'].partial)
                self.assertFalse(self.g['_children'])

    def test_eighth_identical_tool_call_stops_agy_and_codex(self):
        for kind in ('agy', 'codex'):
            with self.subTest(kind=kind):
                self.assertEqual(self.backend(kind, 'repeat7'), '完成')
                with self.assertRaisesRegex(self.g['BackendError'], r'^空转（反复做同一件事：'):
                    self.backend(kind, 'repeat8')
                self.assertIn(PARTIAL, self.g['_ctx'].partial)
                self.assertFalse(self.g['_children'])
        with self.assertRaisesRegex(self.g['BackendError'], r'^空转（'):
            self.backend('codex', 'mcp8')

    def test_tool_identity_uses_all_parameters_and_ignores_key_order(self):
        watch = self.g['Watchdog'](self.cfg, .1)
        for i in range(8):
            watch.tool('read', {'path': 'same', 'offset': i})
        watch.check()
        for _ in range(6):
            watch.tool('read', {'offset': 0, 'path': 'same'})
        watch.check()  # 加上前面那一次，一共七次
        watch.tool('read', {'path': 'same', 'offset': 0})
        with self.assertRaisesRegex(self.g['BackendError'], '^空转'):
            watch.check()

    def test_claude_uses_only_hard_limit_and_keeps_json_parsing(self):
        self.assertEqual(self.backend('claude', 'delayed', idle_timeout=.15), '完成')
        self.assertEqual(self.g['_ctx'].session['id'], 'claude-session')
        self.assertEqual(self.g['_ctx'].tokens['out'], 2)
        with self.assertRaisesRegex(self.g['BackendError'], r'^超时（到总上限 '):
            self.backend('claude', 'silent', hard_timeout=.3)

    def test_explicit_soft_limit_can_raise_hard_limit(self):
        self.cfg.update(timeout=.1, hard_timeout=.2)
        self.cfg['agents']['gemini'] = ['agy:normal']
        text, _ = self.g['ask'](self.cfg, 'gemini', 'active', cwd=self.tmp.name, timeout=1,
                               quiet=True, note=False, meta={'kind': 'test'})
        self.assertEqual(text, '完成')
        argv = self.invocations()[0]['argv']
        self.assertEqual(argv[argv.index('--print-timeout') + 1], '1s')
        self.assertEqual(self.cfg['hard_timeout'], .2)

    def test_duplicate_failed_specs_are_skipped_even_when_not_adjacent(self):
        self.cfg['agents']['gemini'] = ['agy:a', 'agy:a', 'agy:b', 'agy:a']
        called = []

        def fail(cfg, model, *args):
            called.append(model)
            raise self.g['BackendError']('网络 connection error')

        with patch.dict(self.g['BACKENDS'], agy=fail):
            with self.assertRaises(self.g['BackendError']):
                self.ask()
        self.assertEqual(called, ['a', 'b'])
        rec = self.g['load_calls']()[0]
        self.assertEqual(len(rec['attempts']), 4)
        skipped = [a for a in rec['attempts'] if a.get('skipped')]
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all(a['reason'] == '备用和刚才的是同一个模型，不再重跑' for a in skipped))

    def test_idle_partial_is_preserved_and_forwarded_to_different_model(self):
        self.cfg['agents']['gemini'] = ['agy:stall', 'agy:stall', 'agy:next']
        self.assertEqual(self.ask(), ('完成', 'agy:next'))
        calls = self.invocations()
        self.assertEqual([c['model'] for c in calls], ['stall', 'next'])
        self.assertEqual(calls[1]['prompt'], '任务\n\n' + CONTINUE + PARTIAL)
        rec = self.g['load_calls']()[0]
        self.assertEqual(rec['partial'], PARTIAL)
        self.assertEqual(rec['attempts'][0]['partial'], PARTIAL)
        self.assertTrue(rec['attempts'][0]['error'].startswith('卡住了'))
        self.assertTrue(rec['attempts'][1]['skipped'])

    def test_watchdog_resume_failure_does_not_retry_same_model(self):
        self.cfg['agents']['gemini'] = ['agy:stall', 'agy:next']
        resume = {'backend': 'agy:stall', 'path': str(self.home / 'old.json'), 'sid': 'old',
                  'prompt': '接着上轮', 'from': 'c_old'}
        with patch.dict(self.g, resume_plan=lambda *a: resume):
            self.assertEqual(self.ask(kind='ask'), ('完成', 'agy:next'))
        calls = self.invocations()
        self.assertEqual([c['model'] for c in calls], ['stall', 'next'])
        self.assertIn(CONTINUE + PARTIAL, calls[1]['prompt'])

    def test_watchdog_continuation_is_limited_to_first_6000_characters(self):
        for error in ('卡住了（1 分钟没有任何动静）', '空转（反复做同一件事：read）',
                      '超时（到总上限 1 分钟）'):
            with self.subTest(error=error):
                self.cfg['agents']['gemini'] = ['agy:first', 'agy:next']
                prompts = []

                def fake(cfg, model, prompt, *args):
                    prompts.append(prompt)
                    if model == 'first':
                        self.g['_ctx'].partial = '甲' * 6000 + '不带这一段'
                        raise self.g['BackendError'](error)
                    return '完成'

                with patch.dict(self.g['BACKENDS'], agy=fake):
                    self.ask()
                self.assertEqual(prompts[1], '任务\n\n' + CONTINUE + '甲' * 6000)

    def test_keep_session_can_finish_after_soft_limit_and_reuse_process(self):
        self.assertEqual(self.backend('agy', 'active', _keep=True), '完成')
        first = self.g['keep_list']()[0]
        self.assertEqual(self.backend('agy', 'active', _keep=True, _resume='conv-1'), '完成')
        second = self.g['keep_list']()[0]
        self.assertEqual((first['pid'], first['id']), (second['pid'], second['id']))
        self.assertEqual(second['turns'], 2)

    def test_keep_watchdog_stops_clean_up_process_and_preserve_partial(self):
        for prompt, cfg, prefix, partial in (
                ('silent', {}, '^卡住了', None),
                ('stall', {}, '^卡住了', PARTIAL),
                ('repeat8', {}, '^空转', PARTIAL),
                ('active', {'hard_timeout': .3}, '^超时（到总上限 ', '正在干活')):
            with self.subTest(prompt=prompt):
                with self.assertRaisesRegex(self.g['BackendError'], prefix):
                    self.backend('agy', prompt, _keep=True, **cfg)
                if partial:
                    self.assertIn(partial, self.g['_ctx'].partial)
                self.assertFalse(self.g['_keep_processes'])
                self.assertFalse(self.g['_active_keeps'])
                self.assertEqual(list(Path(self.g['KEEP_DIR']).iterdir()), [])

    def test_failure_text_explains_watchdog_stops(self):
        for error, phrase in (('卡住了（5 分钟没有任何动静）', '没有任何动静'),
                              ('空转（反复做同一件事：read）', '反复做同一件事'),
                              ('超时（到总上限 60 分钟）', '最长等待时间')):
            text = self.g['failure_text']('gemini', [('agy:m', error)])
            self.assertIn(phrase, text)
            self.assertNotIn('原因见技术细节', text)


if __name__ == '__main__':
    unittest.main()

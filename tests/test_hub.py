"""离线回归；所有数据及子进程都在临时 HUB_HOME 内。"""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class HubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ, {'HUB_HOME': self.tmp.name}):
            ns = runpy.run_path(str(ROOT / 'hub'))
        self.g = ns['ask'].__globals__
        self.cfg = self.g['load_config']()

    def test_live_trailing_and_same_size(self):
        g = self.g
        g['_ctx'].call_id = 'c_abc'
        live = g['Live']()
        live.add('a')
        old = g['live_len']('c_abc')
        live.text = 'b'
        live.flush(True)
        self.assertNotEqual(old, g['live_len']('c_abc'))
        live.add('c')
        time.sleep(.8)
        self.assertEqual(g['read_live']('c_abc')['text'], 'bc')
        live.close()
        self.assertIsNone(g['read_live']('c_abc'))

    def test_stream_and_input(self):
        lines = []
        rc, out, err = self.g['_run']([sys.executable, '-c',
            'import sys; print(sys.stdin.read()); print("err",file=sys.stderr)'],
            self.tmp.name, os.environ.copy(), 3, '你好', lines.append)
        self.assertEqual((rc, out, err), (0, '你好\n', 'err\n'))
        self.assertEqual(lines, ['你好\n'])
        self.assertFalse(self.g['_children'])

    def test_timeout_descendant_after_parent_exit(self):
        pidfile = Path(self.tmp.name) / 'child.pid'
        code = ('import os,signal,time; p=os.fork(); '
                '\nif p == 0:\n signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                'open(%r,"w").write(str(os.getpid())); time.sleep(30)\n' % str(pidfile))
        start = time.monotonic()
        try:
            with self.assertRaises(self.g['BackendError']):
                self.g['_run']([sys.executable, '-c', code], self.tmp.name,
                               os.environ.copy(), .5, on_line=lambda s: None)
            self.assertLess(time.monotonic() - start, 6)
            pid = int(pidfile.read_text())
            for _ in range(30):
                state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                                       capture_output=True, text=True).stdout.strip()
                if not state or state.startswith('Z'):
                    break
                time.sleep(.1)
            self.assertTrue(not state or state.startswith('Z'), state)
        finally:
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_stop_marks_manual(self):
        g = self.g
        rec = {'id': 'c_abc', 'pid': 99999999, 'status': 'running', 'start': time.time()}
        path = os.path.join(g['CALLS_DIR'], 'c_abc.json')
        g['write_json'](path, rec)
        with patch.dict(g, {'ui_record': lambda *a: rec,
                            'pid_alive': lambda p: False}):
            self.assertEqual(g['stop_record']('call', 'c_abc'), '它已经不在运行了')
        with patch.dict(g, {'ui_record': lambda *a: rec}), \
             patch.dict(g, {'pid_alive': unittest.mock.Mock(side_effect=[True, False, False])}), \
             patch.object(subprocess, 'check_output', return_value='/tmp/hub ask gemini'), \
             patch.object(os, 'kill'):
            self.assertIsNone(g['stop_record']('call', 'c_abc'))
        self.assertEqual(g['read_json'](path)['error'], g['STOP_MSG'])

    def test_plan_rejects_cycle_and_dry_saved(self):
        g = self.g
        def task(tid, deps):
            return dict(id=tid, agent='gemini', prompt='test', depends_on=deps)
        with patch.dict(g, {'ask': lambda *a, **k: (json.dumps({'tasks': [task('a',['b']), task('b',['a'])]}), 'fake')}):
            with self.assertRaises(g['BackendError']):
                g['make_plan'](self.cfg, 'test', self.tmp.name, False, 'gemini', 6)
        with patch.dict(g, {'ask': lambda *a, **k: (json.dumps({'tasks': [task('a',[])]}), 'fake')}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(g['run_goal'](self.cfg, 'test', self.tmp.name, False, 'gemini','gemini',1,6,True), 0)
        files = list(Path(g['RUNS_DIR']).glob('*/plan.json'))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text())['goal'], 'test')

    def test_context_restored_and_parallel_limit(self):
        g = self.g
        g['_ctx'].run_id = 'outer'
        g['_ctx'].call_id = 'parent'
        with patch.dict(g['BACKENDS'], {'agy': lambda *a: 'ok'}):
            g['ask'](self.cfg,'gemini','test',cwd=self.tmp.name)
        self.assertEqual((g['_ctx'].run_id, g['_ctx'].call_id), ('outer', 'parent'))
        plan = {'tasks': [dict(id=str(i), agent='gemini', title='t', prompt='x', depends_on=[],write=False) for i in range(3)]}
        def ask(*args, **kwargs):
            if kwargs.get('meta',{}).get('kind') == 'task':
                rec = g['load_runs']()[0]
                self.assertEqual(sum(t['status']=='running' for t in rec['tasks']), 1)
            return 'ok', 'fake'
        with patch.dict(g, {'make_plan': lambda *a, **k: plan, 'ask': ask}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(g['run_goal'](self.cfg,'test',self.tmp.name,False,'gemini','gemini',1,6,False),0)

    def test_follow_context_multiple_turns_and_cycle(self):
        g = self.g
        records = {'a': {'display':'第一问','answer':'第一答'},
                   'b': {'display':'第二问','answer':'第二答','follows':{'type':'call','id':'a'}}}
        with patch.dict(g, {'ui_record': lambda kind, rid: records.get(rid)}):
            result = g['follow_context']('call','b')
            self.assertLess(result.index('第一问'),result.index('第二问'))
            records['a']['follows'] = {'type':'call','id':'b'}
            self.assertEqual(result,g['follow_context']('call','b'))

    def test_quota_parsing_null_bad_rows_and_timezone(self):
        g = self.g
        sessions = Path(self.tmp.name)/'.codex/sessions/2026/01/01'
        sessions.mkdir(parents=True)
        event = {'timestamp':'2026-01-01T00:00:00Z','payload':{'rate_limits':{
            'primary':{'used_percent':25,'window_minutes':300,'resets_at':4102444800}}}}
        (sessions/'one.jsonl').write_text(json.dumps(event)+'\n'+json.dumps({'payload':{'rate_limits':None}})+'\n{bad')
        with patch.dict(g,{'HOME':self.tmp.name}):
            self.assertEqual(g['quota_codex']()['windows'][0]['remaining'],75)
        self.assertEqual(g['_iso_to_epoch']('2026-01-01T09:00:00+09:00'),g['_iso_to_epoch']('2026-01-01T00:00:00Z'))
        with patch.dict(g,{'find_bin':lambda *a:'fake','_run':lambda *a:(0,'Gemini\tfive_hour\t42%\t2026-01-01T09:00:00+09:00\nGemini\tweek\tnan%\tx','')}):
            q = g['quota_agy'](self.cfg)
            self.assertEqual(len(q['windows']),1)
            self.assertEqual(q['windows'][0]['remaining'],42)

    def test_login_failure_is_not_success(self):
        with patch.object(subprocess,'call',return_value=1):
            with self.assertRaises(ValueError):
                self.g['open_login'](self.cfg,'dsh')
        with patch.dict(self.g, {'find_bin':lambda *a:'/fake/cli'}), patch.object(subprocess,'call',return_value=0):
            self.g['open_login'](self.cfg,'codex')
        self.assertIn('exec /fake/cli login', (Path(self.tmp.name)/'login-codex.command').read_text())

    def test_resume_identifier_is_shell_quoted(self):
        g = self.g
        def fake_run(cmd, *args, **kwargs):
            Path(cmd[cmd.index('-o')+1]).write_text('收到')
            kwargs['on_line'](json.dumps({'thread_id':'session;echo BAD'}))
            return 0,'',''
        with patch.dict(g, {'find_bin':lambda *a:'/fake/cli','_run':fake_run}):
            self.assertEqual(g['backend_codex'](self.cfg,'','test',self.tmp.name,False,1),'收到')
        import shlex
        self.assertEqual(shlex.split(g['_ctx'].session['resume'])[-1],'session;echo BAD')

    def test_historical_fallback_survives_model_changes(self):
        g = self.g
        with patch.dict(g['BACKENDS'], {'agy': lambda *a: 'ok'}):
            g['ask'](self.cfg, 'gemini', 'test', cwd=self.tmp.name, model='gemini-custom')
        first = g['load_calls']()[0]
        self.assertEqual(first['preferred_backend'], 'agy:gemini-custom')
        old = dict(first, id='c_1234', backend='dsh', attempts=[{'backend':'codex'}])
        old.pop('preferred_backend')
        g['write_json'](os.path.join(g['CALLS_DIR'], old['id'] + '.json'), old)
        self.cfg['agents']['gemini'] = ['dsh']
        with patch.dict(g, {'refresh_quota':lambda:None, 'backend_choices':lambda c:[],
                            'codex_defaults':lambda:('', '')}):
            state = g['ui_state'](self.cfg)
        agent = next(a for a in state['agents'] if a['name']=='gemini')
        self.assertEqual(agent['fallback_today'], 1)
        calls = {c['id']:c for c in state['calls']}
        self.assertEqual(calls[first['id']]['preferred_backend'], 'agy:gemini-custom')
        self.assertEqual(calls['c_1234']['preferred_backend'], 'codex')

    def test_image_missing_artifact_marks_call_failed(self):
        g = self.g
        with patch.dict(g['BACKENDS'], {'codex': lambda *a:'已保存'}), \
             patch.object(sys, 'argv', ['hub','image','test','-o',str(Path(self.tmp.name)/'out.png')]), \
             patch.object(signal,'signal'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(g['main'](),1)
        self.assertEqual(g['load_calls']()[0]['status'],'fail')
        self.assertIn('没有生成',g['load_calls']()[0]['error'])


if __name__ == '__main__':
    unittest.main()

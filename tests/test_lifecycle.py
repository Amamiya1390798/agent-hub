"""异常路径的记录收尾和进程回收；使用临时数据及本地 Python 子进程。"""
import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ, {'HUB_HOME': self.tmp.name}):
            ns = runpy.run_path(str(ROOT / 'hub'))
        self.g = ns['ask'].__globals__
        self.cfg = self.g['load_config']()
        self.cfg['keep_sessions'] = False

    def fail(self, *args, **kwargs):
        raise ValueError('异常测试')

    def test_ask_unexpected_error_restores_context_and_marks_failure(self):
        g = self.g
        g['_ctx'].call_id, g['_ctx'].run_id, g['_ctx'].write = 'outer', 'run', True
        with patch.dict(g['BACKENDS'], agy=self.fail):
            with self.assertRaisesRegex(ValueError, '异常测试'):
                g['ask'](self.cfg, 'gemini', 'test', cwd=self.tmp.name)
        self.assertEqual((g['_ctx'].call_id, g['_ctx'].run_id, g['_ctx'].write), ('outer', 'run', True))
        rec = g['load_calls']()[0]
        self.assertEqual((rec['status'], rec['error']), ('fail', '异常测试'))
        self.assertIsNotNone(rec['end'])
        self.assertIsNotNone(rec['secs'])
        self.assertEqual(rec['attempts'], [])  # 编程异常继续抛出，不自动再叫一遍模型

    def test_start_callback_error_closes_record(self):
        with self.assertRaises(ValueError):
            self.g['ask'](self.cfg, 'gemini', 'test', cwd=self.tmp.name,
                           meta={'on_start': self.fail})
        self.assertEqual(self.g['load_calls']()[0]['status'], 'fail')
        self.assertIsNone(self.g['_ctx'].call_id)

    def test_keyboard_interrupt_closes_record_and_still_propagates(self):
        def interrupt(*args):
            raise KeyboardInterrupt
        with patch.dict(self.g['BACKENDS'], agy=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.g['ask'](self.cfg, 'gemini', 'test', cwd=self.tmp.name)
        self.assertEqual(self.g['load_calls']()[0]['error'], self.g['STOP_MSG'])
        self.assertIsNone(self.g['_ctx'].call_id)

    def test_planning_error_closes_run(self):
        with patch.dict(self.g, make_plan=self.fail):
            with self.assertRaises(ValueError):
                self.g['run_goal'](self.cfg, 'test', self.tmp.name, False, 'gemini', 'gemini', 1, 2, False)
        run = self.g['load_runs']()[0]
        self.assertEqual((run['status'], run['error']), ('failed', '异常测试'))
        self.assertIsNotNone(run['end'])

    def test_worker_error_closes_running_and_pending_tasks(self):
        plan = {'tasks': [dict(id=tid, agent='gemini', title=tid, prompt='test', write=False, depends_on=deps)
                          for tid, deps in [('a', []), ('b', ['a'])]]}
        with patch.dict(self.g, make_plan=lambda *a, **k: plan), patch.dict(self.g['BACKENDS'], agy=self.fail):
            with self.assertRaises(ValueError):
                self.g['run_goal'](self.cfg, 'test', self.tmp.name, False, 'gemini', 'gemini', 1, 2, False)
        run = self.g['load_runs']()[0]
        self.assertEqual(run['status'], 'failed')
        self.assertEqual([t['status'] for t in run['tasks']], ['fail', 'skipped'])
        self.assertTrue(all(c['status'] == 'fail' for c in self.g['load_calls']()))

    def test_council_callback_error_closes_pending_tasks(self):
        with patch.dict(self.g, quota_skip=lambda *a: (None, 'test')):
            with self.assertRaises(ValueError):
                self.g['run_council'](self.cfg, 'test', self.tmp.name, ['gemini', 'ds'], on_open=self.fail)
        run = self.g['load_runs']()[0]
        self.assertEqual(run['status'], 'failed')
        self.assertEqual([t['status'] for t in run['tasks']], ['skipped', 'skipped'])

    def test_chat_dispatch_error_closes_both_call_and_run(self):
        with patch.dict(self.g, make_plan=self.fail, pick_ok=lambda c, n: (n, None)), \
             patch.dict(self.g['BACKENDS'], agy=lambda *a: '【派活】自动分工：目标'), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                self.g['run_chat'](self.cfg, 'test', self.tmp.name, contact='gemini')
        self.assertEqual(self.g['load_calls']()[0]['status'], 'fail')
        self.assertEqual(self.g['load_runs']()[0]['status'], 'failed')

    def test_thread_start_failure_kills_child_and_closes_pipes(self):
        real_popen, procs = subprocess.Popen, []

        def spawn(*args, **kwargs):
            p = real_popen(*args, **kwargs)
            procs.append(p)
            return p

        with patch.object(subprocess, 'Popen', side_effect=spawn), \
             patch.object(threading.Thread, 'start', side_effect=RuntimeError('线程启动失败')):
            with self.assertRaisesRegex(RuntimeError, '线程启动失败'):
                self.g['_run']([sys.executable, '-c', 'import time; time.sleep(30)'],
                                self.tmp.name, os.environ.copy(), 2, stdin_text='test')
        self.assertTrue(procs)
        self.assertTrue(all(p.returncode is not None for p in procs))
        self.assertTrue(all(s.closed for p in procs for s in (p.stdin, p.stdout, p.stderr)))
        self.assertFalse(self.g['_children'])


if __name__ == '__main__':
    unittest.main()

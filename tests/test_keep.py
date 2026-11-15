"""常驻会话生命周期；只运行临时 Python 假后端，不使用账号或真实 CLI。"""
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


class KeepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        with patch.dict(os.environ, {'HUB_HOME': self.tmp.name}):
            ns = runpy.run_path(str(ROOT / 'hub'))
        self.g = ns['keep_turn'].__globals__
        self.addCleanup(self.close_keeps)
        self.fake = self.home / 'fake-agy'
        self.fake.write_text('''#!%s
import json, sys, time
model = sys.argv[sys.argv.index('--model') + 1]
if model == 'unsupported':
    print('STARTUP_DIAGNOSTIC', file=sys.stderr, flush=True)
    sys.exit(2)
if model == 'no-read':
    time.sleep(30)
for raw in sys.stdin:
    text = json.loads(raw)['message']['content']
    if text == 'exit':
        print('EXIT_DIAGNOSTIC', file=sys.stderr, flush=True)
        sys.exit(3)
    if text == 'stream':
        while True:
            print('{"event":"progress"}', flush=True)
            time.sleep(.001)
    event = {'result': {'status': 'SUCCESS', 'response': text, 'conversation_id': 'conv-1'}, 'event': 'result'}
    data = json.dumps(event, ensure_ascii=False) + '\\n'
    if text == 'fragment':
        sys.stdout.write(data[:15]); sys.stdout.flush(); time.sleep(.02)
        sys.stdout.write(data[15:]); sys.stdout.flush()
    else:
        print(data, end='', flush=True)
''' % sys.executable)
        self.fake.chmod(0o755)

    def close_keeps(self):
        for kid in list(self.g['_keep_processes']):
            self.g['keep_close'](kid)

    def turn(self, prompt='你好', model='normal', sid=None, timeout=5, callback=None):
        return self.g['keep_turn'](str(self.fake), model, prompt, self.tmp.name,
                                   False, timeout, sid, '测试', callback or (lambda line: None))

    def test_spaced_result_reuses_process_and_returns_clean_metadata(self):
        lines = []
        self.assertTrue(self.turn(callback=lines.append))
        first = self.g['keep_list']()[0]
        self.assertEqual((first['turns'], first['busy'], first['conv']), (1, False, 'conv-1'))
        self.assertTrue(self.turn('第二句', sid='conv-1', callback=lines.append))
        second = self.g['keep_list']()[0]
        self.assertEqual((second['id'], second['pid'], second['turns']), (first['id'], first['pid'], 2))
        self.assertEqual(json.loads(lines[-1])['result']['response'], '第二句')
        self.assertFalse(self.g['_active_keeps'])

    def test_partial_log_line_is_buffered(self):
        lines = []
        self.assertTrue(self.turn('fragment', callback=lines.append))
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])['result']['response'], 'fragment')

    def test_fifo_write_is_included_in_timeout(self):
        started = time.monotonic()
        with self.assertRaisesRegex(self.g['BackendError'], '超时'):
            self.turn('x' * 200000, model='no-read', timeout=.2)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(list(Path(self.g['KEEP_DIR']).iterdir()), [])
        self.assertFalse(self.g['_keep_processes'])
        self.assertFalse(self.g['_active_keeps'])

    def test_continuous_output_does_not_reset_timeout(self):
        started = time.monotonic()
        with self.assertRaisesRegex(self.g['BackendError'], '超时'):
            self.turn('stream', timeout=.2)
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(self.g['_keep_processes'])

    def test_failed_spawn_removes_fifo_and_log(self):
        with patch.object(subprocess, 'Popen', side_effect=OSError('启动失败')):
            with self.assertRaises(OSError):
                self.turn()
        self.assertEqual(list(Path(self.g['KEEP_DIR']).iterdir()), [])

    def test_unsupported_startup_falls_back_and_later_crash_keeps_diagnostic(self):
        self.assertFalse(self.turn(model='unsupported'))
        self.assertEqual(list(Path(self.g['KEEP_DIR']).iterdir()), [])
        self.assertTrue(self.turn())
        with self.assertRaisesRegex(self.g['BackendError'], 'EXIT_DIAGNOSTIC'):
            self.turn('exit', sid='conv-1')
        self.assertFalse(self.g['_keep_processes'])

    def test_callback_exception_closes_process(self):
        def fail(line):
            raise ValueError('callback failed')
        with self.assertRaisesRegex(ValueError, 'callback failed'):
            self.turn(callback=fail)
        self.assertEqual(list(Path(self.g['KEEP_DIR']).iterdir()), [])
        self.assertFalse(self.g['_keep_processes'])

    def test_stop_closes_active_session_and_reaps_owned_child(self):
        procs = []

        def stop(line):
            procs.extend(self.g['_keep_processes'].values())
            self.g['_on_stop'](signal.SIGTERM, None)

        with patch.object(os, '_exit', side_effect=SystemExit) as exit_process:
            with self.assertRaises(SystemExit):
                self.turn(callback=stop)
        exit_process.assert_called_once_with(143)
        self.assertTrue(procs)
        self.assertTrue(all(p.returncode is not None for p in procs))
        self.assertFalse(self.g['_keep_processes'])
        self.assertFalse(self.g['_active_keeps'])

    def test_stop_preserves_idle_sessions(self):
        self.assertTrue(self.turn())
        p = next(iter(self.g['_keep_processes'].values()))
        with patch.object(os, '_exit', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.g['_on_stop'](signal.SIGTERM, None)
        self.assertIsNone(p.poll())
        with self.assertRaisesRegex(self.g['BackendError'], self.g['STOP_MSG']):
            self.turn(sid='conv-1')
        self.assertEqual(len(self.g['_keep_processes']), 1)

    def test_reused_session_verifies_process_identity_before_killing(self):
        kid, pid = 'k_0123456789', 99999999
        for command, should_kill in [('/fake-agy --input-format stream-json', True), ('unrelated-process', False)]:
            self.g['write_json'](self.g['_keep_paths'](kid)['meta'], {'id': kid, 'pid': pid})
            with patch.dict(self.g, pid_alive=unittest.mock.Mock(side_effect=[True, False, False])), \
                 patch.object(subprocess, 'check_output', return_value=command), \
                 patch.object(os, 'killpg') as kill:
                self.assertTrue(self.g['keep_close'](kid))
            self.assertEqual(kill.call_count, 2 if should_kill else 0)
            if should_kill:
                self.assertEqual(kill.call_args_list, [unittest.mock.call(pid, signal.SIGTERM),
                                                      unittest.mock.call(pid, signal.SIGKILL)])


if __name__ == '__main__':
    unittest.main()

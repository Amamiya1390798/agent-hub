"""历史缓存与详情读取；仅使用临时目录，不启动后端或面板。"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ, {'HUB_HOME': self.tmp.name}):
            ns = runpy.run_path(str(ROOT / 'hub'))
        self.g = ns['load_calls'].__globals__

    def call(self, cid='c_abc', **extra):
        rec = dict(id=cid, status='ok', start=1, answer='旧答')
        rec.update(extra)
        path = Path(self.g['CALLS_DIR']) / (cid + '.json')
        self.g['write_json'](str(path), rec)
        return path

    def run_record(self, rid='20260101-000000', **extra):
        rec = dict(id=rid, status='done', start=1, goal='目标', tasks=[])
        rec.update(extra)
        path = Path(self.g['RUNS_DIR']) / rid / 'run.json'
        self.g['write_json'](str(path), rec)
        return path

    def test_unchanged_files_are_parsed_once_and_results_are_isolated(self):
        self.call(attempts=[{'backend': 'agy'}])
        self.run_record(tasks=[{'id': 't1', 'status': 'ok'}])
        with patch.dict(self.g, read_json=unittest.mock.Mock(wraps=self.g['read_json'])):
            calls = self.g['load_calls']()
            runs = self.g['load_runs']()
            calls[0]['attempts'][0]['backend'] = 'changed'
            runs[0]['tasks'][0]['status'] = 'changed'
            self.assertEqual(self.g['load_calls']()[0]['attempts'][0]['backend'], 'agy')
            self.assertEqual(self.g['load_runs']()[0]['tasks'][0]['status'], 'ok')
            self.assertEqual(self.g['read_json'].call_count, 2)

    def test_edits_replacements_additions_and_deletions(self):
        path = self.call()
        self.g['load_calls']()
        rec = json.loads(path.read_text())
        rec['answer'] = '新答'
        path.write_text(json.dumps(rec, ensure_ascii=False))  # 原地改写也要生效
        self.assertEqual(self.g['load_calls']()[0]['answer'], '新答')
        old = path.stat()
        replacement = path.with_suffix('.tmp')
        rec['answer'] = '再答'
        replacement.write_text(json.dumps(rec, ensure_ascii=False))
        os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
        os.replace(replacement, path)  # 时间和长度相同，inode 仍能区分
        self.assertEqual(path.stat().st_size, old.st_size)
        self.assertEqual(self.g['load_calls']()[0]['answer'], '再答')
        self.call('c_def', start=2)
        self.assertEqual([c['id'] for c in self.g['load_calls']()], ['c_def', 'c_abc'])
        path.unlink()
        self.assertEqual([c['id'] for c in self.g['load_calls']()], ['c_def'])

    def test_limit_uses_mtime_then_orders_by_start(self):
        for i, start in enumerate((30, 10, 20)):
            path = self.call('c_%x' % i, start=start)
            os.utime(path, (100 + i, 100 + i))
        self.assertEqual([c['start'] for c in self.g['load_calls'](2)], [20, 10])
        self.assertEqual(self.g['load_calls'](0), [])

    def test_missing_invalid_and_disappearing_files(self):
        self.assertEqual(self.g['load_calls'](), [])
        path = self.call()
        path.write_text('{invalid')
        self.assertEqual(self.g['load_calls'](), [])
        self.call()
        self.assertEqual(len(self.g['load_calls']()), 1)
        real_load = self.g['_load_call']

        def disappear(name, st):
            path.unlink()
            return real_load(name, st)

        # 缓存命中可以返回扫描时的快照；下一轮必须反映删除。
        with patch.dict(self.g, _load_call=disappear):
            self.g['load_calls']()
        self.assertEqual(self.g['load_calls'](), [])

    def test_running_records_recheck_pid_and_persist_failure(self):
        self.call(status='running', pid=1234)
        task = lambda tid, status: dict(id=tid, agent='gemini', title=tid, status=status)
        path = self.run_record(status='running', pid=1234,
                               tasks=[task('a', 'running'), task('b', 'pending')])
        with patch.dict(self.g, pid_alive=lambda p: True):
            self.g['load_calls']()
            self.g['load_runs']()
        with patch.dict(self.g, pid_alive=lambda p: False):
            self.assertEqual(self.g['ui_call']('c_abc')['status'], 'fail')
            run = self.g['ui_run']('20260101-000000')
        self.assertEqual(run['status'], 'failed')
        self.assertEqual([t['status'] for t in run['tasks']], ['fail', 'skipped'])
        self.assertEqual(json.loads(path.read_text())['status'], 'failed')
        self.assertTrue((path.parent / 'board.md').exists())
        call = self.g['read_json'](str(Path(self.g['CALLS_DIR']) / 'c_abc.json'))
        self.assertEqual(call['error'], self.g['DEAD_MSG'])

    def test_run_updates_without_parent_directory_change(self):
        path = self.run_record()
        self.g['load_runs']()
        before = Path(self.g['RUNS_DIR']).stat().st_mtime_ns
        self.run_record(summary='新的进度')
        self.assertEqual(Path(self.g['RUNS_DIR']).stat().st_mtime_ns, before)
        self.assertEqual(self.g['load_runs']()[0]['summary'], '新的进度')
        path.unlink()
        self.assertIsNone(self.g['ui_run']('20260101-000000'))

    def test_process_exit_does_not_overwrite_just_finished_records(self):
        call_path = self.call(status='running', pid=1234)
        run_path = self.run_record(status='running', pid=2345)
        with patch.dict(self.g, pid_alive=lambda p: True):
            self.g['load_calls']()
            self.g['load_runs']()

        def just_finished(pid):
            path, status = (call_path, 'ok') if pid == 1234 else (run_path, 'done')
            rec = json.loads(path.read_text())
            rec.update(status=status, answer='最终结果')
            self.g['write_json'](str(path), rec)
            return False

        with patch.dict(self.g, pid_alive=just_finished):
            self.assertEqual(self.g['load_calls']()[0]['status'], 'ok')
            self.assertEqual(self.g['load_runs']()[0]['status'], 'done')
        self.assertEqual(json.loads(call_path.read_text())['status'], 'ok')
        self.assertEqual(json.loads(run_path.read_text())['status'], 'done')

    def test_missing_running_record_is_not_recreated_by_failure_repair(self):
        path = self.call(status='running', pid=1234)
        with patch.dict(self.g, pid_alive=lambda p: True):
            self.g['load_calls']()

        def disappeared(pid):
            path.unlink()
            return False

        with patch.dict(self.g, pid_alive=disappeared):
            self.assertEqual(self.g['load_calls'](), [])
        self.assertFalse(path.exists())

    def test_detail_does_not_scan_runs_or_accumulate_fields(self):
        self.run_record()
        self.call(kind='synth', run='20260101-000000')
        with patch.dict(self.g, load_runs=unittest.mock.Mock(side_effect=AssertionError('扫描全部项目'))):
            for _ in range(3):
                self.assertEqual(len(self.g['ui_run']('20260101-000000')['synth_calls']), 1)
        self.assertNotIn('synth_calls', self.g['load_runs']()[0])

    def test_cache_is_bounded_and_safe_for_parallel_readers(self):
        path = str(self.call())
        cache = self.g['_RecordCache'](2)
        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(lambda _: cache.read(path), range(24)))
        records[0]['answer'] = 'changed'
        self.assertTrue(all(r['answer'] == '旧答' for r in records[1:]))
        cache.read(str(self.call('c_def')))
        cache.read(str(self.call('c_aaa')))
        self.assertEqual(len(cache.records), 2)
        self.assertNotIn(path, cache.records)


if __name__ == '__main__':
    unittest.main()

"""面板首屏、增量轮询和压缩的离线 HTTP 回归。"""
import gzip
import json
import os
import time
import unittest

import test_api


class PanelRefresh(unittest.TestCase):
    server = test_api.API

    @classmethod
    def setUpClass(cls):
        cls.server.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.server.tearDownClass()

    def write(self, relative, data):
        path = self.server.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)
        return path

    def state(self, version=''):
        status, data, _ = self.server.request('/api/state?compact=1&c=paneltest&v=' + version)
        self.assertEqual(status, 200)
        return json.loads(data)

    def test_compression(self):
        for path in ('/', '/api/state?compact=1'):
            with self.subTest(path=path):
                status, plain, headers = self.server.request(path)
                self.assertEqual(status, 200)
                self.assertNotIn('Content-Encoding', headers)
                for enc in ('gzip', '*;q=0.5', 'br, GZIP;q=0.8', 'gzip;q=0, *;q=1'):
                    _, body, headers = self.server.request(path, headers={'Accept-Encoding': enc})
                    self.assertEqual(int(headers['Content-Length']), len(body))
                    self.assertIn('Accept-Encoding', headers['Vary'])
                    if enc.startswith('gzip;q=0'):
                        self.assertNotIn('Content-Encoding', headers)
                        decoded = body
                    else:
                        self.assertEqual(headers['Content-Encoding'], 'gzip')
                        self.assertLess(len(body), len(plain))
                        decoded = gzip.decompress(body)
                    if path == '/':
                        self.assertEqual(decoded, plain)
                    else:
                        self.assertEqual(json.loads(decoded)['client'], {'remote': False})

    def test_history_and_live_changes(self):
        now = time.time()
        rid, cid = '20260101-123456', 'c_abc'
        answer, prompt = '完整回答' * 1000, '内部指令' * 1000
        call = dict(id=cid, kind='chat', start=now, agent='gemini', status='running', pid=os.getpid(),
                    prompt=prompt, display='原问题', answer=answer, dispatch={'goal': prompt, 'run': rid},
                    chat={'mode': 'manual', 'write': False, 'handoff': answer})
        run = dict(id=rid, start=now, status='done', goal=prompt, display='团队需求', summary=answer,
                   tasks=[{'id': 't1', 'status': 'ok', 'agent': 'gemini', 'title': '任务', 'answer': answer,
                           'progress': '进度详情'}])
        path = self.write('calls/' + cid + '.json', call)
        self.write('runs/' + rid + '/run.json', run)
        initial = self.state()
        call_row = next(c for c in initial['calls'] if c['id'] == cid)
        self.assertEqual(call_row['display'], '原问题')
        self.assertEqual(len(call_row['dispatch']['goal']), 80)
        for key in ('answer_preview', 'answer', 'prompt'):
            self.assertNotIn(key, call_row)
        self.assertNotIn('handoff', call_row['chat'])
        run_row = next(r for r in initial['runs'] if r['id'] == rid)
        self.assertEqual(run_row['display'], '团队需求')
        self.assertNotIn('summary', run_row)
        self.assertNotIn('progress', run_row['tasks'][0])

        for kind, rid_, key, value in (
            ('call', cid, 'answer', answer), ('run', rid, 'summary', answer)
        ):
            status, data, headers = self.server.request(f'/api/{kind}?id={rid_}', headers={'Accept-Encoding': 'gzip'})
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Encoding'], 'gzip')
            self.assertEqual(json.loads(gzip.decompress(data))[key], value)

        stable = self.state(initial['version'])
        # 跨过整分钟时，先接收时间更新，再检查空闲轮询。
        self.assertEqual(self.state(stable['version']), {'version': stable['version']})
        self.write('calls/' + cid + '.live', {'text': '正在写'})
        live = self.state(stable['version'])
        self.assertTrue(live['changes']['live'][cid])
        self.assertNotIn('calls', live['changes'])
        self.assertNotIn('runs', live['changes'])

        call.update(status='ok', end=now + 1)
        self.write('calls/' + cid + '.json', call)
        done = self.state(live['version'])
        self.assertEqual(done['changes']['calls']['upsert'][0]['status'], 'ok')
        self.assertNotEqual(done['changes']['calls']['upsert'][0]['rev'], call_row['rev'])
        self.assertNotIn(cid, done['changes']['live'])
        self.assertNotIn('runs', done['changes'])

        extra = dict(call, id='c_def', start=now + 2)
        self.write('calls/c_def.json', extra)
        path.unlink()
        recent = self.state(live['version'])  # 窗口可以跳过中间一次刷新
        self.assertEqual(recent['changes']['calls']['remove'], [cid])
        self.assertEqual(recent['changes']['calls']['upsert'][0]['id'], 'c_def')
        self.assertEqual(recent['changes']['calls']['order'][0], 'c_def')
        run['summary'] = '更新后的方案'
        self.write('runs/' + rid + '/run.json', run)
        changed = self.state(recent['version'])['changes']
        self.assertNotIn('calls', changed)
        self.assertNotEqual(changed['runs']['upsert'][0]['rev'], run_row['rev'])
        self.assertEqual(json.loads(self.server.request('/api/run?id=' + rid)[1])['summary'], run['summary'])
        self.assertIn('calls', self.state('expired'))  # 版本已过期或服务重启时恢复全量
        self.assertIn('answer_preview', json.loads(self.server.request('/api/state')[1])['calls'][0])


if __name__ == '__main__':
    unittest.main()

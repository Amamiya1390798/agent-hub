"""手机局域网访问的安全回归：配对、Cookie、Host、网段、限速、手机端禁止的操作。全部在临时实例上做。"""
import http.client
import json
import os
from pathlib import Path
import re
import runpy
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

if '--serve-test' in sys.argv:
    ns = runpy.run_path(str(ROOT / 'hub'))
    g = ns['serve_ui'].__globals__
    g['refresh_models'] = lambda: None
    g['refresh_quota'] = lambda: None
    g['_reexec_ui'] = lambda port, me: sys.exit(0)  # 测试里不真的重启
    ns['load_config']()
    ns['serve_ui'](int(sys.argv[-1]), str(ROOT / 'hub'))
    sys.exit()


def lan_ip():
    for probe in ('192.168.255.255', '10.255.255.255', '172.31.255.255'):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            ip = s.getsockname()[0]
            if re.match(r'^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)', ip):
                return ip
        except OSError:
            pass
        finally:
            s.close()
    return None


class Unit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        with patch.dict(os.environ, {'HUB_HOME': self.tmp.name}):
            ns = runpy.run_path(str(ROOT / 'hub'))
        self.g = ns['ask'].__globals__

    def test_ip_kind(self):
        k = self.g['ip_kind']
        for ip, want in [('127.0.0.1', 'local'), ('::1', 'local'), ('::ffff:127.0.0.1', 'local'),
                         ('192.168.1.5', 'private'), ('10.2.3.4', 'private'), ('172.20.0.1', 'private'),
                         ('172.32.0.1', 'other'), ('8.8.8.8', 'other'), ('100.64.0.1', 'other'),
                         ('169.254.1.1', 'other'), ('fe80::1', 'other'), ('', 'other'), ('x', 'other')]:
            self.assertEqual(k(ip), want, ip)

    def test_pair_file_cookie_and_reset(self):
        g = self.g
        self.assertIsNone(g['pair_load'](create=False))
        d = g['pair_load']()
        self.assertGreaterEqual(len(d['code']), 20)
        self.assertEqual(stat.S_IMODE(os.stat(g['PAIR_PATH']).st_mode), 0o600)
        good = 'hub_phone=' + g['pair_cookie_value'](d['code'])
        self.assertTrue(g['cookie_ok'](good))
        self.assertTrue(g['cookie_ok']('a=b; ' + good))
        self.assertTrue(g['cookie_ok']('item[0]=1; x="unclosed; hub_phone=bad; ' + good))  # 别的端口种的怪 Cookie
        for bad in ['', 'hub_phone=', 'hub_phone=' + 'a' * 64, 'hub_phone="x', 'other=' + good[10:]]:
            self.assertFalse(g['cookie_ok'](bad), bad)
        g['pair_reset']()
        self.assertFalse(g['cookie_ok'](good))  # 重置后旧手机失效
        self.assertEqual(stat.S_IMODE(os.stat(g['PAIR_PATH']).st_mode), 0o600)

    def test_gate_matrix(self):
        g = self.g
        d = g['pair_load']()
        ck = 'hub_phone=' + g['pair_cookie_value'](d['code'])
        gate = g['gate']
        P = 8765
        self.assertIsNone(gate('127.0.0.1', '127.0.0.1:8765', '127.0.0.1', P, '/', '', False))
        self.assertIsNone(gate('127.0.0.1', 'localhost:8765', '127.0.0.1', P, '/api/state', '', True))
        self.assertEqual(gate('127.0.0.1', 'evil.com:8765', '127.0.0.1', P, '/', '', False)[0], 403)  # DNS 重绑定
        self.assertEqual(gate('127.0.0.1', '192.168.1.2:8765', '127.0.0.1', P, '/', '', False)[0], 403)
        # 局域网关闭：一律拒绝，即使带着正确 Cookie
        self.assertEqual(gate('192.168.1.9', '192.168.1.2:8765', '192.168.1.2', P, '/', ck, False)[0], 403)
        # 局域网打开
        self.assertEqual(gate('192.168.1.9', '192.168.1.2:8765', '192.168.1.2', P, '/api/state', '', True)[0], 401)
        self.assertIsNone(gate('192.168.1.9', '192.168.1.2:8765', '192.168.1.2', P, '/pair', '', True))
        self.assertIsNone(gate('192.168.1.9', '192.168.1.2:8765', '192.168.1.2', P, '/api/state', ck, True))
        self.assertEqual(gate('192.168.1.9', 'evil.com', '192.168.1.2', P, '/api/state', ck, True)[0], 403)
        self.assertEqual(gate('192.168.1.9', '192.168.1.3:8765', '192.168.1.2', P, '/api/state', ck, True)[0], 403)
        self.assertEqual(gate('8.8.8.8', '192.168.1.2:8765', '192.168.1.2', P, '/api/state', ck, True)[0], 403)
        self.assertEqual(gate('8.8.8.8', '192.168.1.2:8765', '192.168.1.2', P, '/pair', '', True)[0], 403)
        # 局域网设备冒充本机 Host 也必须带 Cookie
        self.assertEqual(gate('192.168.1.9', '127.0.0.1:8765', '192.168.1.2', P, '/api/state', '', True)[0], 401)

    def test_limiter_attempt_is_atomic(self):
        import threading
        lim = self.g['PairLimiter'](per_ip=5, total=30, window=600)
        results = []
        barrier = threading.Barrier(40)

        def go():
            barrier.wait()
            results.append(lim.attempt('a', lambda: False))
        ts = [threading.Thread(target=go) for _ in range(40)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results.count('bad'), 5)  # 并发猛试也只记 5 次，不会把全局上限打满
        self.assertFalse(lim.blocked('b'))
        self.assertEqual(lim.attempt('b', lambda: True), 'ok')
        lim.clear()
        self.assertFalse(lim.blocked('a'))

    def test_limiter(self):
        lim = self.g['PairLimiter'](per_ip=5, total=8, window=600)
        for _ in range(5):
            self.assertFalse(lim.blocked('a', 100))
            lim.fail('a', 100)
        self.assertTrue(lim.blocked('a', 101))
        self.assertFalse(lim.blocked('b', 101))
        for _ in range(3):
            lim.fail('b', 101)
        self.assertTrue(lim.blocked('c', 102))  # 合计上限
        self.assertFalse(lim.blocked('a', 800))  # 10 分钟后解除


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        cls.home = Path(cls.tmp.name)
        (cls.home / 'config.json').write_text(json.dumps({'lan_access': True, 'bins': {'agy': '/nonexistent'}}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.log = (cls.home / 'server.log').open('w')
        cls.proc = subprocess.Popen([sys.executable, __file__, '--serve-test', str(cls.port)],
                                    env=dict(os.environ, HUB_HOME=cls.tmp.name), stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                if cls.req('127.0.0.1', '/')[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(.05)
        else:
            cls.tearDownClass()
            raise RuntimeError('临时面板启动失败')
        cls.token = re.search(r'const HUB_TOKEN = "([a-f0-9]+)"', cls.req('127.0.0.1', '/')[1].decode())[1]
        cls.ip = lan_ip()

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            cls.proc.wait(timeout=5)
        cls.log.close()
        cls.tmp.cleanup()

    @classmethod
    def req(cls, ip, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection(ip, cls.port, timeout=5)
        h = {'Host': host or '%s:%d' % (ip, cls.port)}
        h.update(headers or {})
        if body is not None:
            h.setdefault('X-Hub-Token', cls.token)
            h['Content-Type'] = 'application/json'
        conn.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        out = (r.status, r.read(), dict(r.getheaders()))
        conn.close()
        return out

    def test_1_local_unaffected_and_pair_info(self):
        st = json.loads(self.req('127.0.0.1', '/api/state')[1])
        self.assertEqual(st['client'], {'remote': False})
        self.assertEqual(st['lan'], {'enabled': True, 'listening': True})
        info = json.loads(self.req('127.0.0.1', '/api/pair')[1])
        self.assertTrue(info['code'])
        self.assertEqual(self.req('127.0.0.1', '/icon.png')[2]['Content-Type'], 'image/png')
        self.assertEqual(self.req('127.0.0.1', '/', host='evil.example:%d' % self.port)[0], 403)

    def test_2_remote_flow(self):
        if not self.ip:
            self.skipTest('本机没有局域网地址，跳过真实局域网连接测试（判定逻辑已由单元测试覆盖）')
        ip = self.ip
        code = json.loads(self.req('127.0.0.1', '/api/pair')[1])['code']
        # 未配对：全部拒绝，首页不含令牌
        status, page, _ = self.req(ip, '/')
        self.assertEqual(status, 401)
        self.assertNotIn(self.token.encode(), page)
        for path in ['/api/state', '/api/run?id=x', '/api/call?id=c_1', '/api/image?id=c_1', '/api/pair', '/icon.png']:
            self.assertEqual(self.req(ip, path)[0], 401, path)
        self.assertEqual(self.req(ip, '/api/submit', {'mode': 'ask', 'agent': 'gemini', 'text': 'x'})[0], 401)
        self.assertEqual(self.req(ip, '/api/state', host='evil.example:%d' % self.port)[0], 403)
        # 正确配对：拿到 HttpOnly Cookie
        status, _, headers = self.req(ip, '/pair?code=' + code)
        self.assertEqual(status, 303)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        cookie = {'Cookie': headers['Set-Cookie'].split(';')[0]}
        st = json.loads(self.req(ip, '/api/state', headers=cookie)[1])
        self.assertEqual(st['client'], {'remote': True})
        self.assertIn(self.token.encode(), self.req(ip, '/', headers=cookie)[1])
        # 手机上禁止的事
        self.assertEqual(self.req(ip, '/api/pair', headers=cookie)[0], 403)
        for path, body in [('/api/config', {'timeout': 600}), ('/api/lan', {'enable': False}), ('/api/pair/reset', {}),
                           ('/api/login', {'agent': 'gemini'}), ('/api/health', {}), ('/api/open', {'type': 'call', 'id': 'c_1'})]:
            self.assertEqual(self.req(ip, path, body, headers=cookie)[0], 403, path)
        self.assertEqual(self.req(ip, '/api/submit', {'mode': 'ask', 'agent': 'gemini', 'text': 'x', 'write': True},
                                  headers=cookie)[0], 400)  # 改文件要二次确认
        self.assertEqual(self.req(ip, '/api/submit', {'mode': 'ask', 'agent': 'gemini', 'text': 'x'},
                                  headers=dict(cookie, **{'X-Hub-Token': 'bad'}))[0], 403)
        # 重置配对码：旧手机失效
        self.assertEqual(self.req('127.0.0.1', '/api/pair/reset', {})[0], 200)
        self.assertEqual(self.req(ip, '/api/state', headers=cookie)[0], 401)
        # 输错限速
        codes = [self.req(ip, '/pair?code=wrong%d' % i)[0] for i in range(7)]
        self.assertEqual(codes[:5], [403] * 5)
        self.assertEqual(codes[5:], [429, 429])
        new = json.loads(self.req('127.0.0.1', '/api/pair')[1])['code']
        self.assertEqual(self.req(ip, '/pair?code=' + new)[0], 429)  # 锁定期间正确码也不收
        self.assertEqual(self.req(ip, '/pair')[0], 200)  # 只打开配对页不算试错
        # 电脑上重置配对码会解除锁定
        self.assertEqual(self.req('127.0.0.1', '/api/pair/reset', {})[0], 200)
        new = json.loads(self.req('127.0.0.1', '/api/pair')[1])['code']
        status, _, headers = self.req(ip, '/pair?code=' + new)
        self.assertEqual(status, 303)
        cookie = {'Cookie': headers['Set-Cookie'].split(';')[0]}
        # 手机上画图也要确认；不能指定电脑上的目录，也不回显路径
        self.assertEqual(self.req(ip, '/api/submit', {'mode': 'image', 'text': 'x'}, headers=cookie)[0], 400)
        status, data, _ = self.req(ip, '/api/submit', {'mode': 'ask', 'agent': 'gemini', 'text': 'x', 'cwd': '/no/such/dir'}, headers=cookie)
        self.assertEqual(status, 200, data)

    def test_3_toggle_off_restarts(self):
        status, data, _ = self.req('127.0.0.1', '/api/lan', {'enable': False})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)['restarting'])
        self.assertEqual(json.loads((self.home / 'config.json').read_text())['lan_access'], False)
        self.proc.wait(timeout=5)  # 测试里用退出代替重新启动


if __name__ == '__main__':
    unittest.main()

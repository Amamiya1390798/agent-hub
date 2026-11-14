"""临时面板的 HTTP 契约检查；替换额度/模型探测，绝不访问账号。"""
import http.client
import json
import os
from pathlib import Path
import re
import runpy
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

if '--serve-test' in sys.argv:
    ns = runpy.run_path(str(ROOT / 'hub'))
    g = ns['serve_ui'].__globals__
    g['HOME'] = os.environ['HUB_HOME']
    g['refresh_models'] = lambda: None
    g['refresh_quota'] = lambda: None
    ns['load_config']()
    ns['serve_ui'](int(sys.argv[-1]), str(ROOT / 'hub'))
    sys.exit()


class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        cls.home = Path(cls.tmp.name)
        fake = cls.home / 'fake-agy'
        fake.write_text('#!%s\nimport json,sys,time,os\n'
                        'if any("__STOP_TEST__" in a for a in sys.argv):\n'
                        ' open(os.path.join(os.environ["HUB_HOME"],"fake.pid"),"w").write(str(os.getpid()))\n'
                        ' time.sleep(30)\n'
                        'print(json.dumps({"event":"result","result":{"status":"SUCCESS","response":"测试回答"}}))\n' % sys.executable)
        fake.chmod(0o755)
        (cls.home/'config.json').write_text(json.dumps({'bins': {'agy': str(fake)}, 'planner':'gemini', 'auto_title':'',
            'agents': {'ds': ['agy:fake-ds'], 'claude': ['agy:fake-claude']}}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); cls.port = sock.getsockname()[1]
        cls.log = (cls.home/'server.log').open('w')
        cls.proc = subprocess.Popen([sys.executable, __file__, '--serve-test', str(cls.port)],
            env=dict(os.environ,HUB_HOME=cls.tmp.name), stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                status, data, _ = cls.request('/')
                if status == 200:
                    cls.token = re.search(r'const HUB_TOKEN = "([a-f0-9]+)"', data.decode())[1]
                    break
            except OSError:
                pass
            time.sleep(.05)
        else:
            cls.tearDownClass()
            raise RuntimeError('临时面板启动失败')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.log.close()
        cls.tmp.cleanup()

    @classmethod
    def request(cls, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection('127.0.0.1',cls.port,timeout=5)
        h = dict(headers or {})
        if body is not None or raw is not None:
            h.setdefault('X-Hub-Token',getattr(cls,'token',''))
            h.setdefault('Content-Type','application/json')
        payload = raw if raw is not None else json.dumps(body) if body is not None else None
        conn.request('POST' if payload is not None else 'GET',path,payload,h)
        r = conn.getresponse(); result = (r.status,r.read(),dict(r.getheaders())); conn.close()
        return result

    def test_served_ui_script(self):
        status, data, _ = self.request('/')
        self.assertEqual(status, 200)
        html = data.decode()
        self.assertNotIn('__HUB_TOKEN__', html)
        self.assertIn('task-grid', html)
        self.assertIn('① 跟对接人说', html)
        script = re.search(r'<script>([\s\S]*)</script>', html)[1]
        result = subprocess.run(['node', '--check'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_state_host_token_clients(self):
        self.assertEqual(self.request('/api/state',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/config',{},headers={'X-Hub-Token':''})[0],403)
        self.assertEqual(self.request('/api/config',{},headers={'Host':'evil.example'})[0],403)
        state = json.loads(self.request('/api/state?c=abc123')[1])
        self.assertEqual(len(state['agents']),4)
        self.request('/api/state?c=def456')
        self.assertGreaterEqual(json.loads(self.request('/api/clients')[1])['n'],2)
        before = json.loads(self.request('/api/clients')[1])['n']
        self.assertEqual(self.request('/api/bye?c=abc123&unused=1',{})[0],200)
        self.assertEqual(json.loads(self.request('/api/clients')[1])['n'],before-1)
        self.assertEqual(self.request('/api/byeevil?c=def456',{},headers={'X-Hub-Token':''})[0],403)

    def test_invalid_submit(self):
        base = {'mode':'ask','agent':'gemini','text':'test'}
        for extra in [{'text':''},{'text':[]},{'mode':'bad'},{'agent':[]},{'agent':'bad'},
                      {'cwd':'/path-does-not-exist'},{'cwd':[]},{'write':'false'},
                      {'context':'x'},{'context':{'type':'call','id':[]}},
                      {'context':{'type':'call','id':'c_ffff'}}]:
            with self.subTest(extra=extra):
                self.assertEqual(self.request('/api/submit',dict(base,**extra))[0],400)
        for raw in ['[]','{','null']:
            self.assertEqual(self.request('/api/submit',raw=raw)[0],400)
        self.assertEqual(self.request('/api/submit',raw='',headers={'Content-Length':'-1'})[0],400)

    def test_config_validation_and_preservation(self):
        for b in [{'timeout':None},{'timeout':59},{'timeout':7201},{'max_parallel':0},
                  {'max_parallel':1.5},{'max_parallel':True},{'planner':'missing'},
                  {'codex_effort':'invalid'},{'chain':[]},
                  {'effort':{'agent':'claude','level':'ultra'}},{'effort':{'agent':'nobody','level':'low'}},{'effort':'high'},
                  {'chain':{'agent':'gpt','index':99,'spec':'codex'}},
                  {'chain':{'agent':'gpt','index':.5,'spec':'codex'}},
                  {'chain':{'agent':'gpt','index':0,'spec':'agy:claude-forbidden'}}]:
            with self.subTest(body=b):
                self.assertEqual(self.request('/api/config',b)[0],400)
        self.assertEqual(self.request('/api/config',{'timeout':120,'max_parallel':2,
            'chain':{'agent':'gpt','index':0,'spec':'dsh'}})[0],200)
        cfg = json.loads((self.home/'config.json').read_text())
        self.assertEqual(cfg['timeout'],120)
        self.assertEqual(cfg['agents']['gpt'][0],'dsh')
        self.assertEqual(cfg['planner'],'gemini')
        self.assertEqual(self.request('/api/config',{'effort':{'agent':'claude','level':'xhigh'}})[0],400)  # 现在是 Gemini 假模型，没有这一档
        self.assertEqual(self.request('/api/config',{'chain':{'agent':'claude','index':0,'spec':'claude:opus'}})[0],200)
        self.assertEqual(self.request('/api/config',{'effort':{'agent':'claude','level':'xhigh'}})[0],200)
        self.assertEqual(json.loads((self.home/'config.json').read_text())['effort'],{'claude':'xhigh'})
        self.assertIn('agy',cfg['bins'])

    def test_image_allowlist_and_ids(self):
        calls = self.home/'calls'; calls.mkdir(exist_ok=True)
        for ext, status in [('png',200),('jpg',200),('webp',200),('gif',200),('svg',404),('html',404),('txt',404)]:
            image = self.home/('image.'+ext); image.write_text('<script>test</script>')
            (calls/'c_abcd.json').write_text(json.dumps({'id':'c_abcd','status':'ok','image':str(image)}))
            code, _, headers = self.request('/api/image?id=c_abcd')
            self.assertEqual(code,status)
            self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(self.request('/api/call?id=../../config')[0],404)
        self.assertEqual(self.request('/api/run?id=invalid')[0],404)

    def test_submit_fake_backend(self):
        status, data, _ = self.request('/api/submit',{'mode':'ask','agent':'gemini','text':'离线测试'})
        self.assertEqual(status,200)
        submission = json.loads(data)['submission_id']
        for _ in range(100):
            records = [json.loads(p.read_text()) for p in (self.home/'calls').glob('*.json')]
            matching = [r for r in records if r.get('display')=='离线测试']
            if matching and matching[0]['status'] != 'running':
                break
            time.sleep(.05)
        self.assertEqual(matching[0]['answer'],'测试回答')
        self.assertEqual(matching[0]['status'],'ok')
        self.assertEqual(matching[0]['submission_id'],submission)
        state = json.loads(self.request('/api/state')[1])
        self.assertEqual(next(c for c in state['calls'] if c['id']==matching[0]['id'])['submission_id'],submission)

    def test_submit_council_read_only(self):
        for b in [{'council_agents':[]},{'council_agents':['gemini']},{'council_agents':['gemini','gemini']},{'council_agents':['nobody']},{'council_agents':'gemini'}]:
            self.assertEqual(self.request('/api/config',b)[0],400)
        self.assertEqual(self.request('/api/config',{'council_agents':['gemini','ds']})[0],200)
        self.assertEqual(self.request('/api/submit',{'mode':'council','text':'会审','write':True})[0],400)
        for extra in [{'agents':['nobody']},{'agents':'gemini'},{'agents':[]},{'synthesizer':'nobody'}]:
            self.assertEqual(self.request('/api/submit',dict({'mode':'council','text':'会审'},**extra))[0],400)
        status, data, _ = self.request('/api/submit',{'mode':'council','text':'离线会审'})
        self.assertEqual(status,200)
        for _ in range(200):
            runs = [json.loads(p.read_text()) for p in (self.home/'runs').glob('*/run.json')]
            runs = [r for r in runs if r.get('display')=='离线会审']
            if runs and runs[0]['status'] not in ('running','synthesizing'):
                break
            time.sleep(.05)
        run = runs[0]
        self.assertEqual((run['mode'],run['status'],run['write']),('council','done',False))
        self.assertEqual([t['agent'] for t in run['tasks']],['gemini','ds'])
        detail = json.loads(self.request('/api/run?id='+run['id'])[1])
        self.assertTrue(all(t['answer']=='测试回答' for t in detail['tasks']))
        self.assertEqual(detail['synth_calls'][0]['status'],'ok')
        state = json.loads(self.request('/api/state')[1])
        self.assertEqual(state['config']['council_agents'],['gemini','ds'])
        self.assertEqual(next(r for r in state['runs'] if r['id']==run['id'])['mode'],'council')

    def test_submit_chat_contact(self):
        self.assertEqual(self.request('/api/submit',{'mode':'chat','agent':'nobody','text':'x'})[0],400)
        self.assertEqual(self.request('/api/submit',{'mode':'chat','agent':'gemini','text':'对接测试'})[0],200)
        for _ in range(100):
            calls = [json.loads(p.read_text()) for p in (self.home/'calls').glob('*.json')]
            calls = [c for c in calls if c.get('display')=='对接测试']
            if calls and calls[0]['status'] != 'running':
                break
            time.sleep(.05)
        c = calls[0]
        self.assertEqual((c['kind'],c['agent'],c['answer'],c['chat']['mode']),('chat','gemini','测试回答','manual'))

    def test_stop_real_subprocess(self):
        self.assertEqual(self.request('/api/submit',{'mode':'ask','agent':'gemini','text':'__STOP_TEST__'})[0],200)
        for _ in range(100):
            matches = [json.loads(p.read_text()) for p in (self.home/'calls').glob('*.json')]
            matches = [r for r in matches if r.get('display')=='__STOP_TEST__']
            if matches and (self.home/'fake.pid').exists():
                break
            time.sleep(.05)
        record = matches[0]
        self.assertEqual(self.request('/api/stop',{'type':'call','id':record['id']})[0],200)
        stopped = json.loads(self.request('/api/call?id='+record['id'])[1])
        self.assertEqual(stopped['error'],'已手动停止')
        pid = int((self.home/'fake.pid').read_text())
        state = subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True).stdout.strip()
        self.assertTrue(not state or state.startswith('Z'), state)


    def test_side_question(self):
        for bad in ({'mode':'side','agent':'gemini','text':'x','write':True},
                    {'mode':'side','agent':'gemini','text':'x','spec':'agy:not-real'},
                    {'mode':'side','agent':'ds','text':'x','effort':'xhigh'},
                    {'mode':'side','agent':'gemini','text':'x','web':'yes'}):
            self.assertEqual(self.request('/api/submit',bad)[0],400,bad)
        self.assertEqual(self.request('/api/submit',{'mode':'side','agent':'gemini','text':'旁问离线测试','web':True})[0],200)
        for _ in range(100):
            recs = [json.loads(p.read_text()) for p in (self.home/'calls').glob('*.json')]
            m = [r for r in recs if r.get('display')=='旁问离线测试']
            if m and m[0]['status'] != 'running':
                break
            time.sleep(.05)
        self.assertEqual(m[0]['kind'],'side')
        self.assertEqual(m[0]['side']['web'],True)
        self.assertFalse(m[0]['write'])
        self.assertEqual(m[0]['answer'],'测试回答')


    def test_fork_and_context_scope(self):
        def wait(text):
            for _ in range(100):
                recs = [json.loads(p.read_text()) for p in (self.home/'calls').glob('*.json')]
                m = [r for r in recs if r.get('display')==text]
                if m and m[0]['status'] != 'running':
                    return m[0]
                time.sleep(.05)
        self.assertEqual(self.request('/api/submit',{'mode':'ask','agent':'gemini','text':'分叉的起点'})[0],200)
        root = wait('分叉的起点')
        self.assertEqual(self.request('/api/submit',{'mode':'ask','agent':'gemini','text':'第二轮','context':{'type':'call','id':root['id']}})[0],200)
        second = wait('第二轮')
        for bad in ({'mode':'ask','agent':'gemini','text':'x','context':{'type':'call','id':root['id']},'fork':'yes'},
                    {'mode':'side','agent':'gemini','text':'x','context':{'type':'call','id':root['id']},'fork':True},
                    {'mode':'ask','agent':'gemini','text':'x','context':{'type':'call','id':root['id']},'context_scope':'half'}):
            self.assertEqual(self.request('/api/submit',bad)[0],400,bad)
        self.assertEqual(self.request('/api/submit',{'mode':'ask','agent':'gemini','text':'分出去的','context':{'type':'call','id':root['id']},'fork':True})[0],200)
        fork = wait('分出去的')
        self.assertTrue(fork['fork'])
        self.assertEqual(fork['follows'],{'type':'call','id':root['id']})
        self.assertIn('分叉的起点', fork['prompt'])
        self.assertNotIn('fork', second)
        self.assertEqual(self.request('/api/submit',{'mode':'side','agent':'gemini','text':'只带一条','context':{'type':'call','id':second['id']},'context_scope':'one'})[0],200)
        one = wait('只带一条')
        self.assertIn('第二轮', one['prompt'])
        self.assertNotIn('分叉的起点', one['prompt'])
        self.assertEqual(self.request('/api/submit',{'mode':'side','agent':'gemini','text':'带完整','context':{'type':'call','id':second['id']},'context_scope':'full'})[0],200)
        self.assertIn('分叉的起点', wait('带完整')['prompt'])


    def test_upload_and_images(self):
        import base64
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
        st, data, _ = self.request('/api/upload',{'data':'data:image/png;base64,'+base64.b64encode(png).decode()})
        self.assertEqual(st,200)
        name = json.loads(data)['id']
        st, data, h = self.request('/api/attachment?id='+name)
        self.assertEqual((st, data, h['Content-Type']), (200, png, 'image/png'))
        self.assertEqual(self.request('/api/attachment?id=../config.json')[0],404)
        for bad in ({'data':'not base64!!'},{'data':base64.b64encode(b'<svg/>').decode()}):
            self.assertEqual(self.request('/api/upload',bad)[0],400,bad)
        for bad in ({'mode':'ask','agent':'gemini','text':'x','images':['../x.png']},
                    {'mode':'ask','agent':'gemini','text':'x','images':[name]*7},
                    {'mode':'image','text':'x','images':[name]}):
            self.assertEqual(self.request('/api/submit',bad)[0],400,bad)
        self.assertEqual(self.request('/api/submit',{'mode':'side','agent':'gemini','text':'看图离线测试','images':[name]})[0],200)
        for _ in range(100):
            recs = [json.loads(p.read_text()) for p in (self.home/'calls').glob('*.json')]
            m = [r for r in recs if r.get('display')=='看图离线测试']
            if m and m[0]['status'] != 'running':
                break
            time.sleep(.05)
        self.assertEqual(m[0]['images'],[name])
        self.assertIn(name, m[0]['prompt'])
        self.assertIn('read_image', m[0]['prompt'])


    def test_rename(self):
        self.assertEqual(self.request('/api/rename',{'key':'call:c_abc','name':'  我的项目  '})[0],200)
        st = json.loads(self.request('/api/state?c=t')[1])
        self.assertEqual(st['names'].get('call:c_abc'),'我的项目')
        for bad in ({'key':'../x','name':'a'},{'key':'call:c_abc','name':'x'*61},{'key':'call:c_abc'}):
            self.assertEqual(self.request('/api/rename',bad)[0],400,bad)
        self.assertEqual(self.request('/api/config',{'auto_title':'nobody'})[0],400)
        self.assertEqual(self.request('/api/config',{'auto_title':''})[0],200)


    def test_handoff_api(self):
        for bad in ({'from':{'type':'call','id':'c_nope'},'to':{'type':'call','id':'c_nope2'}},{'from':'x','to':'y'},{}):
            self.assertEqual(self.request('/api/handoff',bad)[0],400,bad)


    def test_archive(self):
        self.assertEqual(self.request('/api/archive',{'keys':['run:20261114-010101','call:c_abc'],'on':True})[0],200)
        st = json.loads(self.request('/api/state?c=t')[1])
        self.assertEqual(st['archived'],['run:20261114-010101','call:c_abc'])
        self.assertEqual(self.request('/api/archive',{'keys':['call:c_abc'],'on':False})[0],200)
        st = json.loads(self.request('/api/state?c=t')[1])
        self.assertEqual(st['archived'],['run:20261114-010101'])
        for bad in ({'keys':['run:../x'],'on':True},{'keys':[],'on':True},{'keys':['call:a'],'on':'yes'},{'keys':'call:a','on':True}):
            self.assertEqual(self.request('/api/archive',bad)[0],400, bad)
        self.request('/api/archive',{'keys':['run:20261114-010101'],'on':False})


if __name__ == '__main__':
    unittest.main()

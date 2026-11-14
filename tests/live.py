"""显式运行的真后端检查，不属于 smoke。"""
import json
import os
from pathlib import Path
import runpy
import tempfile
import time

root = Path(__file__).resolve().parents[1]
results = {}
with tempfile.TemporaryDirectory(prefix='live-', dir=root) as home:
    os.environ['HUB_HOME'] = home
    ns = runpy.run_path(str(root/'hub'))
    g = ns['ask'].__globals__
    cfg = ns['load_config']()
    skip = set(filter(None, os.environ.get('HUB_LIVE_SKIP', '').split(',')))  # 例如 HUB_LIVE_SKIP=codex：GPT 没额度时跳过
    for kind, model in [('agy','gemini-3.8-flash-high'),('codex',''),('dsh','')]:
        if kind in skip:
            continue
        g['_ctx'].session = None
        start = time.monotonic()
        try:
            answer = ns['BACKENDS'][kind](cfg,model,'不要调用工具，不要读文件，只回复：收到',home,False,60)
            assert '收到' in answer, answer
            results[kind] = {'ok':True,'session':getattr(g['_ctx'],'session',None)}
        except Exception as e:
            results[kind] = {'ok':False,'error':str(e)[:600]}
        results[kind]['secs'] = round(time.monotonic()-start,1)
        print(kind, json.dumps(results[kind],ensure_ascii=False),flush=True)
    # 续聊工作目录需要长期存在，使用仓库根目录；会话自身仍由官方客户端管理。
    if results.get('codex',{}).get('session'):
        results['codex']['session']['resume'] = results['codex']['session']['resume'].replace(home,str(root))
(root/'tests'/'live-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
raise SystemExit(0 if all(r['ok'] for r in results.values()) else 1)

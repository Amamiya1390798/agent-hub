"""旁问：指定模型排第一、单独档位只用在它身上、联网时 GPT/Claude 打开搜索开关。全部离线。"""
import os, runpy, tempfile, unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))


class SideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": self.tmp}):
            ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__
        self.cfg = self.g["load_config"]()

    def test_spec_effort_web_and_fallback(self):
        g = self.g
        seen = []

        def fake(kind):
            def run(cfg, model, prompt, cwd, write, timeout):
                seen.append((kind, model, cfg.get("_effort"), cfg.get("_web"), prompt))
                if kind == "codex":
                    raise g["BackendError"]("模拟失败")
                return "ok"
            return run
        cfg = dict(self.cfg, effort={"gpt": "low"})
        cfg["agents"] = dict(cfg["agents"], gpt=["codex", "claude:opus"])
        with patch.dict(g["BACKENDS"], {"codex": fake("codex"), "claude": fake("claude")}), \
                patch.dict(g, {"codex_model_efforts": lambda m: [("low", ""), ("ultra", "")]}):
            text, used = g["ask"](cfg, "gpt", "问题", quiet=True, spec="codex:gpt-6-astra", effort="ultra", web=True,
                                  meta={"kind": "side"})
        self.assertEqual(used, "claude:opus")
        self.assertEqual(seen[0][:4], ("codex", "gpt-6-astra", "ultra", True))   # 指定模型排第一，用单独选的档位
        self.assertIn("联网", seen[0][4])
        self.assertEqual(seen[1][0], "codex")                                    # 再试成员原来的首选
        self.assertEqual(seen[1][2], "low")                                      # 它用成员自己的档位
        self.assertEqual(seen[2][:2], ("claude", "opus"))
        self.assertEqual(seen[2][2], "low")                                      # 备用的 Claude 也有 low，照成员设置传
        recs = [f for f in os.listdir(os.path.join(self.tmp, "calls")) if f.endswith(".json")]
        rec = g["read_json"](os.path.join(self.tmp, "calls", recs[0]))
        self.assertEqual(rec["kind"], "side")
        self.assertEqual(rec["side"], {"web": True, "effort": "ultra", "spec": "codex:gpt-6-astra"})

    def _cmd(self, backend, **extra):
        seen = {}

        def fake_run(cmd, *a, **kw):
            seen["cmd"] = cmd
            if backend == "backend_codex":
                with open(cmd[cmd.index("-o") + 1], "w") as f:
                    f.write("收到")
            return 0, "收到", ""
        with patch.dict(self.g, {"find_bin": lambda *a: "/fake/cli", "_run": fake_run}):
            self.g[backend](dict(self.cfg, **extra), "", "hi", self.tmp, False, 1)
        return seen["cmd"]

    def test_web_flags(self):
        self.assertIn('web_search="live"', self._cmd("backend_codex", _web=True))
        self.assertNotIn('web_search="live"', self._cmd("backend_codex"))
        c = self._cmd("backend_claude", _web=True)
        self.assertIn("--allowedTools", c)
        self.assertIn("WebSearch", c)
        self.assertNotIn("--allowedTools", self._cmd("backend_claude"))


if __name__ == "__main__":
    unittest.main()

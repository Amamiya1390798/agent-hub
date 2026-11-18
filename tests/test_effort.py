"""每位成员的思考等级：GPT 传 model_reasoning_effort，Claude 传 --effort，旧的 codex_effort 兼容。全部离线。"""
import os, runpy, tempfile, unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))


class EffortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": self.tmp}):
            ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__
        self.cfg = self.g["load_config"]()

    def test_agent_effort_precedence(self):
        g = self.g
        ae = g["agent_effort"]
        luna = [("low", ""), ("max", "")]
        with patch.dict(g, {"codex_model_efforts": lambda m: luna if m == "gpt-6-luna" else [(e, "") for e in ("low", "medium", "ultra")]}):
            cfg = dict(self.cfg, codex_effort="medium", effort={})
            self.assertEqual(ae(cfg, "gpt", "codex"), "medium")             # 没在卡片上设过：沿用旧设置
            self.assertEqual(ae(cfg, "claude", "claude:opus"), "")          # 旧设置只管 GPT
            cfg["effort"] = {"gpt": "", "claude": "xhigh"}
            self.assertEqual(ae(cfg, "gpt", "codex"), "")                   # 卡片上选了默认就以卡片为准
            self.assertEqual(ae(cfg, "claude", "claude:opus"), "xhigh")
            cfg["effort"] = {"gpt": "ultra"}
            self.assertEqual(ae(cfg, "gpt", "codex"), "ultra")              # 模型自己有的档位照传
            self.assertEqual(ae(cfg, "gpt", "codex:gpt-6-luna"), "")        # 换成没有这一档的模型就不传
            self.assertEqual(ae(cfg, "gpt", "claude:opus"), "")             # Claude 没有 ultra
            self.assertEqual(ae(cfg, "gpt", "agy:gemini-4-carbon-high"), "")

    def test_codex_levels_from_cache(self):
        g = self.g
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, ".codex"))
        with open(os.path.join(home, ".codex", "models_cache.json"), "w") as f:
            f.write('{"models":[{"slug":"m1","supported_reasoning_levels":[{"effort":"low","description":"a"},{"effort":"ultra","description":"b"},{"effort":"bad\\"x"}]}]}')
        with patch.dict(g, {"HOME": home}):
            self.assertEqual(g["codex_model_efforts"]("m1"), [("low", "a"), ("ultra", "b")])
            self.assertEqual([e for e, _ in g["codex_model_efforts"]("unknown")], ["low", "medium", "high", "xhigh", "max"])

    def _cmd(self, backend, effort):
        seen = {}

        def fake_run(cmd, *a, **kw):
            seen["cmd"] = cmd
            if backend == "backend_codex":
                out = cmd[cmd.index("-o") + 1]
                with open(out, "w") as f:
                    f.write("收到")
            return 0, "收到", ""
        with patch.dict(self.g, {"find_bin": lambda *a: "/fake/cli", "_run": fake_run}):
            self.g[backend](dict(self.cfg, _effort=effort), "", "hi", self.tmp, False, 1)
        return seen["cmd"]

    def test_codex_and_claude_flags(self):
        self.assertIn('model_reasoning_effort="high"', self._cmd("backend_codex", "high"))
        self.assertFalse(any("model_reasoning_effort" in x for x in self._cmd("backend_codex", "")), "没设档位：不传档位")
        c = self._cmd("backend_claude", "max")
        self.assertEqual(c[c.index("--effort") + 1], "max")
        self.assertNotIn("--effort", self._cmd("backend_claude", ""))

    def test_ask_passes_member_effort(self):
        g = self.g
        seen = {}

        def fake_backend(cfg, model, prompt, cwd, write, timeout):
            seen["effort"] = cfg.get("_effort")
            return "ok"
        cfg = dict(self.cfg, effort={"claude": "low"})  # Claude 的 low 是它自己有的档位
        cfg["agents"] = dict(cfg["agents"], claude=["claude:opus"])
        with patch.dict(g["BACKENDS"], {"claude": fake_backend}):
            g["ask"](cfg, "claude", "hi", quiet=True)
        self.assertEqual(seen["effort"], "low")


if __name__ == "__main__":
    unittest.main()

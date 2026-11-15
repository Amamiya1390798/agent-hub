"""成员开关和模型开关：停用的不参与排工、会审、对接，也不当备用。全部离线。"""
import os, runpy, tempfile, unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))


class ToggleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": self.tmp}):
            ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__
        self.cfg = self.g["load_config"]()

    def test_active_cfg(self):
        g = self.g
        self.assertIs(g["active_cfg"](self.cfg), self.cfg, "没停用时原样返回")
        cfg = dict(self.cfg, disabled_agents=["claude", "gemini"], planner="gemini", synthesizer="gemini",
                   default_worker="gemini", auto_title="ds", council_agents=["gemini", "gpt", "ds"])
        cfg["agents"] = dict(cfg["agents"], gpt=["codex", "agy:x"], ds=["dsh"])
        a = g["active_cfg"](cfg)
        self.assertEqual(set(a["agents"]), {"gpt", "ds"})
        self.assertEqual((a["planner"], a["synthesizer"], a["default_worker"]), ("gpt", "gpt", "gpt"), "排工/汇总的人停用了就换一位")
        self.assertEqual(a["council_agents"], ["gpt", "ds"])
        self.assertEqual(a["auto_title"], "ds")
        cfg["disabled_models"] = ["codex", "dsh"]
        a = g["active_cfg"](cfg)
        self.assertEqual(a["agents"], {"gpt": ["agy:x"]}, "停用的模型从备用链里去掉；全被去掉的成员也不参与")
        self.assertEqual(a["auto_title"], "", "起名的人用不了就不起名")
        self.assertIn("ds", a["_disabled_agents"])

    def test_ask_and_roster(self):
        g = self.g
        cfg = g["active_cfg"](dict(self.cfg, disabled_agents=["claude"]))
        with self.assertRaises(g["BackendError"]) as e:
            g["ask"](cfg, "claude", "hi", quiet=True)
        self.assertIn("已停用", str(e.exception))
        self.assertNotIn("claude", g["team_note"](cfg, "gemini"))
        seen = {}

        def fake_ask(c, agent, prompt, **kw):
            seen["p"] = prompt
            return '{"summary":"s","tasks":[{"id":"t1","agent":"claude","title":"x","prompt":"p"}]}', "x"
        with patch.dict(g, {"ask": fake_ask}):
            plan = g["make_plan"](cfg, "目标", self.tmp, False, "gemini", 3)
        self.assertNotIn("- claude：", seen["p"], "排工名单里没有停用的成员")
        self.assertNotEqual(plan["tasks"][0]["agent"], "claude", "派给停用成员的活改派给别人")

    def test_contact_skips_disabled(self):
        g = self.g
        cfg = g["active_cfg"](dict(self.cfg, disabled_agents=["gpt", "gemini"]))
        with patch.dict(g, {"quota_known_ok": lambda n, now=None: (True, "ok"), "quota_stale": lambda now=None: False}):
            name, _, _ = g["choose_contact"](cfg, "帮我定个方案", None)
        self.assertNotIn(name, ("gpt", "gemini"))


if __name__ == "__main__":
    unittest.main()

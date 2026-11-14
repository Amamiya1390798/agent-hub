"""高压模式：ds 拆任务并汇总，拆任务前注入用户写的提示词。全部离线，不调用真模型。"""
import json, os, runpy, sys, tempfile, unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))


class PressureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HUB_HOME"] = self.tmp
        ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__

    def test_inject_goes_before_plan_prompt(self):
        g = self.g
        seen = {}

        def fake_ask(cfg, agent, prompt, **kw):
            seen["agent"], seen["prompt"] = agent, prompt
            return json.dumps({"summary": "s", "tasks": [{"id": "t1", "agent": "gemini", "title": "x", "prompt": "p"}]}), "dsh"
        g["ask"] = fake_ask
        cfg = g["load_config"]()
        g["make_plan"](cfg, "目标A", self.tmp, False, "ds", 3, inject="我的特别要求XYZ")
        self.assertEqual(seen["agent"], "ds")
        p = seen["prompt"]
        self.assertIn("我的特别要求XYZ", p)
        self.assertLess(p.index("我的特别要求XYZ"), p.index("你在给一个多 Agent 小团队排工"))

    def test_no_inject_when_empty(self):
        g = self.g
        seen = {}
        g["ask"] = lambda cfg, agent, prompt, **kw: (seen.setdefault("p", prompt), json.dumps(
            {"summary": "s", "tasks": [{"id": "t1", "agent": "gemini", "title": "x", "prompt": "p"}]}))[1:] + ("dsh",)
        cfg = g["load_config"]()
        g["make_plan"](cfg, "目标B", self.tmp, False, "ds", 3, inject="   ")
        self.assertTrue(seen["p"].startswith("你在给一个多 Agent 小团队排工"))

    def test_config_saves_prompt(self):
        g = self.g
        Path(g["CONFIG_PATH"]).write_text(json.dumps({"pressure_prompt": "abc"}))
        self.assertEqual(g["load_config"]().get("pressure_prompt"), "abc")


if __name__ == "__main__":
    unittest.main()

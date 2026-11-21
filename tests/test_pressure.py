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
        self.assertLess(p.index("我的特别要求XYZ"), p.index("为平等协作的小团队排工"))

    def test_no_inject_when_empty(self):
        g = self.g
        seen = {}
        g["ask"] = lambda cfg, agent, prompt, **kw: (seen.setdefault("p", prompt), json.dumps(
            {"summary": "s", "tasks": [{"id": "t1", "agent": "gemini", "title": "x", "prompt": "p"}]}))[1:] + ("dsh",)
        cfg = g["load_config"]()
        g["make_plan"](cfg, "目标B", self.tmp, False, "ds", 3, inject="   ")
        self.assertTrue(seen["p"].startswith("为平等协作的小团队排工"))

    def test_config_saves_prompt(self):
        g = self.g
        Path(g["CONFIG_PATH"]).write_text(json.dumps({"pressure_prompt": "abc"}))
        self.assertEqual(g["load_config"]().get("pressure_prompt"), "abc")

    def test_pressure_chat_uses_ds_inject_and_dispatch(self):
        g = self.g
        seen, dispatched = {}, {}

        def fake_ask(cfg, agent, prompt, **kw):
            seen["agent"], seen["prompt"], seen["write"], seen["meta"] = agent, prompt, kw.get("write"), kw.get("meta")
            cid = "c_1234567890"
            g["write_json"](os.path.join(g["CALLS_DIR"], cid + ".json"), {"id": cid, "status": "running", "start": 1.0})
            if kw.get("meta") and kw["meta"].get("on_start"):
                kw["meta"]["on_start"](cid)
            return "【派活】自动分工：完成任务Z", "dsh"

        def fake_run_goal(cfg, goal, cwd, write, planner, synth, *a, **kw):
            dispatched.update(goal=goal, write=write, planner=planner, synth=synth, pressure=kw.get("pressure"))
            return 0

        g["ask"] = fake_ask
        g["run_goal"] = fake_run_goal
        cfg = g["load_config"]()
        cfg["pressure_prompt"] = "高压规范ABC"
        g["run_chat"](cfg, "开工吧", cwd=self.tmp, write=True, pressure=True)
        self.assertEqual(seen["agent"], "ds")
        self.assertTrue(seen["write"])
        self.assertTrue(seen["prompt"].startswith("高压规范ABC\n\n---\n\n"))
        self.assertTrue(seen["meta"].get("pressure"))
        self.assertEqual(dispatched, {"goal": "完成任务Z", "write": True, "planner": "ds", "synth": "ds", "pressure": True})

    def test_pressure_reset_dispatch_stops_busy_and_restarts(self):
        g = self.g
        stopped, dispatched, seen = [], {}, {}

        def fake_ask(cfg, agent, prompt, **kw):
            seen["note"], seen["prompt"] = kw.get("note"), prompt
            cid = "c_abcdef1234"
            g["write_json"](os.path.join(g["CALLS_DIR"], cid + ".json"), {"id": cid, "status": "running", "start": 1.0})
            if kw.get("meta") and kw["meta"].get("on_start"):
                kw["meta"]["on_start"](cid)
            return "【重置派活】自动分工：改写后的新目标", "dsh"

        g["ask"] = fake_ask
        g["busy_runs_in_line"] = lambda: [{"id": "20261120-010101", "goal": "旧目标", "done": 0, "total": 2}]
        g["stop_record"] = lambda kind, rid: (stopped.append((kind, rid)), None)[1]
        g["run_goal"] = lambda cfg, goal, cwd, write, planner, synth, *a, **kw: (
            dispatched.update(goal=goal, planner=planner, synth=synth, pressure=kw.get("pressure")), 0
        )[1]
        cfg = g["load_config"]()
        g["run_chat"](cfg, "停掉重做", cwd=self.tmp, write=True, pressure=True)
        self.assertTrue(seen["note"])
        self.assertIn("hub ask <agent>", g["team_note"](cfg, "ds"))
        self.assertIn("【重置派活】", seen["prompt"])
        self.assertEqual(stopped, [("run", "20261120-010101")])
        self.assertEqual(dispatched, {"goal": "改写后的新目标", "planner": "ds", "synth": "ds", "pressure": True})


if __name__ == "__main__":
    unittest.main()

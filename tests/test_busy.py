"""团队还在后台做时接着说话：不叠派、补充转告给团队。"""
import json, os, sys, tempfile, unittest
from unittest.mock import patch

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub")


class Busy(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["HUB_HOME"] = self.home
        self.g = {"__name__": "hubmod"}
        exec(compile(open(HUB, encoding="utf-8").read(), HUB, "exec"), self.g)
        g = self.g
        os.makedirs(os.path.join(g["RUNS_DIR"], "r1"))
        g["write_json"](os.path.join(g["RUNS_DIR"], "r1", "run.json"),
                        {"id": "r1", "status": "running", "pid": os.getpid(), "goal": "画图", "tasks": [{"id": "t1", "status": "ok"}, {"id": "t2", "status": "running"}]})
        g["write_json"](os.path.join(g["CALLS_DIR"], "c_aaa.json"),
                        {"id": "c_aaa", "kind": "chat", "agent": "gemini", "status": "running", "dispatch": {"run": "r1"}, "backend": "agy:m"})
        os.environ["HUB_META"] = json.dumps({"follows": {"type": "call", "id": "c_aaa"}, "display": "再加一张"})

    def tearDown(self):
        os.environ.pop("HUB_META", None)

    def chat(self, reply):
        g, seen = self.g, []

        def fake_ask(cfg, agent, prompt, **kw):
            seen.append(prompt)
            cid = "c_bbb"
            kw["meta"]["on_start"](cid)
            g["write_json"](os.path.join(g["CALLS_DIR"], cid + ".json"), {"id": cid, "status": "running"})
            return reply, "agy:m"
        cfg = {"agents": {"gemini": ["agy:m"]}, "planner": ["gemini"], "synthesizer": ["gemini"]}
        with patch.dict(g, {"ask": fake_ask, "choose_contact": lambda *a: ("gemini", "plan", "x"), "previous_contact": lambda: "gemini",
                            "run_goal": lambda *a, **k: self.fail("不该再派一份")}):
            g["run_chat"](cfg, "再加一张", contact="gemini")
        return seen, g["read_json"](os.path.join(g["CALLS_DIR"], "c_bbb.json"))

    def test_dispatch_becomes_note(self):
        seen, rec = self.chat("【派活】自动分工：再画一张蓝色的")
        self.assertIn("先前任务「画图」仍在进行，已完成 1/2", seen[0])
        self.assertEqual(self.g["run_notes"]("r1"), ["再画一张蓝色的"])
        self.assertIn("转告给了正在做的团队", rec["answer"])
        self.assertIn("再画一张蓝色的", self.g["board_text"]({"id": "r1", "goal": "画图", "tasks": []}, "t1"))

    def test_relay_line(self):
        _, rec = self.chat("好的，我让他们加上。\n【转告团队】背景改成白色")
        self.assertEqual(self.g["run_notes"]("r1"), ["背景改成白色"])
        self.assertIn("已转告正在做的团队：背景改成白色", rec["answer"])

    def test_not_busy_when_done(self):
        g = self.g
        g["write_json"](os.path.join(g["RUNS_DIR"], "r1", "run.json"), {"id": "r1", "status": "done", "pid": os.getpid()})
        self.assertEqual(g["busy_runs_in_line"](), [])


class FullAccess(unittest.TestCase):
    def test_hub_full_makes_every_call_writable(self):
        home = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": home, "HUB_FULL": "1", "HUB_READONLY": ""}):
            g = {"__name__": "hubmod"}
            exec(compile(open(HUB, encoding="utf-8").read(), HUB, "exec"), g)
            seen = []

            def fake(cfg, model, prompt, cwd, write, timeout):
                seen.append(write)
                return "好"
            with patch.dict(g["BACKENDS"], {"agy": fake}):
                g["ask"]({"agents": {"gemini": ["agy:m"]}, "timeout": 60}, "gemini", "会审问题", cwd=home, write=False, quiet=True,
                         meta={"kind": "task", "run": "r"})
        self.assertEqual(seen, [True])


if __name__ == "__main__":
    unittest.main()

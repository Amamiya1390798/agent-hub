"""项目组起名：手动名优先、哪些记录该起名、起名不留调用记录。全部离线。"""
import os, runpy, tempfile, time, unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))


class NameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": self.tmp}):
            ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__
        self.cfg = self.g["load_config"]()

    def test_manual_beats_auto(self):
        g = self.g
        g["set_name"]("call:c_1", "自动名", auto=True)
        self.assertEqual(g["load_names"](), {"call:c_1": "自动名"})
        g["set_name"]("call:c_1", "我起的")
        g["set_name"]("call:c_1", "又一个自动名", auto=True)
        self.assertEqual(g["load_names"]()["call:c_1"], "我起的")
        g["set_name"]("call:c_1", "")
        self.assertNotIn("call:c_1", g["load_names"]())
        for bad in (("../x", "a"), ("call:c_1", "字" * 61), ("call:c_1", 3)):
            with self.assertRaises(ValueError):
                g["set_name"](*bad)

    def test_clean_title(self):
        c = self.g["clean_title"]
        self.assertEqual(c("「专辑筹备计划」。\n第二行"), "专辑筹备计划")
        self.assertEqual(c("  **声卡对比**  "), "声卡对比")
        self.assertEqual(c(""), "")
        self.assertEqual(len(c("长" * 50)), 24)

    def test_candidates(self):
        g = self.g
        self.assertEqual(g["title_candidates"]([], []), [], "第一次只记下时间")
        t = time.time() + 1
        calls = [
            {"id": "c_new", "kind": "chat", "status": "ok", "start": t},
            {"id": "c_follow", "kind": "chat", "status": "ok", "start": t, "follows": {"type": "call", "id": "c_new"}},
            {"id": "c_fork", "kind": "ask", "status": "ok", "start": t, "follows": {"type": "call", "id": "c_new"}, "fork": True},
            {"id": "c_side", "kind": "side", "status": "ok", "start": t},
            {"id": "c_img", "kind": "image", "status": "ok", "start": t},
            {"id": "c_sub", "kind": "ask", "status": "ok", "start": t, "parent": "c_x"},
            {"id": "c_run", "kind": "ask", "status": "running", "start": t},
            {"id": "c_old", "kind": "ask", "status": "ok", "start": 1},
        ]
        runs = [{"id": "r1", "status": "done", "start": t}, {"id": "r2", "status": "done", "start": t, "parent_call": "c_new"}]
        got = set(g["title_candidates"](calls, runs))
        self.assertEqual(got, {"call:c_new", "call:c_fork", "run:r1"})
        g["set_name_since"](0)
        self.assertIn("call:c_old", g["title_candidates"](calls, runs), "点了「给已有的起名」后旧的也起")
        g["set_archived"](["call:c_old"], True)
        self.assertNotIn("call:c_old", g["title_candidates"](calls, runs), "归档的不起")

    def test_auto_title_one_leaves_no_record(self):
        g = self.g
        g["write_json"](os.path.join(g["CALLS_DIR"], "c_abc.json"),
                        {"id": "c_abc", "kind": "ask", "status": "ok", "display": "帮我比较两款声卡", "answer": "A 更稳"})
        seen = []

        def fake(cfg, model, prompt, cwd, write, timeout):
            seen.append(prompt)
            return "「声卡对比」"
        cfg = dict(self.cfg, auto_title="ds")
        cfg["agents"] = dict(cfg["agents"], ds=["dsh"])
        with patch.dict(g["BACKENDS"], {"dsh": fake}):
            g["auto_title_one"](cfg, "call:c_abc")
        self.assertEqual(g["load_names"]()["call:c_abc"], "声卡对比")
        self.assertIn("帮我比较两款声卡", seen[0])
        self.assertEqual(os.listdir(g["CALLS_DIR"]), ["c_abc.json"], "起名不写调用记录")

        def boom(*a):
            raise g["BackendError"]("x")
        g["write_json"](os.path.join(g["CALLS_DIR"], "c_def.json"), {"id": "c_def", "kind": "ask", "status": "ok", "display": "q"})
        with patch.dict(g["BACKENDS"], {"dsh": boom}):
            g["auto_title_one"](cfg, "call:c_def")
        self.assertEqual(g["load_names_raw"]()["failed"]["call:c_def"], 1)


if __name__ == "__main__":
    unittest.main()

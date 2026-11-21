"""交接整组：先放最近几轮顶着，后台把整组压缩成交接说明再换上；压缩失败保留原内容。"""
import os, tempfile, threading, time, unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub")


class Digest(unittest.TestCase):
    def setUp(self):
        os.environ["HUB_HOME"] = tempfile.mkdtemp()
        self.g = g = {"__name__": "hubmod"}
        exec(compile(open(HUB, encoding="utf-8").read(), HUB, "exec"), g)
        w, C = g["write_json"], g["CALLS_DIR"]
        os.makedirs(C, exist_ok=True)
        w(os.path.join(C, "c_a1.json"), {"id": "c_a1", "kind": "chat", "status": "ok", "display": "定个命名规则", "answer": "就叫 yan_v5", "start": 1})
        w(os.path.join(C, "c_a2.json"), {"id": "c_a2", "kind": "chat", "status": "ok", "display": "出图", "answer": "图在 out/1.png", "start": 2,
                                         "follows": {"type": "call", "id": "c_a1"}})
        w(os.path.join(C, "c_b1.json"), {"id": "c_b1", "kind": "chat", "status": "ok", "display": "别的组", "answer": "好", "start": 3})
        self.cfg = {"agents": {"gemini": ["agy:m"]}, "synthesizer": "gemini"}

    def wait(self, cid):
        for _ in range(100):
            rec = self.g["read_json"](os.path.join(self.g["CALLS_DIR"], cid + ".json"))
            if rec["handoff"].get("digest") != "running":
                return rec
            time.sleep(0.05)
        self.fail("压缩一直没结束")

    def test_digest_replaces_answer(self):
        seen = []

        def fake(cfg, model, prompt, cwd, write, timeout):
            seen.append(prompt)
            return "1. 目标：出图\n2. 命名 yan_v5"
        self.g["BACKENDS"]["agy"] = fake
        cid = self.g["make_handoff"]({"type": "call", "id": "c_a2"}, {"type": "call", "id": "c_b1"}, "生图",
                                     keys=["call:c_a1", "call:c_a2"], cfg=self.cfg)
        rec = self.wait(cid)
        self.assertEqual(rec["handoff"]["digest"], "ok")
        self.assertIn("命名 yan_v5", rec["answer"])
        self.assertIn("2 轮压缩", rec["answer"])
        self.assertIn("定个命名规则", seen[0])
        self.assertIn("out/1.png", seen[0])

    def test_digest_failure_keeps_recent(self):
        def boom(*a):
            raise self.g["BackendError"]("超时（900s）")
        self.g["BACKENDS"]["agy"] = boom
        cid = self.g["make_handoff"]({"type": "call", "id": "c_a2"}, {"type": "call", "id": "c_b1"}, "生图",
                                     keys=["call:c_a1", "call:c_a2"], cfg=self.cfg)
        rec = self.wait(cid)
        self.assertEqual(rec["handoff"]["digest"], "fail")
        self.assertIn("out/1.png", rec["answer"])

    def test_handoff_and_compact_are_ready_before_background_digest(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        g = self.g
        digest = g["_digest_handoff"]

        def wait_to_digest(*args):
            started.set()
            release.wait(5)
            try:
                digest(*args)
            finally:
                finished.set()

        g["_digest_handoff"] = wait_to_digest
        g["BACKENDS"]["agy"] = lambda *args: "交接好了"
        source = {"type": "call", "id": "c_a2"}
        target = {"type": "call", "id": "c_b1"}
        keys = ["call:c_a1", "call:c_a2"]
        for compact in (False, True):
            with self.subTest(compact=compact):
                started.clear()
                release.clear()
                finished.clear()
                try:
                    if compact:
                        cid = g["make_compact"](source, keys, self.cfg)
                    else:
                        cid = g["make_handoff"](source, target, keys=keys, cfg=self.cfg)
                    self.assertTrue(started.wait(5))
                    rec = g["ui_call"](cid)
                    self.assertEqual(rec["follows"], source if compact else target)
                    self.assertEqual(rec["handoff"]["from"], None if compact else source)
                    self.assertEqual((rec["handoff"]["digest"], rec["handoff"]["rounds"]), ("running", 2))
                    self.assertIn("out/1.png", rec["answer"])
                finally:
                    release.set()
                    finished.wait(5)

    def test_compact_cuts_context(self):
        g = self.g
        g["BACKENDS"]["agy"] = lambda *a: "命名 yan_v5；图在 out/1.png"
        cid = g["make_compact"]({"type": "call", "id": "c_a2"}, ["call:c_a1", "call:c_a2"], self.cfg, "生图")
        rec = self.wait(cid)
        self.assertTrue(rec["handoff"]["compact"])
        self.assertIn("前面 2 轮的压缩说明", rec["answer"])
        g["write_json"](os.path.join(g["CALLS_DIR"], "c_a3.json"), {"id": "c_a3", "kind": "chat", "status": "ok", "display": "接着出图",
                                                                   "answer": "好" * 3000, "start": 9, "follows": {"type": "call", "id": cid}})
        ctx = g["follow_context"]("call", "c_a3")
        self.assertIn("压缩说明", ctx)
        self.assertNotIn("定个命名规则", ctx, "压缩点之前的不再带")
        self.assertIsNone(g["resume_plan"]("gemini", {"follows": {"type": "call", "id": cid}}, {}, False), "压缩后不续接旧会话")
        with self.assertRaises(ValueError):
            g["make_compact"]({"type": "call", "id": "c_a1"}, ["call:c_a1"], self.cfg)

    def test_handoff_not_truncated_later(self):
        g = self.g
        long = "要点" * 2000
        g["write_json"](os.path.join(g["CALLS_DIR"], "c_ee.json"), {"id": "c_ee", "kind": "handoff", "status": "ok", "display": "交接", "answer": long,
                                                                  "start": 4, "follows": {"type": "call", "id": "c_b1"}, "handoff": {"name": "x"}})
        g["write_json"](os.path.join(g["CALLS_DIR"], "c_b2.json"), {"id": "c_b2", "kind": "chat", "status": "ok", "display": "问", "answer": "答",
                                                                   "start": 5, "follows": {"type": "call", "id": "c_ee"}})
        self.assertIn(long, g["follow_context"]("call", "c_b2"))


if __name__ == "__main__":
    unittest.main()

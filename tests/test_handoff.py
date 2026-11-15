"""项目组交接：把一组的结果接到另一组后面，之后追问能同时带上两边。全部离线。"""
import os, runpy, tempfile, unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": self.tmp}):
            ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__
        os.makedirs(self.g["CALLS_DIR"], exist_ok=True)

    def call(self, cid, **kw):
        r = {"id": cid, "kind": "chat", "agent": "claude", "status": "ok", "start": 1, "display": "", "answer": ""}
        r.update(kw)
        self.g["write_json"](os.path.join(self.g["CALLS_DIR"], cid + ".json"), r)

    def test_handoff_and_context(self):
        g = self.g
        self.call("c_a1", display="我想学生图", answer="先装 ComfyUI")
        self.call("c_a2", display="controlnet 是什么", answer="控制构图的插件", follows={"type": "call", "id": "c_a1"})
        self.call("c_b1", kind="ask", agent="gemini", display="总结这批 B 站视频", answer="视频要点：分层上色")
        hid = g["make_handoff"]({"type": "call", "id": "c_b1"}, {"type": "call", "id": "c_a2"}, "B站视频总结")
        h = g["read_json"](os.path.join(g["CALLS_DIR"], hid + ".json"))
        self.assertEqual(h["kind"], "handoff")
        self.assertEqual(h["follows"], {"type": "call", "id": "c_a2"})
        self.assertEqual(h["handoff"]["from"], {"type": "call", "id": "c_b1"})
        self.assertIn("视频要点：分层上色", h["answer"])
        self.assertNotIn("用户现在的追问", h["answer"])
        ctx = g["follow_context"]("call", hid)
        for part in ("我想学生图", "控制构图的插件", "视频要点：分层上色"):
            self.assertIn(part, ctx, part)
        self.assertLess(ctx.index("我想学生图"), ctx.index("视频要点"), "按时间顺序：先原来的对话，再交接")

    def test_validation(self):
        g = self.g
        self.call("c_a1", display="q", answer="a")
        self.call("c_run", status="running", display="还在做")
        self.call("c_syn", status="synthesizing", display="在汇总")
        self.call("c_empty", display="", answer="")
        for src, dst in ((("call", "c_a1"), ("call", "c_a1")), (("call", "c_run"), ("call", "c_a1")), (("call", "c_syn"), ("call", "c_a1")),
                         (("call", "c_none"), ("call", "c_a1")), (("call", "../x"), ("call", "c_a1")),
                         (("call", "c_empty"), ("call", "c_a1"))):
            with self.assertRaises(ValueError, msg=(src, dst)):
                g["make_handoff"]({"type": src[0], "id": src[1]}, {"type": dst[0], "id": dst[1]})
        with self.assertRaises(ValueError):
            g["make_handoff"]("call:c_a1", {"type": "call", "id": "c_a1"})

    def test_no_resume_after_handoff(self):
        g = self.g
        self.call("c_a1", display="q", answer="a", session={"id": "s1"}, backend="claude:opus")
        self.call("c_b1", display="b", answer="bb")
        hid = g["make_handoff"]({"type": "call", "id": "c_b1"}, {"type": "call", "id": "c_a1"})
        with patch.dict(os.environ, {"HUB_META": '{"follows": {"type": "call", "id": "%s"}, "display": "接着问"}' % hid}):
            self.assertIsNone(g["resume_plan"]("claude", g["top_meta"](), {}, False), "交接后要重发上文，不能续接旧会话")

    def test_undo(self):
        g = self.g
        self.call("c_a1", display="q", answer="a")
        self.call("c_b1", display="b", answer="bb")
        hid = g["make_handoff"]({"type": "call", "id": "c_b1"}, {"type": "call", "id": "c_a1"})
        self.call("c_a3", display="接着问", answer="x", follows={"type": "call", "id": hid})
        back = g["undo_handoff"](hid)
        self.assertEqual(back, {"type": "call", "id": "c_a1"})
        self.assertFalse(os.path.exists(os.path.join(g["CALLS_DIR"], hid + ".json")))
        self.assertTrue(os.path.exists(os.path.join(g["CALLS_DIR"], hid + ".json.undone")), "留底不真删")
        self.assertEqual(g["read_json"](os.path.join(g["CALLS_DIR"], "c_a3.json"))["follows"], {"type": "call", "id": "c_a1"})
        for bad in ("c_a1", "../x", "c_nope"):
            with self.assertRaises(ValueError, msg=bad):
                g["undo_handoff"](bad)


if __name__ == "__main__":
    unittest.main()

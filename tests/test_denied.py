"""Gemini 只读模式下被拒权限、交了空白回答：要说清原因，而且不换模型白白重试。全部离线。"""
import os, runpy, tempfile, unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))


class DeniedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": self.tmp}):
            ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__

    def test_text_and_reason(self):
        g = self.g
        t = g["agy_denied_text"]({"status": "SUCCESS", "response": "", "conversation_id": "x",
                                  "denied_actions": [{"action": "read_file"}, {"action": "command"}]})
        self.assertTrue(t.startswith(g["DENIED_PREFIX"]))
        self.assertIn("读文件", t)
        self.assertIn("运行命令", t)
        self.assertIn("没有权限", g["explain_error"](t)[0])

    def test_no_fallback(self):
        g = self.g
        calls = []

        def fake(cfg, model, prompt, cwd, write, timeout):
            calls.append(model)
            raise g["BackendError"](g["DENIED_PREFIX"] + "：测试")
        cfg = g["load_config"]()
        cfg["agents"]["gemini"] = ["agy:m1", "agy:m2"]
        with patch.dict(g["BACKENDS"], {"agy": fake}):
            with self.assertRaises(g["BackendError"]) as cm:
                g["ask"](cfg, "gemini", "hi", cwd=self.tmp, quiet=True)
        self.assertEqual(calls, ["m1"], "权限问题不该换备用模型重试")
        self.assertIn("没有权限", str(cm.exception))

    def test_readonly_can_read_anywhere(self):
        g = self.g
        seen = []

        def fake_run(cmd, cwd, env, timeout, **kw):
            seen.append(cmd)
            return 0, '{"event": "result", "result": {"status": "SUCCESS", "response": "ok"}}\n', ""
        with patch.dict(g, {"_run": fake_run, "find_bin": lambda cfg, n: "/bin/agy"}):
            for w in (False, True):
                try:
                    g["backend_agy"]({}, "m", "hi", self.tmp, w, 60)
                except g["BackendError"]:
                    pass  # 只看命令行
        ro, rw = seen
        self.assertIn("--settings", ro)
        self.assertIn("read_file(/)", ro[ro.index("--settings") + 1])
        self.assertNotIn("--dangerously-skip-permissions", ro, "只读不能放开写和命令")
        self.assertIn("--dangerously-skip-permissions", rw)


if __name__ == "__main__":
    unittest.main()

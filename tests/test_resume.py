"""追问续接原生会话：条件、分支不续接、失败退回重发上文、各家续接参数。全部离线。"""
import json, os, runpy, tempfile, unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": self.tmp}):
            ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__
        self.cfg = self.g["load_config"]()
        self.cfg["agents"] = dict(self.cfg["agents"], gemini=["agy:m1", "agy:m2"])
        os.makedirs(self.g["CALLS_DIR"], exist_ok=True)

    def target(self, cid="c_aaa", **kw):
        rec = {"id": cid, "kind": "ask", "agent": "gemini", "status": "ok", "backend": "agy:m1",
               "session": {"id": "conv-1"}, "display": "第一问", "answer": "第一答"}
        rec.update(kw)
        self.g["write_json"](os.path.join(self.g["CALLS_DIR"], cid + ".json"), rec)
        return rec

    def env(self, **meta):
        m = {"follows": {"type": "call", "id": "c_aaa"}, "display": "第二问"}
        m.update(meta)
        return patch.dict(os.environ, {"HUB_META": json.dumps(m, ensure_ascii=False)})

    def plan(self, **meta):
        with self.env(**meta):
            return self.g["resume_plan"]("gemini", self.g["top_meta"](), {}, False)

    def test_conditions(self):
        self.target()
        p = self.plan()
        self.assertEqual((p["sid"], p["backend"], p["prompt"]), ("conv-1", "agy:m1", "第二问"))
        self.assertIsNone(self.plan(fork=True), "分叉不续接")
        self.assertIsNone(self.plan(scope="one"), "只带一条上文不续接")
        with self.env():
            self.assertIsNone(self.g["resume_plan"]("gpt", self.g["top_meta"](), {}, False), "换人不续接")
        self.target(dispatch={"run": "r"}, answer="派活了\n\n---\n\n团队结果")
        p = self.plan()
        self.assertTrue(p and p["prompt"].startswith("（上一轮团队任务已结束") and "团队结果" in p["prompt"] and p["prompt"].endswith("第二问"), "派过活也续接，把团队结果补进去")
        with self.env():
            self.target()
            self.assertIsNone(self.g["resume_plan"]("gemini", self.g["top_meta"](), {"kind": "side"}, False), "旁问不抢主对话的会话")
        for bad in ({"session_continued_by": "c_x"}, {"status": "fail"}, {"session": None},
                    {"session": {"id": "bad id; rm"}}, {"kind": "image"}):
            self.target(**bad)
            self.assertIsNone(self.plan(), bad)

    def test_long_gemini_session_compacts_itself(self):
        cfg = {"compact_gemini": 200000}
        self.target(backend="agy:m1", tokens={"in": 3000, "cache": 900000, "ctx": 150000})
        with self.env():
            p = self.g["resume_plan"]("gemini", self.g["top_meta"](), {}, False, cfg)
            self.assertFalse(p["compact"], "会话还不长：照常续接")
            self.assertEqual(p["prompt"], "第二问")
        self.target(backend="agy:m1", tokens={"in": 3000, "cache": 900000, "ctx": 210000})
        with self.env():
            p = self.g["resume_plan"]("gemini", self.g["top_meta"](), {}, False, cfg)
            self.assertTrue(p["compact"] and p["prompt"].startswith("/compact 第二问"), "超过门槛：同一个会话里先压缩再回答")
            self.assertIsNotNone(self.g["resume_plan"]("gemini", self.g["top_meta"](), {}, False, {"compact_gemini": 0}), "填 0：不管")
        self.target(backend="agy:m1", compact="asked", tokens={"ctx": 230000})
        with self.env():
            self.assertIsNone(self.g["resume_plan"]("gemini", self.g["top_meta"](), {}, False, cfg), "让它压缩过却没压成：换新会话兜底")
        self.target(backend="agy:m1", compact="asked", tokens={"ctx": 230000, "compacted": 1})
        with self.env():
            self.assertTrue(self.g["resume_plan"]("gemini", self.g["top_meta"](), {}, False, cfg)["compact"], "压成了但又长了：继续压")

    def test_compact_turn_marks_record_and_skips_keep(self):
        g, seen = self.g, []
        self.cfg["compact_gemini"] = 200000
        self.target(backend="agy:m1", tokens={"ctx": 250000})

        def fake(cfg, model, prompt, cwd, write, timeout):
            seen.append((cfg.get("_resume"), cfg.get("_keep"), prompt))
            g["_ctx"].session = {"id": cfg.get("_resume") or "conv-new"}
            g["_ctx"].tokens = {"in": 1, "out": 1, "cache": 1, "ctx": 9000, "compacted": 1}
            return "答"
        with self.env(), patch.dict(g["BACKENDS"], {"agy": fake}):
            g["ask"](self.cfg, "gemini", "【前文】第一问 第一答\n第二问", quiet=True)
        self.assertEqual(seen[0][0], "conv-1")
        self.assertFalse(seen[0][1], "压缩这一轮不走常驻会话")
        self.assertTrue(seen[0][2].startswith("/compact "))
        rec = [g["read_json"](os.path.join(g["CALLS_DIR"], f)) for f in os.listdir(g["CALLS_DIR"]) if f != "c_aaa.json"][0]
        self.assertEqual(rec["compact"], "asked")
        self.assertEqual(rec["tokens"]["compacted"], 1)

    def test_gpt_and_claude_get_their_own_compact_limits(self):
        g, got = self.g, {}

        def fake_run(cmd, cwd, env, timeout, **kw):
            got["cmd"], got["env"] = cmd, env
            raise g["BackendError"]("stop")
        cfg = dict(self.cfg, compact_gpt=220000, compact_claude=400000)
        with patch.dict(g, {"_run": fake_run, "find_bin": lambda *a: "/fake"}):
            for fn in ("backend_codex", "backend_claude"):
                try:
                    g[fn](cfg, "", "hi", self.tmp, False, 5)
                except Exception:
                    pass
                if fn == "backend_codex":
                    self.assertIn("model_auto_compact_token_limit=220000", got["cmd"])
                else:
                    self.assertEqual(got["env"].get("CLAUDE_CODE_AUTO_COMPACT_WINDOW"), "400000")

    def run_ask(self, fail_resume=False, spec_used=None):
        g, seen = self.g, []

        def fake(cfg, model, prompt, cwd, write, timeout):
            seen.append((model, cfg.get("_resume"), prompt))
            if cfg.get("_resume") and fail_resume:
                raise g["BackendError"]("会话过期")
            g["_ctx"].session = {"id": cfg.get("_resume") or "conv-new"}
            return "答"
        with self.env(), patch.dict(g["BACKENDS"], {"agy": fake}):
            g["ask"](self.cfg, "gemini", "【前文】第一问 第一答\n第二问", quiet=True)
        return seen

    def test_resume_then_branch_does_not(self):
        g = self.g
        self.target()
        seen = self.run_ask()
        self.assertEqual(seen, [("m1", "conv-1", "第二问")], "续接时只发这一轮的话")
        t = g["read_json"](os.path.join(g["CALLS_DIR"], "c_aaa.json"))
        self.assertTrue(t["session_continued_by"])
        seen = self.run_ask()  # 同一条再追问一次 = 分支，不能再往原会话里加
        self.assertEqual(seen[0][1], None)
        self.assertIn("【前文】", seen[0][2])

    def test_resume_failure_falls_back(self):
        g = self.g
        self.target()
        seen = self.run_ask(fail_resume=True)
        self.assertEqual([s[1] for s in seen], ["conv-1", None])
        self.assertIn("【前文】", seen[1][2])
        recs = [g["read_json"](os.path.join(g["CALLS_DIR"], f)) for f in os.listdir(g["CALLS_DIR"])]
        new = [r for r in recs if r["id"] != "c_aaa"][0]
        self.assertEqual(new["status"], "ok")
        self.assertTrue(new["attempts"][0]["resume_failed"])
        self.assertNotIn("resumed", new)

    def test_different_model_does_not_resume(self):
        self.target(backend="agy:m2")
        seen = self.run_ask()
        self.assertEqual(seen[0][:2], ("m1", None))   # m1 不是原来的模型，新开会话
        self.assertTrue(seen[0][2].startswith("【前文】"))

    def _cmd(self, backend, out="收到", **extra):
        seen = {}

        def fake_run(cmd, *a, **kw):
            seen["cmd"] = cmd
            if backend == "backend_codex":
                with open(cmd[cmd.index("-o") + 1], "w") as f:
                    f.write("收到")
            if backend == "backend_agy":
                line = json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "收到"}})
                if kw.get("on_line"):
                    kw["on_line"](line)
                return 0, line, ""
            return 0, out, ""
        with patch.dict(self.g, {"find_bin": lambda *a: "/fake/cli", "_run": fake_run}):
            text = self.g[backend](dict(self.cfg, **extra), "", "hi", self.tmp, False, 1)
        return seen["cmd"], text

    def test_backend_flags(self):
        c, _ = self._cmd("backend_codex", _resume="th-1")
        self.assertEqual(c[1:3], ["exec", "resume"])
        self.assertIn('sandbox_mode="read-only"', c)
        self.assertNotIn("-s", c)
        self.assertEqual(c[-2:], ["th-1", "-"])
        c, _ = self._cmd("backend_codex")
        self.assertIn("-s", c)
        self.assertNotIn("resume", c)
        c, _ = self._cmd("backend_agy", _resume="conv-9")
        self.assertEqual(c[c.index("--conversation") + 1], "conv-9")
        c, _ = self._cmd("backend_dsh", out=json.dumps({"type": "final", "text": "收到"}), _resume="s-1")
        self.assertEqual(c[c.index("--session-id") + 1], "s-1")
        c, text = self._cmd("backend_claude", out=json.dumps({"type": "result", "result": "好的", "session_id": "cs-1",
                                                             "usage": {"input_tokens": 5, "cache_read_input_tokens": 40}}),
                            _resume="cs-0")
        self.assertEqual(c[c.index("--resume") + 1], "cs-0")
        self.assertEqual(text, "好的")
        self.assertEqual(self.g["_ctx"].session["id"], "cs-1")
        self.assertEqual(self.g["_ctx"].tokens["cache"], 40)
        _, text = self._cmd("backend_claude", out="纯文字回答")  # 万一不是 JSON，照旧当文字
        self.assertEqual(text, "纯文字回答")


if __name__ == "__main__":
    unittest.main()

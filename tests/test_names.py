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

    def _save(self, calls, runs=()):
        g = self.g
        for c in calls:
            g["write_json"](os.path.join(g["CALLS_DIR"], c["id"] + ".json"), c)
        for r in runs:
            os.makedirs(os.path.join(g["RUNS_DIR"], r["id"]), exist_ok=True)
            g["write_json"](os.path.join(g["RUNS_DIR"], r["id"], "run.json"), r)

    def test_candidates(self):
        g = self.g
        self.assertEqual(g["title_candidates"]([], []), [], "第一次只记下时间")
        t = time.time() + 1
        calls = [
            {"id": "c_aa01", "kind": "chat", "status": "ok", "start": t},
            {"id": "c_aa02", "kind": "chat", "status": "ok", "start": t + 1, "follows": {"type": "call", "id": "c_aa01"}},
            {"id": "c_aa03", "kind": "ask", "status": "ok", "start": t, "follows": {"type": "call", "id": "c_aa01"}, "fork": True},
            {"id": "c_aa04", "kind": "side", "status": "ok", "start": t},
            {"id": "c_aa05", "kind": "image", "status": "ok", "start": t},
            {"id": "c_aa06", "kind": "ask", "status": "ok", "start": t, "parent": "c_x"},
            {"id": "c_aa07", "kind": "ask", "status": "running", "start": t},
            {"id": "c_aa08", "kind": "ask", "status": "ok", "start": 1},
        ]
        runs = [{"id": "20261118-100000", "status": "done", "start": t},
                {"id": "20261118-100001", "status": "done", "start": t + 2, "parent_call": "c_aa02"}]
        self._save(calls, runs)
        got = dict(g["title_candidates"](calls, runs))
        self.assertEqual(set(got), {"call:c_aa01", "call:c_aa03", "run:20261118-100000"})
        self.assertEqual(got["call:c_aa01"], ["call:c_aa01", "call:c_aa02", "run:20261118-100001"], "整组都交给起名的人看")
        g["set_name_since"](0)
        self.assertIn("call:c_aa08", dict(g["title_candidates"](calls, runs)), "点了「给已有的起名」后旧的也起")
        g["set_archived"](["call:c_aa08"], True)
        self.assertNotIn("call:c_aa08", dict(g["title_candidates"](calls, runs)), "归档的不起")

    def _chain(self, n, start=None):
        t = start or time.time() + 1
        calls = [{"id": "c_%04x" % (0xb000 + i), "kind": "chat", "status": "ok", "start": t + i, "display": "第%d句" % i,
                  "answer": "答%d" % i} for i in range(n)]
        for i in range(1, n):
            calls[i]["follows"] = {"type": "call", "id": calls[i - 1]["id"]}
        self._save(calls)
        return calls

    def test_name_sticks_to_group_head(self):
        """面板只加载最近的记录：长对话开头掉出去后，改名也要记在真正的开头上，开头怎么变名字都不丢。"""
        g = self.g
        calls = self._chain(6)
        head = "call:" + calls[0]["id"]
        g["set_name"]("call:" + calls[3]["id"], "示例名")
        self.assertEqual(g["load_names"](), {head: "示例名"})
        self.assertEqual(g["ui_call_summary"](calls[5])["root"], head, "面板拿到的每一轮都带着开头")
        g["folder_op"]({"op": "create", "name": "工作", "keys": ["call:" + calls[4]["id"]]})
        self.assertEqual(list(g["load_folders"]()["of"]), [head])

    def test_old_names_move_to_head(self):
        g = self.g
        calls = self._chain(5)
        head, mid, late = ["call:" + calls[i]["id"] for i in (0, 2, 4)]
        with g["_names_lock"]:
            d = g["load_names_raw"]()
            d["names"] = {head: {"name": "自动名", "auto": True, "ts": 1},
                          mid: {"name": "cobla", "auto": False, "ts": 2},
                          late: {"name": "示例名", "auto": False, "ts": 3}}
            g["write_json"](g["NAMES_PATH"], d)
        g["write_json"](g["FOLDERS_PATH"], {"folders": [{"id": "f_1", "name": "x"}], "of": {mid: "f_1"}})
        g["rekey_to_roots"]()
        self.assertEqual(g["load_names"](), {head: "示例名"}, "手动的优先，都手动取最新的")
        self.assertEqual(g["load_folders"]()["of"], {head: "f_1"})

    def test_retitle_when_group_grows(self):
        g = self.g
        g["set_name_since"](0)
        calls = self._chain(3)
        head = "call:" + calls[0]["id"]
        g["set_name"](head, "开始", auto=True, rounds=3)
        self.assertEqual(g["title_candidates"](calls, []), [], "刚起过名")
        calls = self._chain(8, calls[0]["start"])
        self.assertEqual([k for k, _ in g["title_candidates"](calls, [])], [head], "长了 5 轮、翻倍：按新内容重起")
        g["set_name"](head, "我起的")
        self.assertEqual(g["title_candidates"](calls, []), [], "手动改过的永远不动")

    def test_title_reads_whole_group(self):
        g = self.g
        calls = self._chain(8)
        seen = []

        def fake(cfg, model, prompt, cwd, write, timeout):
            seen.append(prompt)
            return "批量去水印脚本"
        cfg = dict(self.cfg, auto_title="ds")
        cfg["agents"] = dict(cfg["agents"], ds=["dsh"])
        keys = ["call:" + c["id"] for c in calls]
        with patch.dict(g["BACKENDS"], {"dsh": fake}):
            g["auto_title_one"](cfg, keys[0], keys)
        for w in ("第0句", "第1句", "第7句", "答7"):
            self.assertIn(w, seen[0])
        self.assertNotIn("第4句", seen[0], "中间的省掉")
        saved = g["load_names_raw"]()["names"][keys[0]]
        self.assertEqual((saved["name"], saved["rounds"]), ("批量去水印脚本", 8))

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


    def test_digest_uses_chosen_member_and_model(self):
        """压缩说明由设置里选的人、选的模型和档位来写。"""
        g = self.g
        calls = self._chain(3)
        with patch.object(g["threading"], "Thread"):  # 不在后台真的叫模型
            cid = g["make_compact"]({"type": "call", "id": calls[-1]["id"]}, ["call:" + c["id"] for c in calls], self.cfg)
        seen = []

        def fake(cfg, model, prompt, cwd, write, timeout):
            seen.append((model, cfg.get("_effort")))
            return "目标：测试"
        cfg = dict(self.cfg, handoff_by="gpt", digest={"gpt": {"spec": "codex:gpt-x", "effort": "low"}})
        cfg["agents"] = dict(cfg["agents"], gpt=["codex:gpt-y"])
        with patch.dict(g["BACKENDS"], {"codex": fake}), patch.dict(g, {"effort_levels": lambda spec: ("low", "high")}):
            g["_digest_handoff"](cfg, cid, ["call:" + c["id"] for c in calls])
        self.assertEqual(seen[-1], ("gpt-x", "low"))
        rec = g["read_json"](os.path.join(g["CALLS_DIR"], cid + ".json"))
        self.assertEqual(rec["handoff"]["digest_by"], "codex:gpt-x")


if __name__ == "__main__":
    unittest.main()

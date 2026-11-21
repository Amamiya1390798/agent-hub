"""排工兜底：任务文本明确要产出文件、而排工者漏标 write=false 时，自动补成可写。
只在本次运行本身允许写（run 的 write=True）时生效；只读运行一律不提升。全部离线。"""
import json, os, runpy, tempfile, unittest


class WriteIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HUB_HOME"] = self.tmp
        ns = runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub"),
                            run_name="hub_test")
        self.g = ns["main"].__globals__

    # ---------- 判定函数 ----------
    def test_positive_cases(self):
        f = self.g["write_intent"]
        for title, prompt in [
            ("写 branch.md 与 patch.md", "在工作目录写两个文件：branch.md 说明 arm64 编码"),
            ("导出表格", "把结果导出成 CSV 表格"),
            ("生成脚本", "生成一个 lldb python 脚本用于读取 std::string"),
            ("改配置", "把 config.json 里的 timeout 改成 900"),
            ("英文", "create a file named notes.md with the summary"),
        ]:
            self.assertTrue(f(title, prompt), "应触发：%s" % title)

    def test_negative_cases(self):
        f = self.g["write_intent"]
        for title, prompt in [
            ("读文件并总结", "读取 /tmp/x.md 全部内容，总结成三条要点"),
            ("说明如何写代码", "说明如何写高效的 C 代码，不需要产出文件"),
            ("纯分析", "分析这个二进制里的符号表，给出可能的判定点"),
            ("明确不要写", "不要写文件，只把结论回给我"),
            ("评审", "评审这份实现，指出缺口并给修正补丁"),
        ]:
            self.assertFalse(f(title, prompt), "不应触发：%s" % title)

    # ---------- 排工兜底 ----------
    def _plan(self, run_write, task_write):
        g = self.g
        g["ask"] = lambda cfg, agent, prompt, **kw: (json.dumps({"summary": "s", "tasks": [
            {"id": "t1", "agent": "gemini", "title": "写 branch.md",
             "prompt": "在工作目录写 branch.md，说明 arm64 b 指令编码", "write": task_write},
        ]}), "dsh")
        cfg = g["load_config"]()
        return g["make_plan"](cfg, "目标", self.tmp, run_write, "ds", 3)["tasks"][0]

    def test_auto_promote_when_run_allows_write(self):
        t = self._plan(run_write=True, task_write=False)
        self.assertTrue(t["write"])
        self.assertTrue(t.get("write_auto"))

    def test_no_promote_when_run_is_readonly(self):
        t = self._plan(run_write=False, task_write=False)
        self.assertFalse(t["write"])
        self.assertFalse(t.get("write_auto"))

    def test_no_promote_when_planner_already_correct(self):
        t = self._plan(run_write=True, task_write=True)
        self.assertTrue(t["write"])
        self.assertFalse(t.get("write_auto"))

    def test_readonly_task_stays_readonly(self):
        g = self.g
        g["ask"] = lambda cfg, agent, prompt, **kw: (json.dumps({"summary": "s", "tasks": [
            {"id": "t1", "agent": "gemini", "title": "读并总结",
             "prompt": "读取 config.json 并总结其中的 timeout 字段", "write": False},
        ]}), "dsh")
        cfg = g["load_config"]()
        t = g["make_plan"](cfg, "目标", self.tmp, True, "ds", 3)["tasks"][0]
        self.assertFalse(t["write"])


if __name__ == "__main__":
    unittest.main()

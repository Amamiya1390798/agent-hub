"""回答里提到的文件：能找到的才给看/打开；隐藏目录、像密钥的文件、家目录外的一律不给。"""
import os, tempfile, unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub")


class Files(unittest.TestCase):
    def setUp(self):
        os.environ["HUB_HOME"] = tempfile.mkdtemp()
        self.g = {"__name__": "hubmod"}
        exec(compile(open(HUB, encoding="utf-8").read(), HUB, "exec"), self.g)
        home = os.path.realpath(tempfile.mkdtemp())
        hub = os.path.join(home, ".agent-hub")
        self.g.update(HOME=home, HUB_HOME=hub, UI_WORKSPACE=os.path.join(hub, "workspace"), RUNS_DIR=os.path.join(hub, "runs"))
        self.home, self.ws = home, os.path.join(hub, "workspace")
        for rel, text in [(".agent-hub/workspace/手册 一.md", "# 标题\n内容"), (".agent-hub/config.json", "{}"), (".ssh/id_rsa", "x"),
                          ("Documents/项目/out.txt", "hello"), ("Documents/api_key.txt", "k"), ("Documents/图.png", "\x89PNG"), ("Documents/tool.command", "echo")]:
            p = os.path.join(home, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)

    def test_targets(self):
        t = self.g["file_target"]
        ws_file = os.path.join(self.ws, "手册 一.md")
        self.assertEqual(t("file://" + ws_file.replace(" ", "%20")), ws_file)
        self.assertEqual(t("手册 一.md"), ws_file, "相对路径先找工作目录")
        self.assertEqual(t("out.txt", {"cwd": os.path.join(self.home, "Documents/项目")}), os.path.join(self.home, "Documents/项目/out.txt"))
        self.assertEqual(t(os.path.join(self.home, "Documents")), os.path.join(self.home, "Documents"))
        for bad in [os.path.join(self.home, ".ssh/id_rsa"), os.path.join(self.home, ".agent-hub/config.json"), os.path.join(self.home, "Documents/api_key.txt"),
                    "/etc/hosts", os.path.join(self.ws, "../config.json"), os.path.join(self.home, "nope.md"), "", None, "x" * 3000]:
            self.assertIsNone(t(bad), bad)

    def test_view(self):
        v = self.g["file_view"]
        r = v(os.path.join(self.ws, "手册 一.md"))
        self.assertEqual((r["kind"], r["text"]), ("md", "# 标题\n内容"))
        self.assertEqual(v(os.path.join(self.home, "Documents/图.png"))["kind"], "image")
        self.assertEqual(v(os.path.join(self.home, "Documents/tool.command"))["kind"], "other")
        d = v(os.path.join(self.home, "Documents"))
        self.assertEqual(d["kind"], "dir")
        self.assertIn("项目/", d["items"])
        with self.assertRaises(ValueError):
            v(os.path.join(self.home, ".ssh/id_rsa"))

    def test_open_ext(self):
        self.assertNotIn(".command", self.g["FILE_OPEN_EXT"])
        self.assertNotIn(".app", self.g["FILE_OPEN_EXT"])
        self.assertIn(".md", self.g["FILE_OPEN_EXT"])


if __name__ == "__main__":
    unittest.main(verbosity=1)

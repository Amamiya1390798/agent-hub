"""找命令行程序：PATH 很短（从 Hub.app 启动）时也要去常见目录找；配置里写死的路径不存在时按名字找；找不到时说人话。"""
import os, stat, tempfile, unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub")


def mkexe(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!/bin/sh\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class Bins(unittest.TestCase):
    def setUp(self):
        os.environ["HUB_HOME"] = tempfile.mkdtemp()
        os.environ["HUB_NO_SHELL_PATH"] = "1"
        self.g = {"__name__": "hubmod"}
        exec(compile(open(HUB, encoding="utf-8").read(), HUB, "exec"), self.g)
        self.home = tempfile.mkdtemp()
        self.g.update(HOME=self.home, SYS_BIN_DIRS=(), APP_BINS={})
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = "/usr/bin:/bin"

    def tearDown(self):
        os.environ["PATH"] = self.old_path

    def test_common_dirs(self):
        f = self.g["find_bin"]
        cfg = {"bins": {"agy": "agy", "codex": "/nowhere/codex"}}
        self.assertIsNone(f(cfg, "agy"))
        exe = mkexe(os.path.join(self.home, ".npm-global/bin/agy"))
        self.assertEqual(f(cfg, "agy"), exe, "PATH 很短时也去家目录常见位置找")
        cx = mkexe(os.path.join(self.home, ".local/bin/codex"))
        self.assertEqual(f(cfg, "codex"), cx, "写死的路径不存在时按名字找")
        good = mkexe(os.path.join(self.home, "tools/my-agy"))
        self.assertEqual(f({"bins": {"agy": good}}, "agy"), good, "写了存在的完整路径就用它")

    def test_app_bundle(self):
        exe = mkexe(os.path.join(self.home, "ChatGPT.app/codex"))
        self.g["APP_BINS"] = {"codex": [exe]}
        self.assertEqual(self.g["find_bin"]({"bins": {}}, "codex"), exe)

    def test_message(self):
        m = self.g["missing_bin_text"]("agy")
        self.assertIn("agy", m)
        self.assertIn("检查全部", m)
        self.assertEqual(self.g["explain_error"](m)[0], "这台电脑上没装这位成员要用的命令行软件")
        with self.assertRaises(ValueError) as cm:
            self.g["open_login"]({"bins": {"agy": "agy"}}, "agy")
        self.assertIn("没找到", str(cm.exception))


if __name__ == "__main__":
    unittest.main(verbosity=1)

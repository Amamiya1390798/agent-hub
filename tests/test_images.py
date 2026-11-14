"""贴图：只认真图片、文件名不能乱填、交给各家的方式。全部离线。"""
import json, os, runpy, tempfile, unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with patch.dict(os.environ, {"HUB_HOME": self.tmp}):
            ns = runpy.run_path(os.path.join(HERE, "..", "hub"), run_name="hub_test")
        self.g = ns["main"].__globals__
        self.cfg = self.g["load_config"]()

    def test_save_and_lookup(self):
        g = self.g
        name = g["save_attachment"](PNG)
        self.assertTrue(name.endswith(".png"))
        self.assertTrue(g["attachment_path"](name).startswith(g["ATTACH_DIR"]))
        self.assertTrue(g["save_attachment"](b"RIFF\0\0\0\0WEBPVP8 ").endswith(".webp"))
        for bad in (b"", b"<svg onload=alert(1)>", b"GIF8"):
            with self.assertRaises(ValueError):
                g["save_attachment"](bad)
        with self.assertRaises(ValueError):
            g["save_attachment"](PNG + b"\0" * (10 * 1024 * 1024))
        for bad in ("../config.json", "att-x.png", name.replace(".png", ".svg"), None, "att-20260101-000000-deadbeef.png"):
            self.assertIsNone(g["attachment_path"](bad), bad)

    def test_note_and_flags(self):
        g = self.g
        p = os.path.join(g["ATTACH_DIR"], "a.png")
        self.assertEqual(g["image_note"]([]), "")
        n = g["image_note"]([p, p])
        self.assertIn("2 张图片", n)
        self.assertIn("图 2：" + p, n)
        self.assertIn("read_image", n)
        seen = {}

        def fake_run(cmd, *a, **kw):
            seen["cmd"] = cmd
            if "-o" in cmd:
                with open(cmd[cmd.index("-o") + 1], "w") as f:
                    f.write("收到")
            return 0, json.dumps({"type": "result", "result": "收到"}), ""
        with patch.dict(g, {"find_bin": lambda *a: "/fake", "_run": fake_run}):
            g["backend_codex"](dict(self.cfg, _images=[p]), "", "hi", self.tmp, False, 1)
            self.assertIn("--image=" + p, seen["cmd"])
            self.assertLess(seen["cmd"].index("--image=" + p), seen["cmd"].index("-"))
            g["backend_claude"](dict(self.cfg, _images=[p]), "", "hi", self.tmp, False, 1)
            self.assertEqual(seen["cmd"][seen["cmd"].index("--add-dir") + 1], g["ATTACH_DIR"])
            g["backend_claude"](self.cfg, "", "hi", self.tmp, False, 1)
            self.assertNotIn("--add-dir", seen["cmd"])


if __name__ == "__main__":
    unittest.main()

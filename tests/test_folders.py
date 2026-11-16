"""左栏文件夹：建、放进、拿出、改名、删（删文件夹不删记录）。"""
import os, tempfile, unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub")


class Folders(unittest.TestCase):
    def setUp(self):
        os.environ["HUB_HOME"] = tempfile.mkdtemp()
        self.g = {"__name__": "hubmod"}
        exec(compile(open(HUB, encoding="utf-8").read(), HUB, "exec"), self.g)

    def test_flow(self):
        op, load = self.g["folder_op"], self.g["load_folders"]
        fid = op({"op": "create", "name": "生图", "keys": ["call:c_a"]})
        self.assertEqual(load()["of"], {"call:c_a": fid})
        op({"op": "move", "folder": fid, "keys": ["run:r_1"]})
        op({"op": "move", "folder": "", "keys": ["call:c_a"]})
        self.assertEqual(load()["of"], {"run:r_1": fid})
        op({"op": "rename", "id": fid, "name": "出图"})
        self.assertEqual(load()["folders"][0]["name"], "出图")
        op({"op": "delete", "id": fid})
        self.assertEqual(load(), {"folders": [], "of": {}})

    def test_bad_input(self):
        op = self.g["folder_op"]
        for b in ({"op": "create", "name": ""}, {"op": "create", "name": "x" * 41}, {"op": "move", "folder": "f_nope", "keys": []},
                  {"op": "move", "folder": "", "keys": ["../x"]}, {"op": "rename", "id": "f_nope", "name": "a"}, {"op": "boom"}):
            with self.assertRaises(ValueError):
                op(b)
        self.assertIn("/api/folders", self.g["REMOTE_POSTS"])


if __name__ == "__main__":
    unittest.main()

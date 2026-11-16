"""不休眠开关：开时起一个 caffeinate，关时收掉；重复开不叠。"""
import os, sys, tempfile, unittest

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub")


class Awake(unittest.TestCase):
    def setUp(self):
        os.environ["HUB_HOME"] = tempfile.mkdtemp()
        self.g = {"__name__": "hubmod"}
        exec(compile(open(HUB, encoding="utf-8").read(), HUB, "exec"), self.g)
        self.g["shutil"].which = lambda n, **k: "/bin/sleep" if n == "caffeinate" else None

    def test_toggle(self):
        g, calls = self.g, []
        real = g["subprocess"].Popen

        def fake(cmd, **kw):
            calls.append(cmd)
            return real(["/bin/sleep", "30"], **kw)
        g["subprocess"].Popen = fake
        try:
            self.assertFalse(g["awake_on"]())
            self.assertTrue(g["set_awake"](True))
            self.assertTrue(g["set_awake"](True))
            self.assertEqual(len(calls), 1)
            self.assertIn("-i", calls[0])
            self.assertIn(str(os.getpid()), calls[0])
            p = g["_awake"]["p"]
            self.assertFalse(g["set_awake"](False))
            self.assertIsNotNone(p.poll())
            self.assertFalse(g["awake_on"]())
        finally:
            g["subprocess"].Popen = real
            g["set_awake"](False)

    def test_remote_allowed_and_default_off(self):
        self.assertIn("/api/awake", self.g["REMOTE_POSTS"])
        self.assertFalse(self.g["DEFAULT_CONFIG"]["keep_awake"])


if __name__ == "__main__":
    unittest.main()

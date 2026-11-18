"""动脑/干活两档模型：动脑的活换用成员的「动脑模型」和档位，其他照旧。"""
import os, sys, tempfile, unittest
from unittest.mock import patch

HUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub")


class Think(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["HUB_HOME"] = self.home
        os.environ.pop("HUB_META", None)
        os.environ.pop("HUB_FULL", None)
        self.g = {"__name__": "hubmod"}
        exec(compile(open(HUB, encoding="utf-8").read(), HUB, "exec"), self.g)
        self.cfg = self.g["load_config"]()
        self.cfg["agents"] = {"gemini": ["agy:m-medium", "agy:m-low"], "gpt": ["codex:x"]}
        self.cfg["think"] = {"gemini": {"spec": "agy:m-high", "effort": ""}, "gpt": {"spec": "", "effort": "high"}}
        self.cfg["effort"] = {"gpt": "medium"}
        self.seen = []

    def run_ask(self, agent, **kw):
        g = self.g

        def fake(cfg, model, prompt, cwd, write, timeout):
            self.seen.append((model, cfg.get("_effort")))
            return "ok"
        with patch.dict(g["BACKENDS"], {"agy": fake, "codex": fake}), \
             patch.dict(g, {"effort_levels": lambda sp: ["low", "medium", "high"] if sp.startswith("codex") else []}):
            return g["ask"](self.cfg, agent, "hi", cwd=self.home, quiet=True, note=False, **kw)

    def test_work_uses_primary(self):
        self.run_ask("gemini")
        self.assertEqual(self.seen, [("m-medium", "")])

    def test_think_uses_think_model(self):
        _, spec = self.run_ask("gemini", tier="think")
        self.assertEqual(spec, "agy:m-high")

    def test_think_effort_same_model(self):
        self.run_ask("gpt", tier="think")
        self.assertEqual(self.seen, [("x", "high")])
        self.seen.clear()
        self.run_ask("gpt")
        self.assertEqual(self.seen, [("x", "medium")])

    def test_disabled_think_model_ignored(self):
        self.cfg["disabled_models"] = ["agy:m-high"]
        self.assertEqual(self.g["think_setting"](self.cfg, "gemini")[0], "")

    def test_plan_prompt_mentions_kind(self):
        self.assertIn('"kind": "work"', self.g["PLAN_PROMPT"])
        self.assertNotIn("最多有", self.g["PLAN_PROMPT"])

    def test_design_and_copy_tiers(self):
        self.cfg["design"] = {"gemini": {"spec": "agy:m-flash", "effort": ""}}
        _, spec = self.run_ask("gemini", tier="design")
        self.assertEqual(spec, "agy:m-flash")
        _, spec = self.run_ask("gemini", tier="copy")
        self.assertEqual(spec, "agy:m-medium", "文案没设就跟干活一样")
        self.assertIn("审美用", self.g["tier_roster"](self.cfg, "gemini"))
        self.assertIn("design", self.g["PLAN_PROMPT"])

    def test_plan_prompt_allows_named_model(self):
        P = self.g["PLAN_PROMPT"]
        self.assertIn("{models}", P)
        self.assertIn("点名", P)

    def test_spec_label_families(self):
        L = self.g["spec_label"]
        self.assertEqual(L("agy:gemini-4-hydrogen-xhigh"), "Gemini Hydrogen·超高")
        self.assertEqual(L("agy:gemini-4-argon-low"), "Gemini Argon·低")

    def chat_call(self):
        got = {}

        class Stop(Exception):
            pass

        def fake_ask(cfg, agent, prompt, **kw):
            got.update(agent=agent, spec=kw.get("spec"), tier=kw.get("tier"))
            raise Stop()
        with patch.dict(self.g, {"ask": fake_ask}):
            try:
                self.g["run_chat"](self.cfg, "你好", cwd=self.home, contact="gemini")
            except Stop:
                pass
        return got

    def test_contact_model_tier(self):
        self.cfg["agents"]["gemini"] = ["agy:gemini-pro-orchestrator", "agy:gemini-4-carbon-medium"]
        self.assertEqual(self.chat_call(), {"agent": "gemini", "spec": "agy:gemini-4-carbon-medium", "tier": None}, "没设对接模型：照旧自动换轻模型")
        self.cfg["chat"] = {"gemini": {"spec": "agy:m-high", "effort": ""}}
        self.assertEqual(self.chat_call(), {"agent": "gemini", "spec": None, "tier": "chat"}, "设了对接模型：走对接档")
        _, spec = self.run_ask("gemini", tier="chat")
        self.assertEqual(spec, "agy:m-high")

    def test_chat_not_a_task_kind(self):
        self.assertIn("chat", self.g["TIERS"])
        self.assertNotIn("chat", self.g["TASK_TIERS"])
        self.cfg["chat"] = {"gemini": {"spec": "agy:m-high", "effort": ""}}
        self.assertNotIn("对接", self.g["tier_roster"](self.cfg, "gemini"))

    def test_chat_prompt_states_permission(self):
        P = self.g["CHAT_PROMPT"]
        self.assertIn("{perm_note}", P)
        self.assertIn("跑几条命令核查", P)


if __name__ == "__main__":
    unittest.main()

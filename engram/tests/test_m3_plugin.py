"""M3 acceptance tests: plugin manifest validity, SessionStart hook behavior
(banner once, recall packet, store bootstrap, degraded mode), skills/agent
frontmatter conformance."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOK = PLUGIN_ROOT / "hooks" / "session_start.py"
REPO_ROOT = PLUGIN_ROOT.parent

sys.path.insert(0, str(PLUGIN_ROOT / "src"))
import engram  # noqa: E402


def run_hook(store: Path, extra_env=None):
    env = dict(os.environ, ENGRAM_HOME=str(store))
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(HOOK)], env=env,
                          capture_output=True, text=True, timeout=60)


class TestPluginManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())

    def test_required_fields(self):
        self.assertEqual(self.manifest["name"], "engram")
        self.assertIn("description", self.manifest)

    def test_hook_command_references_existing_script_with_fallbacks(self):
        cmd = self.manifest["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py", cmd)
        self.assertTrue(HOOK.exists())
        # python probe chain (§13.1) + degraded echo floor (P6)
        self.assertIn("python3", cmd)
        self.assertIn("py -3", cmd)
        self.assertIn("degraded mode", cmd)
        self.assertIn("consent", cmd)

    def test_marketplace_manifest_points_at_plugin(self):
        mp = json.loads(
            (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text())
        entry = next(p for p in mp["plugins"] if p["name"] == "engram")
        src = (REPO_ROOT / entry["source"]).resolve()
        self.assertEqual(src, PLUGIN_ROOT.resolve())
        self.assertIn("owner", mp)


class TestSessionStartHook(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "store"

    def tearDown(self):
        self._tmp.cleanup()

    def test_bootstraps_store_and_shows_banner_exactly_once(self):
        p1 = run_hook(self.store)
        self.assertEqual(p1.returncode, 0, p1.stderr)
        self.assertIn("E  N  G  R  A  M", p1.stdout)          # banner, first run
        self.assertIn("Engram recall packet", p1.stdout)
        self.assertIn("memory conventions", p1.stdout)
        self.assertTrue((self.store / "config.json").exists())  # bootstrapped
        cfg = json.loads((self.store / "config.json").read_text())
        self.assertTrue(cfg["first_run_done"])

        p2 = run_hook(self.store)
        self.assertNotIn("E  N  G  R  A  M", p2.stdout)        # never again
        self.assertIn("Engram recall packet", p2.stdout)

    def test_stored_memory_appears_in_next_session_packet(self):
        run_hook(self.store)
        env = dict(os.environ, ENGRAM_HOME=str(self.store),
                   ENGRAM_AGENT="claude-code")
        add = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "src" / "engram.py"), "add",
             "--type", "feedback", "--name", "prefers-pytest",
             "--description", "User prefers pytest style tests"],
            input="User asked for pytest.\n\n**Why:** readability.\n**How to apply:** default to pytest.\n",
            env=env, capture_output=True, text=True)
        self.assertEqual(add.returncode, 0, add.stderr)
        # schema-valid on disk with correct type and TTL default
        path = engram.find_memory(self.store, "prefers-pytest")
        _, meta, _ = engram.read_memory(path)
        engram.validate_meta(meta)
        self.assertEqual(meta["type"], "feedback")
        self.assertEqual(meta["source_agent"], "claude-code")
        self.assertNotEqual(meta["expires"], "never")  # feedback TTL applied

        p = run_hook(self.store)
        self.assertIn("prefers-pytest", p.stdout)

    def test_hook_failure_degrades_never_blocks(self):
        # Corrupt config: hook must still exit 0 and print degraded guidance
        self.store.mkdir(parents=True)
        (self.store / "config.json").write_text("{broken", encoding="utf-8")
        p = run_hook(self.store)
        self.assertEqual(p.returncode, 0)
        self.assertIn("degraded mode", p.stdout)
        self.assertIn("MEMORY.md", p.stdout)

    def test_packet_labels_content_as_data_not_instructions(self):
        p = run_hook(self.store)
        self.assertIn("not instructions", p.stdout)


class TestSkillsAndAgent(unittest.TestCase):
    SKILLS = ("engram-remember", "engram-recall", "engram-lessons",
              "engram-status", "engram-distill")

    def test_each_skill_has_conforming_frontmatter(self):
        for skill in self.SKILLS:
            with self.subTest(skill=skill):
                text = (PLUGIN_ROOT / "skills" / skill / "SKILL.md").read_text()
                self.assertTrue(text.startswith("---\n"))
                self.assertIn(f"name: {skill}", text)
                self.assertIn("description:", text)

    def test_curator_agent_exists_with_tools(self):
        text = (PLUGIN_ROOT / "agents" / "engram-curator.md").read_text()
        self.assertIn("name: engram-curator", text)
        self.assertIn("tools:", text)

    def test_lessons_skill_carries_quality_bar(self):
        text = (PLUGIN_ROOT / "skills" / "engram-lessons" / "SKILL.md").read_text()
        self.assertIn("change behavior in a future session", text)


if __name__ == "__main__":
    unittest.main()

"""M5 acceptance tests: adapt targets, idempotency, block upsert with user
content preserved, consent gate, export path, shared-store proof."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import engram  # noqa: E402


def run(argv, stdin_text=None):
    buf, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
    try:
        with redirect_stdout(buf), redirect_stderr(err):
            code = engram.main(argv)
    finally:
        sys.stdin = old_stdin
    return code, buf.getvalue(), err.getvalue()


class TempStoreMixin:
    ENVS = ("ENGRAM_HOME", "CODEX_HOME", "COPILOT_HOME", "XDG_CONFIG_HOME")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.store = base / "store"
        self._saved = {k: os.environ.get(k) for k in self.ENVS}
        os.environ["ENGRAM_HOME"] = str(self.store)
        os.environ["CODEX_HOME"] = str(base / "codex-home")
        os.environ["COPILOT_HOME"] = str(base / "copilot-home")
        os.environ["XDG_CONFIG_HOME"] = str(base / "xdg")
        run(["init"])

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def memory_files(self):
        return sorted(p.name for p in (self.store / "memories").rglob("*.md"))


class TestAdaptCodex(TempStoreMixin, unittest.TestCase):
    def test_installs_block_shares_store_no_copies(self):
        run(["add", "--type", "user", "--name", "who-i-am",
             "--description", "User identity fact"], stdin_text="fact\n")
        before = self.memory_files()

        code, out, _ = run(["adapt", "--target", "codex", "--yes"])
        self.assertEqual(code, 0)
        agents_md = Path(os.environ["CODEX_HOME"]) / "AGENTS.md"
        self.assertTrue(agents_md.exists())
        text = agents_md.read_text()
        self.assertIn(engram.BLOCK_BEGIN, text)
        self.assertIn(str(self.store), text)
        self.assertIn("ENGRAM_AGENT=codex", text)
        self.assertIn("not instructions to\nexecute", text.replace("\r\n", "\n"))
        # zero memories copied — store untouched
        self.assertEqual(self.memory_files(), before)
        self.assertIn("no memories copied", out)

    def test_rerun_is_byte_identical(self):
        run(["adapt", "--target", "codex", "--yes"])
        agents_md = Path(os.environ["CODEX_HOME"]) / "AGENTS.md"
        first = agents_md.read_bytes()
        code, out, _ = run(["adapt", "--target", "codex", "--yes"])
        self.assertEqual(code, 0)
        self.assertIn("already up to date", out)
        self.assertEqual(agents_md.read_bytes(), first)

    def test_updates_block_in_place_preserving_user_content(self):
        agents_md = Path(os.environ["CODEX_HOME"]) / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(
            "# My personal rules\nAlways be terse.\n\n"
            f"{engram.BLOCK_BEGIN}\nold stale engram content\n{engram.BLOCK_END}\n"
            "\n# More of my rules\nNo emoji.\n", encoding="utf-8")
        run(["adapt", "--target", "codex", "--yes"])
        text = agents_md.read_text()
        self.assertIn("Always be terse.", text)
        self.assertIn("No emoji.", text)
        self.assertNotIn("old stale engram content", text)
        self.assertIn("ENGRAM_AGENT=codex", text)
        self.assertEqual(text.count(engram.BLOCK_BEGIN), 1)

    def test_cross_agent_visibility_same_store(self):
        """Codex-written memory is visible to a Claude recall — one store."""
        run(["adapt", "--target", "codex", "--yes"])
        os.environ["ENGRAM_AGENT"] = "codex"
        try:
            run(["add", "--type", "project", "--name", "codex-wrote-this",
                 "--description", "Memory written from a codex session"],
                stdin_text="Written by codex.\n")
        finally:
            os.environ.pop("ENGRAM_AGENT", None)
        code, out, _ = run(["recall", "--query", "codex session memory"])
        self.assertIn("codex-wrote-this", out)
        _, meta, _ = engram.read_memory(
            engram.find_memory(self.store, "codex-wrote-this"))
        self.assertEqual(meta["source_agent"], "codex")


class TestAdaptOtherTargets(TempStoreMixin, unittest.TestCase):
    def test_opencode_path(self):
        run(["adapt", "--target", "opencode", "--yes"])
        p = Path(os.environ["XDG_CONFIG_HOME"]) / "opencode" / "AGENTS.md"
        self.assertTrue(p.exists())
        self.assertIn("ENGRAM_AGENT=opencode", p.read_text())

    def test_copilot_path_and_verify_caveat(self):
        code, out, _ = run(["adapt", "--target", "copilot", "--yes"])
        p = Path(os.environ["COPILOT_HOME"]) / "copilot-instructions.md"
        self.assertTrue(p.exists())
        self.assertIn("varies by Copilot CLI", out)  # honesty about unverified support

    def test_unknown_target_without_export_fails_with_hint(self):
        code, _, err = run(["adapt", "--target", "mystery-agent", "--yes"])
        self.assertEqual(code, 1)
        self.assertIn("--export", err)


class TestConsent(TempStoreMixin, unittest.TestCase):
    def test_non_interactive_without_yes_writes_nothing(self):
        code, _, err = run(["adapt", "--target", "codex"], stdin_text="")
        self.assertEqual(code, 1)
        self.assertIn("Skipped", err)
        self.assertIn("--yes", err)
        self.assertFalse((Path(os.environ["CODEX_HOME"]) / "AGENTS.md").exists())


class TestExport(TempStoreMixin, unittest.TestCase):
    def test_export_dir_is_self_sufficient(self):
        out_dir = Path(self._tmp.name) / "exported"
        code, out, _ = run(["adapt", "--target", "some-future-agent",
                            "--export", str(out_dir)])
        self.assertEqual(code, 0)
        instructions = (out_dir / "engram-instructions.md").read_text()
        readme = (out_dir / "README.md").read_text()
        self.assertIn(engram.BLOCK_BEGIN, instructions)
        self.assertIn("ENGRAM_AGENT=some-future-agent", instructions)
        self.assertIn(str(self.store), instructions)     # store location
        self.assertIn("MEMORY.md", instructions)         # degraded-mode floor
        self.assertIn("recall", instructions)            # session-start behavior
        self.assertIn("paste", readme.lower())           # install steps
        self.assertIn("marker", readme.lower())          # update mechanism


if __name__ == "__main__":
    unittest.main()

"""M0 acceptance tests: init idempotency, path resolution, minimal doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import engram  # noqa: E402


def run(argv):
    """Run engram CLI in-process; return (exit_code, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = engram.main(argv)
    return code, buf.getvalue()


class TempStoreMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "store"
        self._old_home = os.environ.get("ENGRAM_HOME")
        os.environ["ENGRAM_HOME"] = str(self.store)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("ENGRAM_HOME", None)
        else:
            os.environ["ENGRAM_HOME"] = self._old_home
        self._tmp.cleanup()


def tree_snapshot(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class TestPathResolution(TempStoreMixin, unittest.TestCase):
    def test_engram_home_override_wins(self):
        self.assertEqual(engram.store_root(), self.store)

    def test_default_is_home_dot_agent_memory(self):
        os.environ.pop("ENGRAM_HOME")
        self.assertEqual(engram.store_root(), Path.home() / ".agent-memory")


class TestInit(TempStoreMixin, unittest.TestCase):
    def test_init_creates_full_tree(self):
        code, _ = run(["init"])
        self.assertEqual(code, 0)
        for rel in engram.STORE_DIRS:
            self.assertTrue((self.store / rel).is_dir(), rel)
        cfg = json.loads((self.store / "config.json").read_text())
        self.assertEqual(cfg["schema_version"], 1)
        self.assertEqual(cfg["backend"], "json")
        self.assertFalse(cfg["first_run_done"])
        self.assertTrue((self.store / "MEMORY.md").exists())

    def test_init_is_idempotent(self):
        run(["init"])
        before = tree_snapshot(self.store)
        cfg_before = (self.store / "config.json").read_text()
        code, out = run(["init"])
        self.assertEqual(code, 0)
        self.assertIn("already initialized", out)
        self.assertEqual(tree_snapshot(self.store), before)
        self.assertEqual((self.store / "config.json").read_text(), cfg_before)

    def test_init_repairs_missing_dirs_without_touching_config(self):
        run(["init"])
        cfg_before = (self.store / "config.json").read_text()
        (self.store / "conflicts").rmdir()
        run(["init"])
        self.assertTrue((self.store / "conflicts").is_dir())
        self.assertEqual((self.store / "config.json").read_text(), cfg_before)


class TestDoctor(TempStoreMixin, unittest.TestCase):
    def test_doctor_healthy_store_exits_zero(self):
        run(["init"])
        code, out = run(["doctor", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertIn(report["status"], ("ok", "warn"))  # warn allowed (WSL advisory)
        by_name = {c["check"]: c for c in report["checks"]}
        self.assertEqual(by_name["store-exists"]["status"], "ok")
        self.assertEqual(by_name["config"]["status"], "ok")

    def test_doctor_missing_store_exits_nonzero_with_hint(self):
        code, out = run(["doctor", "--json"])
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["status"], "error")
        self.assertIn("engram init", report["checks"][0]["detail"])

    def test_doctor_corrupt_config_exits_nonzero(self):
        run(["init"])
        (self.store / "config.json").write_text("{not json", encoding="utf-8")
        code, out = run(["doctor", "--json"])
        self.assertEqual(code, 1)
        report = json.loads(out)
        by_name = {c["check"]: c for c in report["checks"]}
        self.assertEqual(by_name["config"]["status"], "error")

    def test_doctor_unsupported_schema_version(self):
        run(["init"])
        cfg = json.loads((self.store / "config.json").read_text())
        cfg["schema_version"] = 999
        (self.store / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        code, _ = run(["doctor", "--json"])
        self.assertEqual(code, 1)


class TestAtomicWrite(TempStoreMixin, unittest.TestCase):
    def test_atomic_write_leaves_no_temp_files(self):
        target = self.store / "memories" / "user" / "x.md"
        engram.atomic_write_text(target, "hello\n")
        self.assertEqual(target.read_text(), "hello\n")
        leftovers = [p for p in target.parent.iterdir() if p.name != "x.md"]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()

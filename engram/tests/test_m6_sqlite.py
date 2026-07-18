"""M6 acceptance tests: JSON<->SQLite parity at 600 memories, both-direction
switching with markdown untouched, interface compliance for core ops,
scale suggestion thresholds, interrupted-switch safety, FTS-less fallback."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import engram  # noqa: E402

ENGRAM_PY = str(Path(__file__).resolve().parent.parent / "src" / "engram.py")

QUERIES = ["python testing", "kubernetes infra", "database migration",
           "react frontend", "auth security", "ci pipeline", "docker build",
           "api design", "logging observability", "package tooling"]
TOPICS = ["python testing", "kubernetes infra", "database migration",
          "react frontend", "auth security", "ci pipeline", "docker build",
          "api design", "logging observability", "package tooling"]


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


def plant_memories(store: Path, n: int):
    """Fabricate n schema-valid memories directly (fast bulk fixture)."""
    types = ["feedback", "user", "project", "reference", "lesson"]
    for i in range(n):
        mtype = types[i % len(types)]
        topic = TOPICS[i % len(TOPICS)]
        body = f"Fixture body {i} about {topic}.\n"
        meta = {
            "name": f"fix-{i:04d}",
            "description": f"Fixture {i}: {topic} note",
            "type": mtype,
            "created": "2026-07-01", "updated": "2026-07-01",
            "expires": "never" if mtype == "user" else "2027-07-01",
            "source_agent": "test",
            "tags": topic.split(),
            "hash": engram.body_hash(body),
        }
        if mtype == "lesson":
            meta["times_applied"] = i % 7
        p = engram.type_dir(store, mtype) / f"fix-{i:04d}.md"
        engram.atomic_write_text(p, engram.serialize_memory(meta, body))


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.md")):
        h.update(str(p.relative_to(root)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


class TempStoreMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "store"
        self._old_home = os.environ.get("ENGRAM_HOME")
        os.environ["ENGRAM_HOME"] = str(self.store)
        run(["init"])

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("ENGRAM_HOME", None)
        else:
            os.environ["ENGRAM_HOME"] = self._old_home
        self._tmp.cleanup()

    def backend_name(self):
        return json.loads((self.store / "config.json").read_text())["backend"]


class TestParityAndRoundTrip(TempStoreMixin, unittest.TestCase):
    def test_600_memory_round_trip_parity(self):
        plant_memories(self.store, 600)
        run(["reindex"])
        md_before = tree_hash(self.store / "memories")
        json_snapshot = (self.store / "index" / "index.json").read_text()
        json_results = {q: run(["recall", "--query", q])[1] for q in QUERIES}

        code, out, _ = run(["reindex", "--backend", "sqlite"])
        self.assertEqual(code, 0)
        self.assertIn("json -> sqlite", out)
        self.assertEqual(self.backend_name(), "sqlite")
        for q in QUERIES:
            self.assertEqual(run(["recall", "--query", q])[1], json_results[q],
                             f"sqlite recall diverged for query {q!r}")

        code, out, _ = run(["reindex", "--backend", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(self.backend_name(), "json")
        after = json.loads((self.store / "index" / "index.json").read_text())
        before = json.loads(json_snapshot)
        self.assertEqual(before["entries"], after["entries"])
        self.assertEqual(tree_hash(self.store / "memories"), md_before,
                         "markdown must be untouched through both switches")


class TestInterfaceCompliance(TempStoreMixin, unittest.TestCase):
    """Core mutating ops behave identically on the sqlite backend."""

    def setUp(self):
        super().setUp()
        run(["reindex", "--backend", "sqlite"])

    def test_add_edit_delete_lesson_journal_on_sqlite(self):
        code, _, err = run(["add", "--type", "lesson", "--name", "sq-lesson",
                            "--description", "Sqlite lesson", "--tags", "sq"],
                           stdin_text="**Mistake:** x\n**Why it happened:** y\n**How to apply:** z\n")
        self.assertEqual(code, 0, err)
        code, out, _ = run(["recall", "--query", "sqlite lesson"])
        self.assertIn("sq-lesson", out)

        run(["lesson", "applied", "sq-lesson"])
        be = engram.get_backend(self.store, engram.load_config(self.store))
        self.assertEqual(be.get("sq-lesson")["times_applied"], 1)

        code, _, _ = run(["journal", "--slug", "sq-day",
                          "--description", "Sqlite journal day"],
                         stdin_text="Did sqlite things.\n")
        self.assertEqual(code, 0)
        code, out, _ = run(["recall"])
        self.assertIn("sq-day", out)

        run(["delete", "sq-lesson"])
        self.assertIsNone(be.get("sq-lesson"))
        _, out, _ = run(["recall", "--query", "sqlite lesson"])
        self.assertNotIn("## sq-lesson", out)

    def test_drift_self_heal_on_sqlite(self):
        run(["add", "--type", "user", "--name", "sq-ghost",
             "--description", "Ghost on sqlite"], stdin_text="boo\n")
        engram.find_memory(self.store, "sq-ghost").unlink()
        code, out, _ = run(["recall", "--query", "ghost sqlite"])
        self.assertEqual(code, 0)
        self.assertNotIn("## sq-ghost", out)
        be = engram.get_backend(self.store, engram.load_config(self.store))
        self.assertIsNone(be.get("sq-ghost"))


class TestScaleSuggestion(TempStoreMixin, unittest.TestCase):
    def _scale_check(self):
        code, out, _ = run(["doctor", "--json"])
        return {c["check"]: c for c in json.loads(out)["checks"]}.get("index-scale")

    def test_suggests_at_501_not_below(self):
        plant_memories(self.store, 200)
        run(["reindex"])
        check = self._scale_check()
        # below threshold: must not warn on count (timing warns only on slow disks)
        if check["status"] == "warn":
            self.assertNotIn("501", check["detail"])
        plant_memories(self.store, 600)  # overwrites first 200, total 600
        run(["reindex"])
        check = self._scale_check()
        self.assertEqual(check["status"], "warn")
        self.assertIn("consent", check["detail"])
        self.assertIn("reindex --backend sqlite", check["detail"])

    def test_no_suggestion_once_on_sqlite(self):
        plant_memories(self.store, 600)
        run(["reindex", "--backend", "sqlite"])
        self.assertIsNone(self._scale_check())  # check only runs on json backend


class TestInterruptedSwitch(TempStoreMixin, unittest.TestCase):
    def test_crash_mid_switch_leaves_old_backend_active(self):
        plant_memories(self.store, 20)
        run(["reindex"])
        env = dict(os.environ, ENGRAM_TEST_CRASH_BEFORE_REPLACE="1")
        proc = subprocess.run(
            [sys.executable, ENGRAM_PY, "reindex", "--backend", "sqlite"],
            env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 9)
        self.assertEqual(self.backend_name(), "json",
                         "config must not flip if the rebuild did not complete")
        code, out, _ = run(["recall", "--query", "python testing"])
        self.assertEqual(code, 0)  # old backend fully functional
        self.assertIn("fix-", out)


class TestFtsFallback(TempStoreMixin, unittest.TestCase):
    def test_no_fts_full_scan_parity(self):
        plant_memories(self.store, 100)
        run(["reindex"])
        with_fts = {q: run(["recall", "--query", q])[1] for q in QUERIES[:3]}
        run(["reindex", "--backend", "sqlite"])
        os.environ["ENGRAM_TEST_NO_FTS"] = "1"
        try:
            for q in QUERIES[:3]:
                self.assertEqual(run(["recall", "--query", q])[1], with_fts[q])
        finally:
            os.environ.pop("ENGRAM_TEST_NO_FTS", None)


if __name__ == "__main__":
    unittest.main()

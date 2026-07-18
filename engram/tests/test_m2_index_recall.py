"""M2 acceptance tests: lossless rebuild, recall relevance + budget,
ranking (times_applied), drift self-heal, MEMORY.md generation."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import engram  # noqa: E402


def run(argv):
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        code = engram.main(argv)
    return code, buf.getvalue(), err.getvalue()


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

    def add(self, name, mtype="feedback", body=None, description=None, tags=None):
        body = body or f"Body of {name}.\n"
        description = description or f"Description of {name}"
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(body)
            bf = f.name
        argv = ["add", "--type", mtype, "--name", name,
                "--description", description, "--body-file", bf]
        if tags:
            argv += ["--tags", tags]
        result = run(argv)
        os.unlink(bf)
        return result

    def index_data(self):
        return json.loads((self.store / "index" / "index.json").read_text())


class TestLosslessRebuild(TempStoreMixin, unittest.TestCase):
    def test_delete_index_then_reindex_restores_identical_entries(self):
        for i in range(30):
            mtype = ("feedback", "user", "project", "reference", "lesson")[i % 5]
            self.add(f"mem-{i:02d}", mtype=mtype, tags="alpha,beta")
        before = self.index_data()["entries"]
        (self.store / "index" / "index.json").unlink()
        code, out, _ = run(["reindex"])
        self.assertEqual(code, 0)
        self.assertIn("30 active", out)
        after = self.index_data()["entries"]
        self.assertEqual(before, after)

    def test_incremental_updates_match_full_rebuild(self):
        self.add("one")
        self.add("two", mtype="lesson")
        run(["delete", "one"])
        run(["pin", "two"])
        incremental = self.index_data()["entries"]
        run(["reindex"])
        rebuilt = self.index_data()["entries"]
        self.assertEqual(incremental, rebuilt)


class TestRecall(TempStoreMixin, unittest.TestCase):
    def _populate_topics(self):
        self.add("pytest-style", description="User prefers pytest over unittest",
                 tags="python,testing")
        self.add("fixture-naming", description="Python testing fixtures naming rule",
                 tags="python,testing")
        self.add("k8s-cluster", description="Kubernetes cluster reference",
                 mtype="reference", tags="kubernetes,infra")
        self.add("coffee-pref", description="User drinks too much coffee",
                 mtype="user", tags="personal")

    def test_query_matches_ranked_above_and_excludes_unrelated(self):
        self._populate_topics()
        code, out, _ = run(["recall", "--query", "python testing"])
        self.assertEqual(code, 0)
        self.assertIn("pytest-style", out)
        self.assertIn("fixture-naming", out)
        self.assertNotIn("k8s-cluster", out)  # zero-overlap entries drop out

    def test_recall_excludes_expired_and_archived(self):
        self._populate_topics()
        run(["delete", "coffee-pref"])
        path = engram.find_memory(self.store, "k8s-cluster")
        _, meta, body = engram.read_memory(path)
        meta["expires"] = (date.today() - timedelta(days=1)).isoformat()
        engram.atomic_write_text(path, engram.serialize_memory(meta, body))
        code, out, _ = run(["recall"])
        self.assertNotIn("coffee", out)
        self.assertNotIn("k8s-cluster", out)

    def test_budget_enforced_with_stubs(self):
        for i in range(30):
            self.add(f"bulk-{i:02d}", body=("filler line for token mass\n" * 8),
                     tags="common,topic")
        code, out, _ = run(["recall", "--query", "common topic", "--budget", "100"])
        self.assertEqual(code, 0)
        self.assertLessEqual(engram.estimate_tokens(out), 100)
        self.assertIn("Not loaded (over budget)", out)
        self.assertIn("engram show", out)

    def test_times_applied_outranks_equal_match(self):
        self.add("lesson-proven", mtype="lesson",
                 description="Check lockfile before package commands", tags="tooling")
        self.add("lesson-fresh", mtype="lesson",
                 description="Check node version before package commands", tags="tooling")
        path = engram.find_memory(self.store, "lesson-proven")
        _, meta, body = engram.read_memory(path)
        meta["times_applied"] = 5
        engram.atomic_write_text(path, engram.serialize_memory(meta, body))
        run(["reindex"])
        entries = engram.get_backend(self.store, engram.load_config(self.store)).query()
        ranked = engram.rank_entries(entries, "package commands")
        names = [e["name"] for e in ranked]
        self.assertLess(names.index("lesson-proven"), names.index("lesson-fresh"))

    def test_review_queue_lists_expiring_max_three(self):
        for i in range(5):
            self.add(f"soon-{i}")
            run(["expire", f"soon-{i}", "--in", "5d"])
        code, out, _ = run(["recall"])
        self.assertIn("Expiring soon", out)
        self.assertEqual(out.count("expires " + (date.today() + timedelta(days=5)).isoformat()), 3)


class TestDriftSelfHeal(TempStoreMixin, unittest.TestCase):
    def test_hand_deleted_file_heals_on_recall(self):
        self.add("ghost", tags="haunt")
        self.add("solid", tags="haunt")
        engram.find_memory(self.store, "ghost").unlink()
        code, out, _ = run(["recall", "--query", "haunt"])
        self.assertEqual(code, 0)
        self.assertNotIn("## ghost", out)
        self.assertIn("solid", out)
        names = [e["name"] for e in self.index_data()["entries"]]
        self.assertNotIn("ghost", names)

    def test_corrupt_index_heals_on_use(self):
        self.add("survivor")
        (self.store / "index" / "index.json").write_text("{broken", encoding="utf-8")
        code, out, _ = run(["list"])
        self.assertEqual(code, 0)
        self.assertIn("survivor", out)


class TestMemoryMd(TempStoreMixin, unittest.TestCase):
    def test_grouped_by_type_one_line_each_valid_links(self):
        self.add("fact-a", mtype="user", description="A user fact")
        self.add("fact-b", mtype="lesson", description="A lesson learned")
        md = (self.store / "MEMORY.md").read_text()
        self.assertIn("## user", md)
        self.assertIn("## lesson", md)
        self.assertIn("- [A user fact](memories/user/fact-a.md)", md)
        self.assertIn("- [A lesson learned](lessons/fact-b.md)", md)
        for line in md.splitlines():
            if line.startswith("- ["):
                rel = line[line.index("](") + 2:-1]
                self.assertTrue((self.store / rel).exists(), rel)

    def test_delete_removes_line(self):
        self.add("temp-fact", description="Temporary")
        run(["delete", "temp-fact"])
        self.assertNotIn("temp-fact", (self.store / "MEMORY.md").read_text())


class TestListFilters(TempStoreMixin, unittest.TestCase):
    def test_type_and_expiring_and_archived_filters(self):
        self.add("keep-user", mtype="user")
        self.add("keep-lesson", mtype="lesson")
        self.add("going", mtype="feedback")
        run(["expire", "going", "--in", "3d"])
        run(["delete", "keep-user"])

        _, out, _ = run(["list", "--type", "lesson"])
        self.assertIn("keep-lesson", out)
        self.assertNotIn("going", out)

        _, out, _ = run(["list", "--expiring"])
        self.assertIn("going", out)
        self.assertNotIn("keep-lesson", out)

        _, out, _ = run(["list", "--archived"])
        self.assertIn("keep-user", out)
        self.assertNotIn("going", out)


if __name__ == "__main__":
    unittest.main()

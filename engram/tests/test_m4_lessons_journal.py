"""M4 acceptance tests: lesson loop end-to-end, concurrent reinforcement,
journal entry placement, rollup lifecycle."""

import io
import json
import multiprocessing
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, timedelta
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

    def add_lesson(self, name, description, tags="tooling"):
        body = ("**Mistake:** ran npm in a pnpm workspace.\n"
                "**Why it happened:** assumed default tooling.\n"
                "**How to apply:** check lockfile type before package commands.\n")
        return run(["add", "--type", "lesson", "--name", name,
                    "--description", description, "--tags", tags],
                   stdin_text=body)


class TestLessonLoop(TempStoreMixin, unittest.TestCase):
    def test_end_to_end_capture_recall_apply_rerank(self):
        code, _, err = self.add_lesson(
            "check-lockfile-first", "Check lockfile type before package commands")
        self.assertEqual(code, 0, err)
        path = engram.find_memory(self.store, "check-lockfile-first")
        _, meta, body = engram.read_memory(path)
        self.assertEqual(meta["times_applied"], 0)
        self.assertIn("**How to apply:**", body)

        # surfaces for a matching query
        code, out, _ = run(["recall", "--query", "package lockfile"])
        self.assertIn("check-lockfile-first", out)

        # applying bumps counter, stamps last_applied, extends expiry
        old_expires = meta["expires"]
        code, out, _ = run(["lesson", "applied", "check-lockfile-first"])
        self.assertEqual(code, 0)
        _, meta, _ = engram.read_memory(path)
        self.assertEqual(meta["times_applied"], 1)
        self.assertEqual(meta["last_applied"], date.today().isoformat())
        self.assertGreaterEqual(meta["expires"], old_expires)

        # outranks an equally matching unapplied peer
        self.add_lesson("check-node-version",
                        "Check node version before package commands")
        for _ in range(4):
            run(["lesson", "applied", "check-lockfile-first"])
        entries = engram.get_backend(self.store, engram.load_config(self.store)).query()
        ranked = engram.rank_entries(entries, "package commands")
        names = [e["name"] for e in ranked]
        self.assertLess(names.index("check-lockfile-first"),
                        names.index("check-node-version"))

    def test_applied_on_non_lesson_rejected(self):
        run(["add", "--type", "user", "--name", "not-a-lesson",
             "--description", "plain fact"], stdin_text="fact\n")
        code, _, err = run(["lesson", "applied", "not-a-lesson"])
        self.assertEqual(code, 1)
        self.assertIn("not a lesson", err)


def _applied_worker(store, n, out_queue):
    os.environ["ENGRAM_HOME"] = store
    ok = 0
    for _ in range(n):
        try:
            engram.cas_update_retry(
                engram.store_root(), "contended-lesson",
                lambda meta, body: (
                    {**meta,
                     "times_applied": int(meta.get("times_applied", 0)) + 1,
                     "last_applied": engram.today()},
                    body),
                "worker")
            ok += 1
        except engram.ConflictError:
            pass
    out_queue.put(ok)


class TestConcurrentReinforcement(TempStoreMixin, unittest.TestCase):
    def test_parallel_applied_never_loses_an_increment(self):
        self.add_lesson("contended-lesson", "Contended lesson for the race test")
        n = 25
        q = multiprocessing.Queue()
        procs = [multiprocessing.Process(target=_applied_worker,
                                         args=(str(self.store), n, q))
                 for _ in range(2)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)
            self.assertEqual(p.exitcode, 0)
        total_ok = q.get() + q.get()
        _, meta, _ = engram.read_memory(
            engram.find_memory(self.store, "contended-lesson"))
        self.assertEqual(meta["times_applied"], total_ok,
                         "every successful applied-call must be counted exactly once")
        self.assertEqual(total_ok, 2 * n, "with retries, all attempts should land")


class TestJournal(TempStoreMixin, unittest.TestCase):
    def test_entry_lands_at_dated_path_with_journal_ttl(self):
        code, out, err = run(["journal", "--slug", "engram-build",
                              "--description", "Built M4 of Engram"],
                             stdin_text="Implemented lessons and journal.\nNext: adapters.\n")
        self.assertEqual(code, 0, err)
        d = date.today()
        expect = (self.store / "journal" / f"{d.year:04d}" /
                  f"{d.year:04d}-{d.month:02d}" / f"{d.isoformat()}-engram-build.md")
        self.assertTrue(expect.exists())
        _, meta, _ = engram.read_memory(expect)
        self.assertEqual(meta["type"], "journal")
        self.assertEqual(meta["expires"],
                         (d + timedelta(days=90)).isoformat())

    def test_latest_entries_in_recall_packet(self):
        run(["journal", "--slug", "first-session",
             "--description", "First session summary"],
            stdin_text="Did the first thing.\n")
        code, out, _ = run(["recall"])
        self.assertIn("journal:", out)
        self.assertIn("first-session", out)

    def test_description_required_with_slug(self):
        code, _, err = run(["journal", "--slug", "x"], stdin_text="body\n")
        self.assertEqual(code, 1)
        self.assertIn("--description", err)


class TestRollup(TempStoreMixin, unittest.TestCase):
    MONTH = "2026-06"  # a completed month relative to frozen store dates

    def _plant_past_entry(self, day, slug, description):
        name = f"{self.MONTH}-{day:02d}-{slug}"
        meta = {
            "name": name, "description": description, "type": "journal",
            "created": f"{self.MONTH}-{day:02d}", "updated": f"{self.MONTH}-{day:02d}",
            "expires": (date.today() - timedelta(days=1)).isoformat(),  # already aged
            "source_agent": "test", "hash": engram.body_hash("body\n"),
        }
        p = (self.store / "journal" / "2026" / self.MONTH / f"{name}.md")
        engram.atomic_write_text(p, engram.serialize_memory(meta, "body\n"))
        return p

    def test_rollup_lifecycle(self):
        for day, slug in ((3, "auth-flow"), (12, "rate-limit"), (25, "cleanup")):
            self._plant_past_entry(day, slug, f"Worked on {slug}")
        run(["reindex"])

        # doctor flags the completed month
        code, out, _ = run(["doctor", "--json"])
        report = json.loads(out)
        by = {c["check"]: c for c in report["checks"]}
        self.assertEqual(by["journal-rollups"]["status"], "warn")
        self.assertIn(self.MONTH, by["journal-rollups"]["detail"])

        # rollup covers all entries; doctor stops flagging
        code, out, _ = run(["journal", "--rollup", self.MONTH])
        self.assertEqual(code, 0)
        rollup = self.store / "journal" / "2026" / f"{self.MONTH}-rollup.md"
        self.assertTrue(rollup.exists())
        _, meta, body = engram.read_memory(rollup)
        for slug in ("auth-flow", "rate-limit", "cleanup"):
            self.assertIn(slug, body)
        code, out, _ = run(["doctor", "--json"])
        by = {c["check"]: c for c in json.loads(out)["checks"]}
        self.assertEqual(by["journal-rollups"]["status"], "ok")

        # aged daily entries sweep to archive; rollup survives
        swept = engram.sweep_expired(self.store)
        self.assertEqual(len(swept), 3)
        self.assertTrue(rollup.exists())
        self.assertEqual(len(list((self.store / "archive").glob(f"{self.MONTH}-*.md"))), 3)

    def test_duplicate_rollup_rejected(self):
        self._plant_past_entry(3, "only", "Only entry")
        run(["journal", "--rollup", self.MONTH])
        code, _, err = run(["journal", "--rollup", self.MONTH])
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)


if __name__ == "__main__":
    unittest.main()

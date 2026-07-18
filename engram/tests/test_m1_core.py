"""M1 acceptance tests: format round-trip, hashing, CAS concurrency,
crash safety, secret deny-patterns, expiry lifecycle, strict parser."""

import io
import json
import multiprocessing
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

    def add(self, name="test-memory", mtype="feedback", body="Fact line.\n",
            description="A test memory", extra=None):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(body)
            bf = f.name
        argv = ["add", "--type", mtype, "--name", name,
                "--description", description, "--body-file", bf]
        if extra:
            argv += extra
        result = run(argv)
        os.unlink(bf)
        return result


class TestRoundTrip(TempStoreMixin, unittest.TestCase):
    def test_add_show_round_trip_body_exact(self):
        body = "Line one.\n\n**Why:** because.\n**How to apply:** do it.\n"
        code, _, err = self.add(body=body)
        self.assertEqual(code, 0, err)
        code, out, _ = run(["show", "test-memory"])
        self.assertEqual(code, 0)
        meta, parsed_body = engram.parse_memory_text(out)
        self.assertEqual(parsed_body, body)
        self.assertEqual(meta["name"], "test-memory")
        self.assertEqual(meta["type"], "feedback")
        self.assertEqual(meta["hash"], engram.body_hash(body))
        # feedback TTL default: 365d from config
        expected = (date.today() + timedelta(days=365)).isoformat()
        self.assertEqual(meta["expires"], expected)

    def test_duplicate_add_rejected_with_edit_hint(self):
        self.add()
        code, _, err = self.add()
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertIn("engram edit", err)

    def test_tags_and_links_round_trip(self):
        self.add(extra=["--tags", "python,testing", "--links", "other-memory"])
        _, out, _ = run(["show", "test-memory"])
        meta, _ = engram.parse_memory_text(out)
        self.assertEqual(meta["tags"], ["python", "testing"])
        self.assertEqual(meta["links"], ["other-memory"])


class TestHashing(TempStoreMixin, unittest.TestCase):
    def test_crlf_and_lf_hash_identically(self):
        lf = "line one\nline two\n"
        crlf = "line one\r\nline two\r\n"
        self.assertEqual(engram.body_hash(lf), engram.body_hash(crlf))

    def test_trailing_whitespace_normalized(self):
        self.assertEqual(engram.body_hash("x\n"), engram.body_hash("x   \n\n\n"))

    def test_hash_is_16_hex(self):
        h = engram.body_hash("content")
        self.assertRegex(h, r"^[0-9a-f]{16}$")


def _cas_worker(store, worker_id, attempts, out_queue):
    os.environ["ENGRAM_HOME"] = store
    os.environ["ENGRAM_AGENT"] = f"worker{worker_id}"
    successes = 0
    for i in range(attempts):
        def mutate(meta, body, wid=worker_id, n=i):
            return meta, body + f"edit w{wid} n{n}\n"
        try:
            engram.cas_update(engram.store_root(), "contended", mutate,
                              f"worker{worker_id}")
            successes += 1
        except engram.ConflictError:
            pass
    out_queue.put(successes)


class TestConcurrency(TempStoreMixin, unittest.TestCase):
    def test_parallel_cas_no_data_loss(self):
        """AC: 2 processes x 50 CAS edits; every write survives either in the
        memory file (success) or in conflicts/ (loser). Zero silent loss."""
        self.add(name="contended", body="base\n")
        attempts = 50
        q = multiprocessing.Queue()
        procs = [multiprocessing.Process(target=_cas_worker,
                                         args=(str(self.store), w, attempts, q))
                 for w in (1, 2)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)
            self.assertEqual(p.exitcode, 0)
        successes = q.get() + q.get()
        conflicts = list((self.store / "conflicts").glob("contended.*.md"))
        self.assertEqual(successes + len(conflicts), attempts * 2,
                         "every attempt must be a success or a preserved conflict")
        self.assertGreater(successes, 0)
        # final file is valid, not torn
        _, meta, body = engram.read_memory(engram.find_memory(self.store, "contended"))
        self.assertEqual(meta["hash"], engram.body_hash(body))
        # every conflict file is itself a valid memory
        for c in conflicts:
            engram.read_memory(c)


class TestCrashSafety(TempStoreMixin, unittest.TestCase):
    def test_crash_between_temp_and_replace_leaves_old_version(self):
        self.add(name="crash-target", body="original body\n")
        path = engram.find_memory(self.store, "crash-target")
        before = path.read_text()
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("new body that must not land\n")
            bf = f.name
        env = dict(os.environ, ENGRAM_TEST_CRASH_BEFORE_REPLACE="1")
        proc = subprocess.run(
            [sys.executable, ENGRAM_PY, "edit", "crash-target", "--body-file", bf],
            env=env, capture_output=True, text=True)
        os.unlink(bf)
        self.assertEqual(proc.returncode, 9)
        after = path.read_text()
        self.assertEqual(after, before, "target must be the old version, never partial")
        engram.read_memory(path)  # still parses


class TestSecretDenyPatterns(TempStoreMixin, unittest.TestCase):
    # Fixtures are concatenated at runtime so no secret-shaped literal exists
    # in this file — otherwise GitHub push protection (correctly) blocks the
    # repo push. The joined strings still match engram's deny-patterns.
    SAMPLES = {
        "api key (sk-...)": "my key is " + "sk-" + "abc123def456ghi789jkl",
        "GitHub token": "token " + "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWX12345678",
        "AWS access key": "AKIA" + "IOSFODNN7EXAMPLE",
        "Slack token": "xox" + "b-123456789012-abcdefghijklmnop",
        "JWT": "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N",
        "private key block": "-----BEGIN RSA " + "PRIVATE KEY-----",
        "credential in URL": "postgres://admin:hunter2" + "@db.example.com/prod",
        "password assignment": "password" + " = hunter2",
    }

    def test_each_category_rejected_and_named(self):
        for label, sample in self.SAMPLES.items():
            with self.subTest(label=label):
                code, _, err = self.add(name=f"secret-{abs(hash(label)) % 10000}",
                                        body=sample + "\n")
                self.assertEqual(code, 1, f"{label} should be rejected")
                self.assertIn(label, err)

    def test_clean_body_passes(self):
        code, _, err = self.add(name="clean", body="User prefers dark mode.\n")
        self.assertEqual(code, 0, err)


class TestLifecycle(TempStoreMixin, unittest.TestCase):
    def _force_expiry(self, name, iso_date):
        path = engram.find_memory(self.store, name)
        _, meta, body = engram.read_memory(path)
        meta["expires"] = iso_date
        engram.atomic_write_text(path, engram.serialize_memory(meta, body))

    def test_expired_memory_swept_to_archive_with_stamp(self):
        self.add(name="stale")
        self._force_expiry("stale", (date.today() - timedelta(days=1)).isoformat())
        swept = engram.sweep_expired(self.store)
        self.assertEqual(len(swept), 1)
        self.assertTrue(swept[0].parent.name == "archive")
        _, meta, _ = engram.read_memory(swept[0])
        self.assertEqual(meta["archived"], date.today().isoformat())
        with self.assertRaises(engram.EngramError):
            engram.find_memory(self.store, "stale")

    def test_pin_sets_never_and_survives_sweep(self):
        self.add(name="keeper")
        code, _, _ = run(["pin", "keeper"])
        self.assertEqual(code, 0)
        _, meta, _ = engram.read_memory(engram.find_memory(self.store, "keeper"))
        self.assertEqual(meta["expires"], "never")
        self.assertEqual(engram.sweep_expired(self.store), [])

    def test_expire_in_days(self):
        self.add(name="short-lived")
        code, _, _ = run(["expire", "short-lived", "--in", "30d"])
        self.assertEqual(code, 0)
        _, meta, _ = engram.read_memory(engram.find_memory(self.store, "short-lived"))
        self.assertEqual(meta["expires"], (date.today() + timedelta(days=30)).isoformat())

    def test_delete_archives_and_purge_removes(self):
        self.add(name="doomed")
        code, _, _ = run(["delete", "doomed"])
        self.assertEqual(code, 0)
        archived = list((self.store / "archive").glob("doomed*.md"))
        self.assertEqual(len(archived), 1)
        # purge with 0d cutoff won't touch today's archive (archived today is not < today)
        code, out, _ = run(["purge", "--older-than", "0d", "--yes"])
        self.assertIn("Nothing", out)
        # backdate the archive stamp, then purge
        _, meta, body = engram.read_memory(archived[0])
        meta["archived"] = (date.today() - timedelta(days=100)).isoformat()
        engram.atomic_write_text(archived[0], engram.serialize_memory(meta, body))
        code, out, _ = run(["purge", "--older-than", "90d", "--yes"])
        self.assertEqual(code, 0)
        self.assertEqual(list((self.store / "archive").glob("doomed*.md")), [])

    def test_doctor_fix_restamps_hand_edited_hash(self):
        self.add(name="hand-edited", body="original\n")
        path = engram.find_memory(self.store, "hand-edited")
        text = path.read_text().replace("original", "hand edit")
        path.write_text(text, encoding="utf-8")
        code, out, _ = run(["doctor", "--fix", "--json"])
        report = json.loads(out)
        self.assertTrue(any("re-stamped hash" in f for f in report["fixes"]))
        _, meta, body = engram.read_memory(path)
        self.assertEqual(meta["hash"], engram.body_hash(body))


class TestStrictParser(TempStoreMixin, unittest.TestCase):
    def test_nested_yaml_rejected_not_guessed(self):
        bad = ("---\n"
               "name: nested-file\n"
               "description: nested structures are out of subset\n"
               "type: user\n"
               "metadata:\n"
               "  inner: value\n"
               "---\n\nbody\n")
        with self.assertRaises(engram.FrontmatterError) as ctx:
            engram.parse_memory_text(bad, origin="bad.md")
        self.assertIn("subset", str(ctx.exception))

    def test_block_list_rejected(self):
        bad = ("---\nname: x\ntags:\n- a\n---\n\nbody\n")
        with self.assertRaises(engram.FrontmatterError):
            engram.parse_memory_text(bad, origin="bad.md")

    def test_duplicate_key_rejected(self):
        bad = ("---\nname: x\nname: y\n---\n\nbody\n")
        with self.assertRaises(engram.FrontmatterError):
            engram.parse_memory_text(bad, origin="bad.md")

    def test_description_over_120_rejected(self):
        code, _, err = self.add(description="x" * 121)
        self.assertEqual(code, 1)
        self.assertIn("120", err)

    def test_bad_name_rejected(self):
        code, _, err = self.add(name="Bad_Name")
        self.assertEqual(code, 1)
        self.assertIn("kebab-case", err)


if __name__ == "__main__":
    unittest.main()

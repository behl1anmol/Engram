"""M7 acceptance tests: full doctor on a broken store + --fix, shims,
PATH-stripped degraded behavior, cloud-sync and conflicts advisories."""

import io
import json
import os
import stat
import subprocess
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

    def add(self, name, mtype="feedback", body="Fact.\n", description=None):
        return run(["add", "--type", mtype, "--name", name,
                    "--description", description or f"Description of {name}"],
                   stdin_text=body)

    def doctor(self, fix=False):
        argv = ["doctor", "--json"] + (["--fix"] if fix else [])
        code, out, _ = run(argv)
        report = json.loads(out)
        return code, report, {c["check"]: c for c in report["checks"]}


class TestBrokenStoreDoctor(TempStoreMixin, unittest.TestCase):
    def _break_everything(self):
        # 1. hash drift (hand edit)
        self.add("drifted")
        p = engram.find_memory(self.store, "drifted")
        p.write_text(p.read_text().replace("Fact.", "Hand-edited fact."),
                     encoding="utf-8")
        # 2. expired memory
        self.add("expired-one")
        p2 = engram.find_memory(self.store, "expired-one")
        _, meta, body = engram.read_memory(p2)
        meta["expires"] = (date.today() - timedelta(days=2)).isoformat()
        engram.atomic_write_text(p2, engram.serialize_memory(meta, body))
        # 3. unparseable file
        bad = self.store / "memories" / "user" / "broken-file.md"
        bad.write_text("---\nname: broken-file\nmeta:\n  nested: x\n---\n\nbody\n",
                       encoding="utf-8")
        # 4. index orphan (file removed behind the index's back)
        self.add("ghost-entry")
        engram.find_memory(self.store, "ghost-entry").unlink()
        # 5. missing rollup for a completed month
        m = self.store / "journal" / "2026" / "2026-05" / "2026-05-10-old-work.md"
        meta = {"name": "2026-05-10-old-work", "description": "Old month entry",
                "type": "journal", "created": "2026-05-10", "updated": "2026-05-10",
                "expires": "never", "source_agent": "test",
                "hash": engram.body_hash("old\n")}
        engram.atomic_write_text(m, engram.serialize_memory(meta, "old\n"))

    def test_reports_every_defect_then_fix_resolves(self):
        self._break_everything()
        code, report, by = self.doctor()
        self.assertEqual(by["hash-drift"]["status"], "warn")
        self.assertIn("drifted", by["hash-drift"]["detail"])
        self.assertEqual(by["expired"]["status"], "warn")
        self.assertEqual(by["memory-schema"]["status"], "warn")
        self.assertIn("broken-file", by["memory-schema"]["detail"])
        self.assertEqual(by["index-bijection"]["status"], "warn")
        self.assertIn("ghost-entry", by["index-bijection"]["detail"])
        self.assertEqual(by["journal-rollups"]["status"], "warn")
        self.assertIn("2026-05", by["journal-rollups"]["detail"])

        code, report, by = self.doctor(fix=True)
        fixes = report["fixes"]
        self.assertTrue(any("re-stamped" in f for f in fixes))
        self.assertTrue(any("archived expired" in f for f in fixes))
        self.assertTrue(any("quarantined" in f for f in fixes))
        self.assertTrue(any("index rebuilt" in f for f in fixes))
        # re-report: fixable defects gone; rollup gap remains (needs narrative,
        # not a mechanical fix) and quarantine surfaces via conflicts warn
        code, report, by = self.doctor()
        self.assertEqual(by["hash-drift"]["status"], "ok")
        self.assertEqual(by["expired"]["status"], "ok")
        self.assertEqual(by["memory-schema"]["status"], "ok")
        self.assertEqual(by["index-bijection"]["status"], "ok")
        self.assertEqual(by["conflicts"]["status"], "warn")  # quarantined file preserved
        quarantined = list((self.store / "conflicts").glob("broken-file.unparseable*.md"))
        self.assertEqual(len(quarantined), 1)


class TestAdvisories(TempStoreMixin, unittest.TestCase):
    def test_conflict_files_surface_as_warning(self):
        (self.store / "conflicts" / "x.20260718.1.agent.md").write_text(
            "conflict body", encoding="utf-8")
        _, _, by = self.doctor()
        self.assertEqual(by["conflicts"]["status"], "warn")
        self.assertIn("lost a race", by["conflicts"]["detail"])

    def test_cloud_sync_path_warns(self):
        cloud = Path(self._tmp.name) / "Dropbox" / "store"
        os.environ["ENGRAM_HOME"] = str(cloud)
        run(["init"])
        _, _, by = self.doctor()
        self.assertEqual(by["cloud-sync"]["status"], "warn")
        self.assertIn("conscious", by["cloud-sync"]["detail"])


class TestShims(TempStoreMixin, unittest.TestCase):
    def test_init_generates_both_shims(self):
        sh = self.store / "bin" / "engram"
        cmd = self.store / "bin" / "engram.cmd"
        self.assertTrue(sh.exists())
        self.assertTrue(cmd.exists())
        self.assertIn(str(Path(engram.__file__).resolve()), sh.read_text())
        self.assertIn("py -3", cmd.read_text())
        if os.name == "posix":
            self.assertTrue(sh.stat().st_mode & stat.S_IXUSR)

    def test_posix_shim_runs_doctor(self):
        sh = self.store / "bin" / "engram"
        proc = subprocess.run(["sh", str(sh), "doctor", "--json"],
                              env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"status"', proc.stdout)

    def test_path_stripped_shim_degrades_with_guidance(self):
        sh = self.store / "bin" / "engram"
        env = dict(os.environ, PATH="/nonexistent")
        proc = subprocess.run(["/bin/sh", str(sh), "doctor"], env=env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Python 3 not found", proc.stderr)
        self.assertIn("MEMORY.md", proc.stderr)   # degraded-mode pointer
        self.assertIn("consent", proc.stderr)


if __name__ == "__main__":
    unittest.main()

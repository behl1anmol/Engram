"""M8 enhancement tests: protected (readonly-for-agents) memories and
variable-duration expiry (§6.6, amended §6.2)."""

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

    def add(self, name, mtype="user", body="Fact.\n", description=None):
        return run(["add", "--type", mtype, "--name", name,
                    "--description", description or f"Description of {name}"],
                   stdin_text=body)

    def meta(self, name):
        _, m, _ = engram.read_memory(engram.find_memory(self.store, name))
        return m


class TestProtect(TempStoreMixin, unittest.TestCase):
    def test_protect_sets_flag_and_auto_pins(self):
        self.add("users-name", description="User's name is Anmol")
        code, out, _ = run(["protect", "users-name"])
        self.assertEqual(code, 0)
        m = self.meta("users-name")
        self.assertEqual(m["protected"], "true")
        self.assertEqual(m["expires"], "never")

    def test_keep_expiry_preserves_date(self):
        self.add("in-college", mtype="project",
                 description="In college until 2030")
        run(["expire", "in-college", "--in", "4y"])
        expected = (date.today() + timedelta(days=4 * 365)).isoformat()
        run(["protect", "in-college", "--keep-expiry"])
        m = self.meta("in-college")
        self.assertEqual(m["protected"], "true")
        self.assertEqual(m["expires"], expected)

    def test_edit_and_delete_refused_until_unprotect(self):
        self.add("innate")
        run(["protect", "innate"])
        code, _, err = run(["edit", "innate"], stdin_text="new body\n")
        self.assertEqual(code, 1)
        self.assertIn("protected", err)
        self.assertIn("unprotect", err)
        code, _, err = run(["delete", "innate"])
        self.assertEqual(code, 1)
        self.assertIn("unprotect", err)
        # two-step: unprotect then act works
        run(["unprotect", "innate"])
        self.assertNotIn("protected", self.meta("innate"))
        code, _, _ = run(["edit", "innate"], stdin_text="new body\n")
        self.assertEqual(code, 0)
        code, _, _ = run(["delete", "innate"])
        self.assertEqual(code, 0)

    def test_protected_visible_in_list_and_packet_label(self):
        self.add("labeled")
        run(["protect", "labeled"])
        _, out, _ = run(["list"])
        self.assertIn("[protected]", out)
        _, out, _ = run(["recall", "--query", "labeled description"])
        self.assertIn("(user, protected)", out)


class TestProtectedLifecycle(TempStoreMixin, unittest.TestCase):
    def _force_expiry(self, name, iso):
        p = engram.find_memory(self.store, name)
        _, meta, body = engram.read_memory(p)
        meta["expires"] = iso
        engram.atomic_write_text(p, engram.serialize_memory(meta, body))
        run(["reindex"])

    def test_sweep_never_touches_protected(self):
        self.add("shielded")
        run(["protect", "shielded", "--keep-expiry"])
        self._force_expiry("shielded", (date.today() - timedelta(days=5)).isoformat())
        self.assertEqual(engram.sweep_expired(self.store), [])
        engram.find_memory(self.store, "shielded")  # still active

    def test_past_due_protected_stays_in_review_queue_and_recall(self):
        self.add("overdue")
        run(["protect", "overdue", "--keep-expiry"])
        self._force_expiry("overdue", (date.today() - timedelta(days=5)).isoformat())
        code, out, _ = run(["recall", "--query", "overdue description"])
        self.assertIn("## overdue", out)             # still served (user's locked fact)
        self.assertIn("Expiring soon", out)          # nagging until user decides
        self.assertIn("overdue", out.split("Expiring soon")[1])

    def test_doctor_fix_does_not_archive_protected_expired(self):
        self.add("held")
        run(["protect", "held", "--keep-expiry"])
        self._force_expiry("held", (date.today() - timedelta(days=5)).isoformat())
        code, out, _ = run(["doctor", "--fix", "--json"])
        report = json.loads(out)
        self.assertFalse(any("held" in f for f in report["fixes"]))
        by = {c["check"]: c for c in report["checks"]}
        self.assertEqual(by["expired"]["status"], "ok")  # protected not counted
        engram.find_memory(self.store, "held")

    def test_purge_skips_protected_archived(self):
        # hand-archived protected file (edge: user moved it manually)
        body = "kept\n"
        meta = {"name": "hand-moved", "description": "Hand-archived protected",
                "type": "user", "created": "2026-01-01", "updated": "2026-01-01",
                "expires": "never", "protected": "true", "source_agent": "user",
                "archived": "2026-01-02", "hash": engram.body_hash(body)}
        p = self.store / "archive" / "hand-moved.md"
        engram.atomic_write_text(p, engram.serialize_memory(meta, body))
        code, out, _ = run(["purge", "--older-than", "90d", "--yes"])
        self.assertTrue(p.exists())
        self.assertIn("protected", out)


class TestDurations(TempStoreMixin, unittest.TestCase):
    def test_expire_accepts_weeks_months_years(self):
        for spec, days in (("2w", 14), ("6m", 180), ("4y", 1460)):
            name = f"dur-{spec}"
            self.add(name)
            code, _, _ = run(["expire", name, "--in", spec])
            self.assertEqual(code, 0)
            self.assertEqual(self.meta(name)["expires"],
                             (date.today() + timedelta(days=days)).isoformat())

    def test_bad_duration_actionable_error(self):
        self.add("dur-bad")
        code, _, err = run(["expire", "dur-bad", "--in", "4years"])
        self.assertEqual(code, 1)
        self.assertIn("4y", err)  # error shows valid examples

    def test_config_ttl_defaults_accept_units(self):
        cfg = json.loads((self.store / "config.json").read_text())
        cfg["ttl_defaults"]["project"] = "2y"
        (self.store / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.add("unit-ttl", mtype="project")
        self.assertEqual(self.meta("unit-ttl")["expires"],
                         (date.today() + timedelta(days=730)).isoformat())

    def test_purge_accepts_units(self):
        code, out, _ = run(["purge", "--older-than", "3m", "--yes"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

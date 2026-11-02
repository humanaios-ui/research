"""Milestone C: sandbox rehearsal of the full release path.

Asserts zero unauthorized releases, no state advance on failure, resume after
an injected failure, and that a repeat run changes nothing.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rehearse_release as rr  # noqa: E402


def workdir():
    return Path(tempfile.mkdtemp()) / "sandbox"


def files_under(root: Path):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file() and "research/.git" not in str(p)
            and p.name != "state.json"}


class HappyPathTest(unittest.TestCase):
    def test_complete_run(self):
        w = workdir()
        st = rr.run(w)
        self.assertEqual(st["result"], "complete")
        self.assertEqual([t["state"] for t in st["transitions"]], rr.STEPS)
        s = rr.summary(w)
        self.assertEqual(s["releases"], [rr.TAG])
        self.assertEqual(s["catalog"][rr.TAG]["status"], "published")
        self.assertEqual(s["drafts"], [f"{rr.TAG}.eml"])
        self.assertIn("not sent", (w / "services/drafts" / f"{rr.TAG}.eml").read_text())
        for t in st["transitions"]:
            self.assertEqual(t["commit"], st["approved_commit"])
            self.assertEqual(t["actor"], rr.ACTOR)
        self.assertEqual(st["release_commit"], st["approved_commit"])

    def test_repeat_run_changes_nothing(self):
        w = workdir()
        rr.run(w)
        before = files_under(w)
        n = len(json.loads((w / "state.json").read_text())["transitions"])
        st = rr.run(w)
        self.assertEqual(st["result"], "complete")
        self.assertEqual(len(st["transitions"]), n)  # no new transitions
        self.assertEqual(files_under(w), before)


class FailureTest(unittest.TestCase):
    def test_no_step_after_a_failure_and_resume_completes(self):
        for step in rr.STEPS:
            with self.subTest(step=step):
                w = workdir()
                st = rr.run(w, fail_at=step)
                self.assertEqual(st["result"], "failed")
                self.assertEqual(st["transitions"][-1]["state"], step)
                self.assertEqual(st["transitions"][-1]["status"], "failed")
                ok = [t["state"] for t in st["transitions"] if t["status"] == "ok"]
                self.assertEqual(ok, rr.STEPS[:rr.STEPS.index(step)])
                s = rr.summary(w)
                if rr.STEPS.index(step) <= rr.STEPS.index("released"):
                    self.assertEqual(s["releases"], [])
                if rr.STEPS.index(step) <= rr.STEPS.index("catalog_recorded"):
                    self.assertEqual(s["catalog"], {})  # catalog never ahead of release
                st = rr.run(w)
                self.assertEqual(st["result"], "complete")
                self.assertEqual(rr.summary(w)["releases"], [rr.TAG])

    def test_bad_inputs_produce_zero_releases(self):
        expect = {"forged-hash": "approved_exact_sha",
                  "mutated-after-approval": "approved_exact_sha",
                  "unratified": "approved_exact_sha",
                  "missing-license": "validated"}
        for scenario, where in expect.items():
            with self.subTest(scenario=scenario):
                w = workdir()
                st = rr.run(w, scenario=scenario)
                self.assertEqual(st["result"], "failed")
                self.assertEqual(st["transitions"][-1]["state"], where)
                self.assertFalse((w / "dist").exists())
                s = rr.summary(w)
                self.assertEqual((s["releases"], s["catalog"], s["drafts"]), ([], {}, []))


class DriftTest(unittest.TestCase):
    def test_changed_bundle_is_caught_on_rerun(self):
        w = workdir()
        rr.run(w)
        (w / "dist/manifest.json").write_text("{}\n")
        st = rr.run(w)
        self.assertEqual(st["result"], "failed")
        self.assertEqual(st["transitions"][-1]["state"], "bundled")

    def test_existing_release_with_other_assets_is_refused(self):
        w = workdir()
        rr.run(w, fail_at="released")
        target = w / "services/releases" / rr.TAG
        target.mkdir()
        (target / "release.json").write_text(json.dumps({"tag": rr.TAG, "assets": {"x": "y"}}))
        st = rr.run(w)
        self.assertEqual(st["transitions"][-1]["state"], "released")
        self.assertIn("different assets", st["transitions"][-1]["detail"])
        self.assertEqual(rr.summary(w)["catalog"], {})

    def test_corrupted_release_asset_is_refused(self):
        w = workdir()
        rr.run(w)
        asset = w / "services/releases" / rr.TAG / "manifest.json"
        asset.write_text("{}\n")  # release.json left unchanged
        st = rr.run(w)
        self.assertEqual(st["result"], "failed")
        self.assertEqual(st["transitions"][-1]["state"], "released")
        self.assertIn("different assets", st["transitions"][-1]["detail"])

    def test_moved_tag_is_refused(self):
        w = workdir()
        rr.run(w, fail_at="bundled")
        research = w / "research"
        (research / "README.md").write_text("later\n")
        rr.git(research, "commit", "-qam", "later")
        rr.git(research, "tag", "-f", rr.TAG)  # someone moves the tag
        st = rr.run(w)
        self.assertEqual(st["result"], "failed")
        # Caught at the first gate: the Z2 check now reads the tag itself.
        self.assertEqual(st["transitions"][-1]["state"], "approved_exact_sha")
        self.assertIn("not the commit being released", st["transitions"][-1]["detail"])
        self.assertEqual(rr.summary(w)["releases"], [])

    def test_main_moving_on_after_start_does_not_break_resume(self):
        w = workdir()
        rr.run(w, fail_at="released")
        research = w / "research"
        (research / "README.md").write_text("unrelated later work\n")
        rr.git(research, "commit", "-qam", "later work on main")
        st = rr.run(w)
        self.assertEqual(st["result"], "complete")
        self.assertEqual(st["release_commit"], st["approved_commit"])


class SafetyTest(unittest.TestCase):
    def test_new_rehearsal_refuses_a_nonempty_workdir(self):
        w = workdir()
        real = w / "operations/z1-inbox/INDEX.yaml"
        real.parent.mkdir(parents=True)
        real.write_text("real data\n")
        with self.assertRaises(SystemExit):
            rr.run(w)
        self.assertEqual(real.read_text(), "real data\n")
        self.assertFalse((w / "state.json").exists())

    def test_real_step_error_is_recorded_as_a_failed_transition(self):
        w = workdir()
        rr.run(w, fail_at="released")
        shutil.rmtree(w / "dist")
        (w / "dist").write_text("not a directory\n")  # an OSError, not a StepFailed
        st = rr.run(w)
        self.assertEqual(st["result"], "failed")
        self.assertEqual(st["transitions"][-1]["status"], "failed")
        self.assertEqual(rr.summary(w)["releases"], [])


if __name__ == "__main__":
    unittest.main()

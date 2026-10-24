"""End-to-end release authorization tests: registry entry -> operations Z2
record -> validate --release -> bundle. No network, no GitHub Release.

Every negative case must produce zero bundles.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_release_manifest as brm  # noqa: E402
import validate_repository as vr  # noqa: E402
import z2_release_auth as auth  # noqa: E402
from test_publishing import Repo, git  # noqa: E402

TAG = "dataset-acme-corpus-v1.0.0"
Q_ID = "Q-RESEARCH-RELEASE-ACME-01"
DATA = "datasets/acme-corpus/v1-2026q1/data.csv"
LICENSE = "datasets/acme-corpus/v1-2026q1/LICENSE"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Ops:
    """A minimal operations tree in the shape ratify.py writes."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "z1-inbox/2026-10-24").mkdir(parents=True)

    def file(self, release: dict, by="Night", at="2026-10-24", status="ratified",
             tamper=False, ratifiers=("Night",), extra=None, blocks=1):
        block = "```json research-release\n" + json.dumps(release, indent=2) + "\n```\n"
        cand = ("# Release candidate\n\n" + block * blocks).encode()
        cand_rel = f"z1-inbox/2026-10-24/{Q_ID}.md"
        z2_hash = auth.signature(cand, by, at, "ACCEPT")
        if tamper:  # content edited after signing
            cand += b"\nedited later\n"
        (self.root / cand_rel).write_bytes(cand)
        ruling_rel = "z1-inbox/2026-10-24/Z2_RULINGS_2026-10-24.md"
        (self.root / ruling_rel).write_text(f"## {Q_ID}\n\n- hash `{z2_hash}`\n")
        entries = [{"q_id": Q_ID, "path": cand_rel, "status": status, "ratified_by": by,
                    "ratified_at": at, "z2_ruling": ruling_rel, "z2_hash": z2_hash}]
        entries += extra or []
        import yaml
        (self.root / "z1-inbox/INDEX.yaml").write_text(yaml.safe_dump(
            {"ratifiers": list(ratifiers), "candidates": entries}))
        return z2_hash

    def close(self):
        shutil.rmtree(self.root)


class ReleaseAuthTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        reg = json.loads((self.repo.root / "registry/datasets.json").read_text())
        reg["datasets"][0]["rights_ref"] = "consent: fixture"
        self.repo.write("registry/datasets.json", json.dumps(reg).encode())
        self.pub = {"release_tag": TAG, "kind": "dataset", "slug": "acme-corpus",
                    "version": "1.0.0", "title": "Acme", "license": "CC0-1.0",
                    "authors": ["A"], "scope": "fixture", "limitations": "fixture",
                    "z2_q_id": Q_ID}
        self.set_pubs([self.pub])
        self.repo.commit("candidate")
        self.commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo.root,
                                     capture_output=True, text=True).stdout.strip()
        self.ops = Ops()

    def tearDown(self):
        self.repo.close()
        self.ops.close()

    def set_pubs(self, pubs):
        self.repo.write("registry/publications.json", json.dumps({"publications": pubs}).encode())

    def commit_pubs(self, pubs):
        """Registry change that is part of the released commit."""
        self.set_pubs(pubs)
        self.repo.commit("registry change")
        self.commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo.root,
                                     capture_output=True, text=True).stdout.strip()

    def release(self, **over):
        files = [{"path": p, "sha256": sha((self.repo.root / p).read_bytes())}
                 for p in (DATA, LICENSE)]
        rel = {"repo": "humanaios-ui/research", "release_tag": TAG,
               "git_commit": self.commit, "files": files}
        rel.update(over)
        return rel

    def errors(self, operations=True):
        return " ".join(vr.run(self.repo.root, release=TAG,
                               operations=str(self.ops.root) if operations else None).errors)

    def tag(self, commit=None):
        git(self.repo.root, "tag", "-f", TAG, commit or self.commit)

    def assert_no_bundle(self):
        out = Path(tempfile.mkdtemp())
        with self.assertRaises(SystemExit):
            brm.build(self.repo.root, TAG, out / "dist", out / "notes", self.ops.root)
        self.assertFalse((out / "dist").exists())

    # --- the one path that may publish ---

    def test_ratified_exact_release_builds_reproducibly(self):
        z2_hash = self.ops.file(self.release())
        self.assertEqual(self.errors(), "")
        self.tag()
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        for d in (a, b):
            brm.build(self.repo.root, TAG, d / "dist", d / "notes", self.ops.root)
        for name in (f"{TAG}.tar.gz", "manifest.json", "checksums.sha256"):
            self.assertEqual((a / "dist" / name).read_bytes(), (b / "dist" / name).read_bytes())
        m = json.loads((a / "dist/manifest.json").read_text())
        self.assertEqual(m["z2"], {"q_id": Q_ID, "z2_hash": z2_hash})
        self.assertEqual([f["path"] for f in m["files"]], sorted([DATA, LICENSE]))
        self.assertIn(Q_ID, (a / "notes" / f"{TAG}.md").read_text())

    # --- authority ---

    def test_no_operations_checkout_fails_closed(self):
        self.ops.file(self.release())
        self.assertIn("--operations checkout is required", self.errors(operations=False))

    def test_forged_correct_length_hash(self):
        self.ops.file(self.release())
        idx = (self.ops.root / "z1-inbox/INDEX.yaml").read_text()
        import yaml
        doc = yaml.safe_load(idx)
        doc["candidates"][0]["z2_hash"] = "a" * 64
        (self.ops.root / "z1-inbox/INDEX.yaml").write_text(yaml.safe_dump(doc))
        self.assertIn("SIGNATURE MISMATCH", self.errors())
        self.assert_no_bundle()

    def test_candidate_edited_after_ratification(self):
        self.ops.file(self.release(), tamper=True)
        self.assertIn("SIGNATURE MISMATCH", self.errors())

    def test_unratified_withdrawn_or_superseded(self):
        for status in ("awaiting_z2", "withdrawn", "superseded"):
            self.ops.file(self.release(), status=status)
            self.assertIn("not 'ratified'", self.errors(), status)
        for form in (Q_ID, f"Q-OTHER, {Q_ID}", f"Q-OTHER,{Q_ID}", ["Q-OTHER", Q_ID]):
            self.ops.file(self.release(), extra=[{"q_id": "Q-NEXT", "supersedes": form}])
            self.assertIn("superseded by", self.errors(), form)
        self.assert_no_bundle()
        self.ops.file(self.release(), extra=[{"q_id": "Q-NEXT", "supersedes": [f"{Q_ID}-2"]}])
        self.assertNotIn("superseded by", self.errors())  # no prefix match

    def test_unlisted_ratifier(self):
        self.ops.file(self.release(), by="Mallory")
        self.assertIn("not an INDEX ratifier", self.errors())

    def test_missing_ruling_record(self):
        self.ops.file(self.release())
        (self.ops.root / "z1-inbox/2026-10-24/Z2_RULINGS_2026-10-24.md").unlink()
        self.assertIn("z2_ruling file missing", self.errors())

    def test_two_release_blocks_rejected(self):
        self.ops.file(self.release(), blocks=2)
        self.assertIn("exactly one research-release block", self.errors())

    # --- exact commit and payload ---

    def test_tag_on_different_commit(self):
        self.ops.file(self.release(git_commit="f" * 40))
        self.assertIn("approved commit is", self.errors())
        self.assert_no_bundle()

    def test_file_changed_after_approval(self):
        self.ops.file(self.release())
        self.repo.write(DATA, b"a,b\n9,9\n")
        reg = json.loads((self.repo.root / "registry/datasets.json").read_text())
        reg["datasets"][0]["sha256"] = sha(b"a,b\n9,9\n")
        self.repo.write("registry/datasets.json", json.dumps(reg).encode())
        self.repo.commit("mutate")  # tag now points at the mutated commit
        errs = " ".join(vr.run(self.repo.root, release=TAG, operations=str(self.ops.root)).errors)
        self.assertIn("approved commit is", errs)

    def test_empty_payload(self):
        self.ops.file(self.release(files=[]))
        self.assertIn("approved file list is empty", self.errors())
        self.assert_no_bundle()

    def test_traversal_duplicate_and_untracked_paths(self):
        good = self.release()["files"][0]
        bad = [good, good, {"path": "../etc/passwd", "sha256": "0" * 64},
               {"path": "datasets/./x", "sha256": "0" * 64},
               {"path": "papers/missing.md", "sha256": "0" * 64}]
        self.ops.file(self.release(files=bad))
        errs = self.errors()
        self.assertIn("duplicate path", errs)
        self.assertIn("unsafe or non-normalized path '../etc/passwd'", errs)
        self.assertIn("unsafe or non-normalized path 'datasets/./x'", errs)
        self.assertIn("not tracked at", errs)

    def test_wrong_approved_hash(self):
        files = [{"path": DATA, "sha256": "0" * 64}]
        self.ops.file(self.release(files=files))
        self.assertIn("changed after approval", self.errors())

    # --- registry and rights ---

    def test_duplicate_registry_entries(self):
        self.commit_pubs([self.pub, dict(self.pub)])
        self.ops.file(self.release())
        errs = self.errors()
        self.assertIn("duplicate release_tag", errs)
        self.assertIn("duplicate kind/slug/version", errs)

    def test_dataset_without_license_or_rights_blocks_release(self):
        reg = json.loads((self.repo.root / "registry/datasets.json").read_text())
        reg["datasets"][0]["rights_ref"] = None
        self.repo.write("registry/datasets.json", json.dumps(reg).encode())
        self.repo.commit("drop rights")
        self.commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo.root,
                                     capture_output=True, text=True).stdout.strip()
        self.ops.file(self.release(files=[self.release()["files"][0]]))  # data only
        errs = self.errors()
        self.assertIn("no license file in the release", errs)
        self.assertIn("no rights/consent reference", errs)
        self.assert_no_bundle()  # the standalone builder refuses it too

    def test_rights_are_read_at_the_released_commit(self):
        reg = json.loads((self.repo.root / "registry/datasets.json").read_text())
        reg["datasets"][0]["rights_ref"] = None
        self.repo.write("registry/datasets.json", json.dumps(reg).encode())
        self.repo.commit("released commit lacks rights")
        self.commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo.root,
                                     capture_output=True, text=True).stdout.strip()
        self.ops.file(self.release())
        self.tag()

        def assert_refused():
            out = Path(tempfile.mkdtemp())
            with self.assertRaises(SystemExit) as cm:
                brm.build(self.repo.root, TAG, out / "dist", out / "notes", self.ops.root,
                          commit=self.commit)
            self.assertIn("no rights/consent reference", str(cm.exception))
            self.assertFalse((out / "dist").exists())

        # Rights restored only in the working tree, then in a later commit:
        # the released commit must still be refused both times.
        reg["datasets"][0]["rights_ref"] = "consent: fixture"
        self.repo.write("registry/datasets.json", json.dumps(reg).encode())
        assert_refused()
        self.repo.commit("later commit restores rights")
        assert_refused()

    def test_publication_metadata_is_read_at_the_released_commit(self):
        self.ops.file(self.release())
        # A later, uncommitted edit must not reach the manifest or the checks.
        self.set_pubs([dict(self.pub, title="Edited later", scope="")])
        self.assertEqual(self.errors(), "")
        self.tag()
        out = Path(tempfile.mkdtemp())
        brm.build(self.repo.root, TAG, out / "dist", out / "notes", self.ops.root,
                  commit=self.commit)
        m = json.loads((out / "dist/manifest.json").read_text())
        self.assertEqual(m["publication"]["title"], "Acme")

    def test_tag_must_point_at_the_released_commit(self):
        self.ops.file(self.release())
        out = Path(tempfile.mkdtemp())
        with self.assertRaises(SystemExit) as cm:  # untagged: no bundle
            brm.build(self.repo.root, TAG, out / "dist", out / "notes", self.ops.root,
                      commit=self.commit)
        self.assertIn(f"tag {TAG} does not exist", str(cm.exception))
        self.repo.write("README.md", b"later\n")
        self.repo.commit("later")
        self.tag("HEAD")  # tag on a different commit than the approved one
        errs = " ".join(vr.run(self.repo.root, release=TAG, operations=str(self.ops.root),
                               commit=self.commit).errors)
        self.assertIn("not the commit being released", errs)
        with self.assertRaises(SystemExit):
            brm.build(self.repo.root, TAG, out / "dist", out / "notes", self.ops.root,
                      commit=self.commit)
        self.assertFalse((out / "dist").exists())

    def test_missing_scope_and_limitations(self):
        pub = {k: v for k, v in self.pub.items() if k not in ("scope", "limitations")}
        self.commit_pubs([pub])
        self.ops.file(self.release())
        errs = self.errors()
        self.assertIn("missing scope", errs)
        self.assertIn("missing limitations", errs)


class SignatureCompatTest(unittest.TestCase):
    def test_matches_ratify_py_construction(self):
        # sha256(candidate | by=… | at=… | decision=…) per operations CLAUDE.md
        expect = hashlib.sha256(b"body|by=Night|at=2026-10-24|decision=ACCEPT").hexdigest()
        self.assertEqual(auth.signature(b"body", "Night", "2026-10-24", "ACCEPT"), expect)


if __name__ == "__main__":
    unittest.main()

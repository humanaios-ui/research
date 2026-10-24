"""Tests for scripts/build_release_manifest.py."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_release_manifest as brm  # noqa: E402
from test_publishing import Repo  # noqa: E402

TAG = "dataset-acme-corpus-v1.0.0"


class ReleaseManifestTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        pub = {"release_tag": TAG, "kind": "dataset", "slug": "acme-corpus",
               "version": "1.0.0", "status": "approved", "title": "Acme",
               "license": "CC0-1.0", "authors": ["A"], "z2_ratification_hash": "b" * 64,
               "paths": ["datasets/acme-corpus/v1-2026q1"]}
        self.repo.write("registry/publications.json",
                        json.dumps({"publications": [pub]}).encode())
        self.repo.commit("pub")

    def tearDown(self):
        self.repo.close()

    def build(self):
        out = Path(tempfile.mkdtemp())
        brm.build(self.repo.root, TAG, out / "dist", out / "notes")
        return out

    def test_bundle_is_reproducible(self):
        a, b = self.build(), self.build()
        for name in (f"{TAG}.tar.gz", "manifest.json", "checksums.sha256"):
            self.assertEqual((a / "dist" / name).read_bytes(),
                             (b / "dist" / name).read_bytes(), name)

    def test_manifest_lists_declared_files_and_notes_stay_out_of_dist(self):
        out = self.build()
        m = json.loads((out / "dist/manifest.json").read_text())
        self.assertEqual([f["path"] for f in m["files"]],
                         ["datasets/acme-corpus/v1-2026q1/LICENSE",
                          "datasets/acme-corpus/v1-2026q1/data.csv"])
        self.assertEqual(sorted(p.name for p in (out / "dist").iterdir()),
                         sorted([f"{TAG}.tar.gz", "manifest.json", "checksums.sha256"]))
        self.assertIn("b" * 64, (out / "notes" / f"{TAG}.md").read_text())

    def test_unknown_tag_fails(self):
        with self.assertRaises(SystemExit):
            brm.build(self.repo.root, "paper-nope-v1.0.0",
                      Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()

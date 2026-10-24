"""Tests for scripts/inventory.py and scripts/validate_repository.py.

Run: python3 -m unittest discover -s tests
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory  # noqa: E402
import validate_repository as vr  # noqa: E402

RAW_ARG = (
    "name,type,resourceGroup,location,id\n"
    "aios-acct,microsoft.cognitiveservices/accounts,rg-demo,westus3,"
    "/subscriptions/00000000-1111-2222-3333-444444444444/resourceGroups/rg-demo/providers/x/aios-acct\n"
    "aios-proj,microsoft.cognitiveservices/accounts/projects,rg-demo,westus3,/subscriptions/0000.../proj\n"
)


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class Repo:
    """A throwaway git repo with the minimal registry layout."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "config", "user.name", "t")
        data = b"a,b\n1,2\n"
        self.write("datasets/acme-corpus/v1-2026q1/data.csv", data)
        self.write_registry([{
            "id": "acme-v1", "slug": "acme-corpus", "method_version": "v1",
            "path": "datasets/acme-corpus/v1-2026q1/data.csv",
            "sha256": inventory.sha256_bytes(data), "license": "CC0-1.0",
            "license_file": "datasets/acme-corpus/v1-2026q1/LICENSE",
            "data_class": "public", "lifecycle": "frozen"}])
        self.write("datasets/acme-corpus/v1-2026q1/LICENSE", b"CC0\n")
        self.write("registry/publications.json", b'{"publications": []}\n')
        self.write("README.md", b"x\n")
        self.commit("base")

    def write(self, rel, data: bytes):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def write_registry(self, datasets):
        self.write("registry/datasets.json", json.dumps({"datasets": datasets}).encode())

    def commit(self, msg):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", msg)

    def close(self):
        shutil.rmtree(self.root)


class ArgSanitizeTest(unittest.TestCase):
    def test_complete_id_detection(self):
        self.assertTrue(inventory.is_complete_azure_id(
            "/subscriptions/abc/resourceGroups/rg/providers/x"))
        self.assertFalse(inventory.is_complete_azure_id("/subscriptions/0000.../proj"))
        self.assertFalse(inventory.is_complete_azure_id(""))

    def test_raw_ids_never_survive(self):
        rows, warnings = inventory.sanitize_arg_rows(RAW_ARG)
        dumped = json.dumps(rows)
        self.assertNotIn("/subscriptions/", dumped)
        self.assertNotIn("00000000-1111", dumped)
        complete = {r["resource_name"]: r["azure_id_complete"] for r in rows}
        self.assertEqual(complete, {"aios-acct": "true", "aios-proj": "false"})
        self.assertEqual(len([w for w in warnings if "incomplete" in w["issue"]]), 1)

    def test_alias_resolution_and_unknown_columns(self):
        text = "resourceName,resourceType,rg,region,resourceId,owner\nn,T,g,WestUS3,,me\n"
        rows, warnings = inventory.sanitize_arg_rows(text)
        self.assertEqual(rows[0]["resource_type"], "t")
        self.assertEqual(rows[0]["region"], "westus3")
        self.assertTrue(any(w.get("column") == "owner" for w in warnings))

    def test_sanitized_snapshot_round_trips(self):
        rows, _ = inventory.sanitize_arg_rows(RAW_ARG)
        header = ",".join(inventory.SANITIZED_COLUMNS)
        body = "".join(",".join(r[c] for c in inventory.SANITIZED_COLUMNS) + "\n" for r in rows)
        again, _ = inventory.sanitize_arg_rows(header + "\n" + body)
        self.assertEqual(rows, again)


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_deterministic_and_check(self):
        root = self.repo.root
        self.assertEqual(inventory.render(root, None), inventory.render(root, None))
        self.assertEqual(inventory.main(["--root", str(root), "--check"]), 1)
        self.assertEqual(inventory.main(["--root", str(root)]), 0)
        self.repo.commit("generated")
        self.assertEqual(inventory.main(["--root", str(root), "--check"]), 0)
        self.repo.write("papers/new-paper/README.md", b"draft\n")
        git(root, "add", "-A")
        self.assertEqual(inventory.main(["--root", str(root), "--check"]), 1)

    def test_checksums_cover_publication_data_only(self):
        out = inventory.render(self.repo.root, None)["checksums.sha256"]
        self.assertIn("datasets/acme-corpus/v1-2026q1/data.csv", out)
        self.assertNotIn("README.md", out)


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def errors(self, **kw):
        return vr.run(self.repo.root, **kw).errors

    def test_clean_repo_passes(self):
        self.assertEqual(self.errors(), [])

    def test_bad_slug_and_build_dir(self):
        self.repo.write("papers/Bad_Slug/main.tex", b"x")
        self.repo.write("papers/good-slug/dist/out.pdf", b"x")
        git(self.repo.root, "add", "-A")
        errs = " ".join(self.errors())
        self.assertIn("kebab-case", errs)
        self.assertIn("build output", errs)

    def test_unregistered_dataset_and_hash_drift(self):
        self.repo.write("datasets/acme-corpus/v1-2026q1/data.csv", b"tampered\n")
        self.repo.write("datasets/acme-corpus/v2-2026q2/data.csv", b"new\n")
        git(self.repo.root, "add", "-A")
        errs = " ".join(self.errors())
        self.assertIn("sha256 mismatch", errs)
        self.assertIn("not registered", errs)

    def test_frozen_edit_blocked_but_errata_append_allowed(self):
        self.repo.write("corrections/acme/errata-2026-11-14.md", b"fix\n")
        self.repo.commit("errata")
        git(self.repo.root, "branch", "base")
        self.repo.write("corrections/acme/errata-2026-12-01.md", b"second\n")
        self.repo.commit("append")
        self.assertEqual(self.errors(base="base"), [])
        self.repo.write("corrections/acme/errata-2026-11-14.md", b"rewritten\n")
        self.repo.commit("rewrite")
        self.assertIn("frozen path modified", " ".join(self.errors(base="base")))

    def test_secret_scan(self):
        self.repo.write("docs/notes.md",
                        b"/subscriptions/00000000-1111-2222-3333-444444444444/rg")
        git(self.repo.root, "add", "-A")
        self.assertIn("azure subscription id", " ".join(self.errors()))

    def test_release_requires_z2_hash(self):
        pub = {"release_tag": "paper-acme-v1.0.0", "kind": "paper", "slug": "acme",
               "version": "1.0.0", "status": "approved", "title": "T",
               "license": "CC-BY-4.0", "authors": ["A"], "paths": []}
        self.repo.write("registry/publications.json",
                        json.dumps({"publications": [pub]}).encode())
        self.assertIn("Z2 ratification hash",
                      " ".join(self.errors(release="paper-acme-v1.0.0")))
        pub["z2_ratification_hash"] = "a" * 64
        self.repo.write("registry/publications.json",
                        json.dumps({"publications": [pub]}).encode())
        self.assertEqual(self.errors(release="paper-acme-v1.0.0"), [])
        self.assertIn("must be paper-", " ".join(self.errors(release="v1.0.0")))


if __name__ == "__main__":
    unittest.main()

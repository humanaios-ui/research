#!/usr/bin/env python3
"""Repository gates for the publishing methodology.

    python3 scripts/validate_repository.py                     # structure, registry, secrets
    python3 scripts/validate_repository.py --base origin/main  # + frozen paths unchanged
    python3 scripts/validate_repository.py --release TAG --operations ../operations
                                                               # + tag is Z2-ratified

Errors exit 1. Warnings print but pass.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory  # noqa: E402
import z2_release_auth  # noqa: E402

ROOT = inventory.ROOT
ALLOWED_TOP = {"papers", "datasets", "supplementary", "corrections", "registry",
               "scripts", "tests", "infra", "docs", ".github", ".claude",
               ".agents", ".codex"} | inventory.ROOT_FILES
FORBIDDEN_DIRS = {"build", "dist", "artifacts", "__pycache__", "node_modules"}
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SNAPSHOT = re.compile(r"^v\d+(?:-\d+)*-\d{4}(?:q[1-4]|h[12]|m(?:0[1-9]|1[0-2]))?$")
RELEASE_TAG = re.compile(r"^(paper|dataset)-([a-z0-9]+(?:-[a-z0-9]+)*)-v(\d+\.\d+\.\d+)$")
ERRATA = re.compile(r"^errata-\d{4}-\d{2}-\d{2}\.md$")
ARG_MARKERS = ("resourcegroup", "resource_group", "azure_id")
SECRET_PATTERNS = [
    ("azure subscription id", re.compile(r"/subscriptions/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("azure storage key", re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}")),
    ("supabase secret key", re.compile(r"\bsb_secret_[A-Za-z0-9_-]{10,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
]
# Files that define the patterns above are allowed to contain them.
SECRET_SCAN_SKIP = {"scripts/validate_repository.py", "tests/test_publishing.py"}


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def all_tracked(root: Path):
    """Every tracked file, generated output included (the secret scan needs it)."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                         capture_output=True).stdout.decode()
    return sorted(p for p in out.split("\0") if p)


def check_structure(root: Path, files, rep: Report):
    for path in files:
        parts = path.split("/")
        if parts[0] not in ALLOWED_TOP:
            rep.error(f"{path}: top-level entry '{parts[0]}' is not in the declared layout")
        bad = FORBIDDEN_DIRS.intersection(parts[:-1])
        if bad:
            rep.error(f"{path}: build output directory {sorted(bad)} must not be committed")
        if parts[0] == "papers" and len(parts) > 2 and not KEBAB.match(parts[1]):
            rep.error(f"{path}: paper slug '{parts[1]}' must be lowercase kebab-case")
        if parts[0] == "datasets" and len(parts) > 2:
            if not KEBAB.match(parts[1]):
                rep.error(f"{path}: dataset slug '{parts[1]}' must be lowercase kebab-case")
            if len(parts) > 3 and not SNAPSHOT.match(parts[2]):
                rep.error(f"{path}: snapshot dir '{parts[2]}' must look like v5-3-2026q1")
        if parts[0] == "corrections" and len(parts) == 3 and parts[2] != "README.md" \
                and not ERRATA.match(parts[2]):
            rep.error(f"{path}: errata files are named errata-YYYY-MM-DD.md")


def check_registry(root: Path, files, rep: Report):
    datasets = json.loads((root / "registry/datasets.json").read_text())["datasets"]
    registered = set()
    for ds in datasets:
        path = ds["path"]
        registered.add(path)
        for key in ("id", "slug", "method_version", "sha256", "license", "data_class", "lifecycle"):
            if not ds.get(key):
                rep.error(f"registry/datasets.json {ds.get('id', path)}: missing {key}")
        if not KEBAB.match(ds.get("slug", "")):
            rep.error(f"registry dataset {ds['id']}: slug must be kebab-case")
        full = root / path
        if not full.is_file():
            rep.error(f"registry dataset {ds['id']}: {path} does not exist")
            continue
        actual = inventory.sha256_bytes(full.read_bytes())
        if actual != ds.get("sha256"):
            rep.error(f"registry dataset {ds['id']}: sha256 mismatch "
                      f"(registry {ds.get('sha256', '')[:12]}, file {actual[:12]}). "
                      "Frozen data changed; publish a correction as a new version instead.")
        if ds.get("data_class") != "public":
            rep.error(f"registry dataset {ds['id']}: data_class '{ds.get('data_class')}' "
                      "cannot live in this public repository")
        if not ds.get("license_file"):
            rep.warn(f"registry dataset {ds['id']}: no per-dataset LICENSE file "
                     f"(README promises one for datasets)")
    for path in files:
        if path.startswith("datasets/") and Path(path).name not in ("README.md", "LICENSE",
                                                                     "schema.json", "manifest.json") \
                and path not in registered:
            rep.error(f"{path}: dataset file is not registered in registry/datasets.json")


def check_secrets(root: Path, files, rep: Report):
    """Secrets and operational Azure inventory never live in this public repo."""
    for path in files:
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if path not in SECRET_SCAN_SKIP:
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    rep.error(f"{path}: possible {label}")
        if path.endswith(".csv"):
            header = text.split("\n", 1)[0].lower()
            if any(m in header for m in ARG_MARKERS):
                rep.error(f"{path}: looks like an Azure inventory export; keep it out of "
                          "this public repo (use inventory.py --private-out)")
        if path.endswith(".json") and '"azure-resource"' in text:
            rep.error(f"{path}: contains Azure resource records; keep them private")


def check_frozen(root: Path, base: str, rep: Report):
    """Frozen paths are append-only: no modify, delete, or rename vs base."""
    r = subprocess.run(["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD"],
                       cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        rep.error(f"base '{base}' cannot be compared to HEAD; refusing to skip the "
                  f"frozen-path check ({r.stderr.strip()[:200]})")
        return
    out = r.stdout
    for line in out.splitlines():
        status, path = line.split("\t", 1)
        bucket, lifecycle = inventory.classify(path)
        if lifecycle == "frozen" and status[0] in "MDT":
            rep.error(f"{path}: frozen path {'modified' if status[0] != 'D' else 'deleted'}. "
                      "Corrections are appended as new files, never edited in place.")


def check_release(root: Path, tag: str, operations, commit: str, rep: Report):
    m = RELEASE_TAG.match(tag)
    if not m:
        rep.error(f"tag {tag}: must be paper-<slug>-vX.Y.Z or dataset-<slug>-vX.Y.Z")
        return
    kind, slug, version = m.groups()
    pubs = json.loads((root / "registry/publications.json").read_text())["publications"]
    tags = [p.get("release_tag") for p in pubs]
    keys = [(p.get("kind"), p.get("slug"), p.get("version")) for p in pubs]
    for dup in sorted({t for t in tags if tags.count(t) > 1}):
        rep.error(f"registry: duplicate release_tag {dup}")
    for dup in sorted({k for k in keys if keys.count(k) > 1}):
        rep.error(f"registry: duplicate kind/slug/version {dup}")
    match = [p for p in pubs if p.get("release_tag") == tag]
    if not match:
        rep.error(f"tag {tag}: no entry in registry/publications.json")
        return
    pub = match[0]
    if (pub.get("kind"), pub.get("slug"), pub.get("version")) != (kind, slug, version):
        rep.error(f"tag {tag}: registry entry kind/slug/version do not match the tag")
    for key in ("title", "license", "authors", "scope", "limitations", "z2_q_id"):
        if not pub.get(key):
            rep.error(f"tag {tag}: missing {key}")
    if not operations:
        rep.error(f"tag {tag}: --operations checkout is required to verify Z2 ratification")
        return
    errors, approved = z2_release_auth.verify(Path(operations), str(pub.get("z2_q_id")),
                                              tag, commit, root)
    for e in errors:
        rep.error(f"tag {tag}: {e}")
    for e in z2_release_auth.dataset_rights_errors(root, commit, approved):
        rep.error(f"tag {tag}: {e}")

def run(root: Path, base=None, release=None, operations=None, commit="HEAD") -> Report:
    rep = Report()
    files = all_tracked(root)
    check_structure(root, files, rep)
    check_registry(root, files, rep)
    check_secrets(root, files, rep)
    if base:
        check_frozen(root, base, rep)
    if release:
        sha = subprocess.run(["git", "rev-parse", f"{commit}^{{commit}}"], cwd=root,
                             capture_output=True, text=True).stdout.strip()
        check_release(root, release, operations, sha, rep)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--base", help="Git ref to diff against for the frozen-path check")
    ap.add_argument("--release", metavar="TAG", help="Validate a release tag")
    ap.add_argument("--operations", help="Path to a humanaios-ui/operations checkout")
    ap.add_argument("--commit", default="HEAD", help="Commit the tag points at")
    args = ap.parse_args(argv)
    rep = run(Path(args.root).resolve(), args.base, args.release, args.operations,
              args.commit)
    for w in rep.warnings:
        print(f"warning: {w}")
    for e in rep.errors:
        print(f"error: {e}")
    print(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())

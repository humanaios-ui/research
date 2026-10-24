#!/usr/bin/env python3
"""Repository gates for the publishing methodology.

    python3 scripts/validate_repository.py                     # structure, registry, secrets
    python3 scripts/validate_repository.py --base origin/main  # + frozen paths unchanged
    python3 scripts/validate_repository.py --release TAG       # + tag is Z2-ratified

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

ROOT = inventory.ROOT
ALLOWED_TOP = {"papers", "datasets", "supplementary", "corrections", "registry",
               "scripts", "tests", "infra", "docs", ".github", ".claude",
               ".agents", ".codex"} | inventory.ROOT_FILES
FORBIDDEN_DIRS = {"build", "dist", "artifacts", "__pycache__", "node_modules"}
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SNAPSHOT = re.compile(r"^v\d+(?:-\d+)*-\d{4}(?:q[1-4]|h[12]|m(?:0[1-9]|1[0-2]))?$")
RELEASE_TAG = re.compile(r"^(paper|dataset)-([a-z0-9]+(?:-[a-z0-9]+)*)-v(\d+\.\d+\.\d+)$")
ERRATA = re.compile(r"^errata-\d{4}-\d{2}-\d{2}\.md$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
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
    for path in files:
        if path in SECRET_SCAN_SKIP:
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                rep.error(f"{path}: possible {label}")


def check_frozen(root: Path, base: str, rep: Report):
    """Frozen paths are append-only: no modify, delete, or rename vs base."""
    out = subprocess.run(["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD"],
                         cwd=root, check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        status, path = line.split("\t", 1)
        bucket, lifecycle = inventory.classify(path)
        if lifecycle == "frozen" and status[0] in "MDT":
            rep.error(f"{path}: frozen path {'modified' if status[0] != 'D' else 'deleted'}. "
                      "Corrections are appended as new files, never edited in place.")


def check_release(root: Path, tag: str, rep: Report):
    m = RELEASE_TAG.match(tag)
    if not m:
        rep.error(f"tag {tag}: must be paper-<slug>-vX.Y.Z or dataset-<slug>-vX.Y.Z")
        return
    kind, slug, version = m.groups()
    pubs = json.loads((root / "registry/publications.json").read_text())["publications"]
    match = [p for p in pubs if p.get("release_tag") == tag]
    if not match:
        rep.error(f"tag {tag}: no entry in registry/publications.json")
        return
    pub = match[0]
    if pub.get("kind") != kind or pub.get("slug") != slug or pub.get("version") != version:
        rep.error(f"tag {tag}: registry entry kind/slug/version do not match the tag")
    if pub.get("status") != "approved":
        rep.error(f"tag {tag}: status is '{pub.get('status')}', must be 'approved' before tagging")
    if not HEX64.match(pub.get("z2_ratification_hash", "")):
        rep.error(f"tag {tag}: missing Z2 ratification hash (64 hex chars)")
    for key in ("title", "license", "authors"):
        if not pub.get(key):
            rep.error(f"tag {tag}: missing {key}")
    for path in pub.get("paths", []):
        if not (root / path).exists():
            rep.error(f"tag {tag}: declared path {path} does not exist")


def run(root: Path, base=None, release=None) -> Report:
    rep = Report()
    files = inventory.tracked_files(root)
    check_structure(root, files, rep)
    check_registry(root, files, rep)
    check_secrets(root, files, rep)
    if base:
        check_frozen(root, base, rep)
    if release:
        check_release(root, release, rep)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--base", help="Git ref to diff against for the frozen-path check")
    ap.add_argument("--release", metavar="TAG", help="Validate a release tag")
    args = ap.parse_args(argv)
    rep = run(Path(args.root).resolve(), args.base, args.release)
    for w in rep.warnings:
        print(f"warning: {w}")
    for e in rep.errors:
        print(f"error: {e}")
    print(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())

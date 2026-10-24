#!/usr/bin/env python3
"""Verify that a release tag is covered by a Z2 ratification in operations.

Authority lives in humanaios-ui/operations, not here. A release is authorized
only by a candidate block under operations/z1-inbox/ that Z2 signed with
`.z1-control/ratify.py`, recorded in z1-inbox/INDEX.yaml, and merged. This
module re-checks that record; it does not create authority of its own.

The candidate must carry exactly one fenced block:

    ```json research-release
    {"repo": "humanaios-ui/research",
     "release_tag": "paper-<slug>-vX.Y.Z",
     "git_commit": "<40-hex commit the tag must point at>",
     "files": [{"path": "papers/<slug>/...", "sha256": "<64-hex>"}, ...]}
    ```

Checks, all fail closed:
  - INDEX entry exists, status is exactly `ratified` (not withdrawn/superseded)
  - ratified_by is listed in INDEX `ratifiers`
  - z2_hash recomputes as sha256(candidate | by | at | decision=ACCEPT),
    the formula in operations/.z1-control/ratify.py::signature
  - the z2_ruling file exists and contains z2_hash
  - no INDEX entry declares it supersedes this q_id
  - the block names this repo, this tag, and the exact commit being released
  - files is a non-empty list of unique, normalized, repo-relative paths, each
    present at that commit with the approved SHA-256 (no directory expansion)

Limit: like ratify.py, this pins CONTENT, not identity. The record binds
because Z2 merges it in operations. CI cannot authenticate who signed.
"""
import hashlib
import json
import posixpath
import re
import subprocess
from pathlib import Path

REPO = "humanaios-ui/research"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
BLOCK = re.compile(r"^```json research-release\s*\n(.*?)^```", re.M | re.S)


def signature(candidate_bytes: bytes, by: str, at: str, decision: str) -> str:
    """Same construction as operations/.z1-control/ratify.py::signature."""
    payload = candidate_bytes + f"|by={by}|at={at}|decision={decision}".encode()
    return hashlib.sha256(payload).hexdigest()


def id_list(value) -> list:
    """`supersedes` as written in INDEX.yaml: a YAML list, or one string of
    IDs separated by spaces or commas. Missing means none."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [t for t in re.split(r"[\s,]+", str(value)) if t]


def load_index(operations_root: Path) -> dict:
    import yaml  # only the release path needs PyYAML
    return yaml.safe_load((operations_root / "z1-inbox" / "INDEX.yaml").read_text())


def git_bytes(research_root: Path, commit: str, path: str):
    r = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=research_root,
                       capture_output=True)
    return r.stdout if r.returncode == 0 else None


def safe_path(path: str) -> bool:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return False
    return posixpath.normpath(path) == path and not path.startswith("../") and path != ".."


def verify(operations_root: Path, q_id: str, tag: str, commit: str,
           research_root: Path):
    """Return (errors, approved_files). approved_files is [] on any error."""
    errors = []
    try:
        index = load_index(operations_root)
    except FileNotFoundError:
        return [f"operations INDEX.yaml not found under {operations_root}"], []
    candidates = index.get("candidates") or []
    rows = [c for c in candidates if c.get("q_id") == q_id]
    if len(rows) != 1:
        return [f"{q_id}: expected exactly one INDEX entry, found {len(rows)}"], []
    c = rows[0]

    if c.get("status") != "ratified":
        errors.append(f"{q_id}: status is '{c.get('status')}', not 'ratified'")
    by, at, z2_hash = str(c.get("ratified_by")), str(c.get("ratified_at")), str(c.get("z2_hash"))
    if by not in (index.get("ratifiers") or []):
        errors.append(f"{q_id}: ratified_by '{by}' is not an INDEX ratifier")
    if not HEX64.match(z2_hash):
        errors.append(f"{q_id}: z2_hash is not a sha256")
    superseders = [x.get("q_id") for x in candidates
                   if q_id in id_list(x.get("supersedes"))]
    if superseders:
        errors.append(f"{q_id}: superseded by {superseders}")

    cand_path = operations_root / str(c.get("path"))
    if not cand_path.is_file():
        return errors + [f"{q_id}: candidate file {c.get('path')} missing"], []
    cand = cand_path.read_bytes()
    if signature(cand, by, at, "ACCEPT") != z2_hash:
        errors.append(f"{q_id}: SIGNATURE MISMATCH — candidate changed after ratification "
                      "or the hash was not produced by ratify.py")
    ruling = operations_root / str(c.get("z2_ruling", ""))
    if not c.get("z2_ruling") or not ruling.is_file() or z2_hash not in ruling.read_text():
        errors.append(f"{q_id}: z2_ruling file missing or does not contain z2_hash")

    blocks = BLOCK.findall(cand.decode("utf-8", "replace"))
    if len(blocks) != 1:
        return errors + [f"{q_id}: candidate must carry exactly one research-release block, "
                         f"found {len(blocks)}"], []
    try:
        rel = json.loads(blocks[0])
    except json.JSONDecodeError as e:
        return errors + [f"{q_id}: research-release block is not JSON ({e})"], []

    if rel.get("repo") != REPO:
        errors.append(f"{q_id}: release block repo is '{rel.get('repo')}', not {REPO}")
    if rel.get("release_tag") != tag:
        errors.append(f"{q_id}: approved tag '{rel.get('release_tag')}' is not '{tag}'")
    if not HEX40.match(str(rel.get("git_commit", ""))):
        errors.append(f"{q_id}: approved git_commit is not a full 40-hex SHA")
    elif rel["git_commit"] != commit:
        errors.append(f"{q_id}: tag points at {commit[:12]}, approved commit is "
                      f"{rel['git_commit'][:12]}")

    files = rel.get("files")
    if not isinstance(files, list) or not files:
        return errors + [f"{q_id}: approved file list is empty"], []
    seen = set()
    for f in files:
        path, digest = (f or {}).get("path"), (f or {}).get("sha256")
        if not safe_path(path):
            errors.append(f"{q_id}: unsafe or non-normalized path {path!r}")
            continue
        if path in seen:
            errors.append(f"{q_id}: duplicate path {path}")
        seen.add(path)
        if not HEX64.match(str(digest)):
            errors.append(f"{q_id}: {path}: approved sha256 missing or malformed")
            continue
        data = git_bytes(research_root, commit, path)
        if data is None:
            errors.append(f"{q_id}: {path} is not tracked at {commit[:12]}")
        elif hashlib.sha256(data).hexdigest() != digest:
            errors.append(f"{q_id}: {path} changed after approval (sha256 mismatch)")
    if errors:
        return errors, []
    return [], sorted(f["path"] for f in files)

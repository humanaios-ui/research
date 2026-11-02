#!/usr/bin/env python3
"""Sandbox rehearsal of the full release path (Milestone C). No network.

    python3 scripts/rehearse_release.py --workdir /tmp/rehearsal
    python3 scripts/rehearse_release.py --workdir /tmp/rehearsal --fail-at released
    python3 scripts/rehearse_release.py --workdir /tmp/rehearsal          # resumes
    python3 scripts/rehearse_release.py --workdir /tmp/r2 --scenario forged-hash

Everything lives under --workdir: a throwaway research repo with a synthetic
dataset, a throwaway operations tree holding a SANDBOX Z2 record, and file-
backed mocks of GitHub Releases, the catalog, and the Gmail draft. Nothing
real is read or written: not this repo's data, not operations, not GitHub,
not Supabase, not Gmail.

The real gates run unchanged: validate_repository.py, z2_release_auth.py and
build_release_manifest.py. Only the outside services are mocked.

State machine, persisted to <workdir>/state.json after every step:

    approved_exact_sha → validated → tagged → bundled → attested
        → released → catalog_recorded → email_drafted

Each transition records state, commit, actor, time and status. A failed step
records `failed` and stops; nothing after it runs. Re-running resumes at the
first incomplete step, and every completed step is checked again for drift
(same bytes, same hashes): a repeat run with the same inputs changes nothing.
"""
import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_release_manifest as brm  # noqa: E402
import validate_repository as vr  # noqa: E402
import z2_release_auth as auth  # noqa: E402

STEPS = ["approved_exact_sha", "validated", "tagged", "bundled", "attested",
         "released", "catalog_recorded", "email_drafted"]
SCENARIOS = ["happy", "forged-hash", "mutated-after-approval", "unratified", "missing-license"]
TAG = "dataset-rehearsal-corpus-v1.0.0"
Q_ID = "Q-SANDBOX-REHEARSAL-RELEASE-01"
DATA = "datasets/rehearsal-corpus/v1-2026q4/data.csv"
LICENSE = "datasets/rehearsal-corpus/v1-2026q4/LICENSE"
ACTOR = "sandbox-rehearsal"


class StepFailed(Exception):
    pass


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git(root, *args) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- sandbox setup -----------------------------------------------------------

def write(root: Path, rel: str, data: bytes):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def setup_research(root: Path, scenario: str) -> str:
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "rehearsal@example.invalid")
    git(root, "config", "user.name", "rehearsal")
    data = b"id,score\n1,0.5\n2,0.7\n"
    lic = b"CC0-1.0 (synthetic rehearsal data)\n"
    write(root, DATA, data)
    write(root, LICENSE, lic)
    write(root, "README.md", b"Sandbox research repo for a release rehearsal.\n")
    ds = {"id": "rehearsal-corpus-v1", "slug": "rehearsal-corpus", "method_version": "v1",
          "path": DATA, "sha256": sha256(data), "license": "CC0-1.0",
          "license_file": None if scenario == "missing-license" else LICENSE,
          "rights_ref": "synthetic data, no third-party rights",
          "data_class": "public", "lifecycle": "frozen"}
    write(root, "registry/datasets.json", json.dumps({"datasets": [ds]}, indent=2).encode())
    pub = {"release_tag": TAG, "kind": "dataset", "slug": "rehearsal-corpus",
           "version": "1.0.0", "title": "Rehearsal corpus", "license": "CC0-1.0",
           "authors": ["Sandbox"], "scope": "synthetic", "limitations": "not real data",
           "z2_q_id": Q_ID}
    write(root, "registry/publications.json", json.dumps({"publications": [pub]}, indent=2).encode())
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "rehearsal content")
    return git(root, "rev-parse", "HEAD")


def setup_operations(root: Path, research: Path, commit: str, scenario: str):
    """A SANDBOX Z2 record in the shape .z1-control/ratify.py writes."""
    files = [DATA] if scenario == "missing-license" else [DATA, LICENSE]
    release = {"repo": auth.REPO, "release_tag": TAG, "git_commit": commit,
               "files": [{"path": f, "sha256": sha256((research / f).read_bytes())}
                         for f in files]}
    cand = ("# SANDBOX release candidate — not a real Z2 ratification\n\n"
            "```json research-release\n" + json.dumps(release, indent=2) + "\n```\n").encode()
    rel_dir = "z1-inbox/2026-10-24"
    cand_rel, ruling_rel = f"{rel_dir}/{Q_ID}.md", f"{rel_dir}/Z2_RULINGS_SANDBOX.md"
    z2_hash = auth.signature(cand, "Night", "2026-10-24", "ACCEPT")
    write(root, cand_rel, cand)
    write(root, ruling_rel, f"## {Q_ID} (SANDBOX)\n\n`{z2_hash}`\n".encode())
    entry = {"q_id": Q_ID, "path": cand_rel, "ratified_by": "Night", "ratified_at": "2026-10-24",
             "z2_ruling": ruling_rel, "z2_hash": z2_hash,
             "status": "awaiting_z2" if scenario == "unratified" else "ratified"}
    if scenario == "forged-hash":
        entry["z2_hash"] = "a" * 64
    import yaml
    write(root, "z1-inbox/INDEX.yaml",
          yaml.safe_dump({"ratifiers": ["Night"], "candidates": [entry]}).encode())


def setup(workdir: Path, scenario: str):
    research, ops = workdir / "research", workdir / "operations"
    commit = setup_research(research, scenario)
    setup_operations(ops, research, commit, scenario)
    if scenario == "mutated-after-approval":
        write(research, DATA, b"id,score\n1,0.9\n")  # change after Z2 signed
        reg = json.loads((research / "registry/datasets.json").read_text())
        reg["datasets"][0]["sha256"] = sha256(b"id,score\n1,0.9\n")
        write(research, "registry/datasets.json", json.dumps(reg).encode())
        git(research, "add", "-A")
        git(research, "commit", "-q", "-m", "edit after approval")
    for d in ("services/releases", "services/drafts"):
        (workdir / d).mkdir(parents=True, exist_ok=True)
    state = {"schema": "release_rehearsal_v1", "scenario": scenario, "tag": TAG,
             "approved_commit": commit, "release_commit": None, "current": None,
             "transitions": []}
    (workdir / "state.json").write_text(json.dumps(state, indent=2) + "\n")


# --- mock services -----------------------------------------------------------

def mock_release(workdir: Path, tag: str, dist: Path) -> str:
    """Mock GitHub Release. Same assets again: no-op. Different assets: refuse."""
    target = workdir / "services/releases" / tag
    assets = {p.name: sha256(p.read_bytes()) for p in sorted(dist.iterdir())}
    if target.exists():
        have = json.loads((target / "release.json").read_text())["assets"]
        on_disk = {p.name: sha256(p.read_bytes()) for p in sorted(target.iterdir())
                   if p.name != "release.json"}
        if have != assets or on_disk != assets:
            raise StepFailed(f"release {tag} already exists with different assets; "
                             "a correction must be a new version")
        return "already released, assets identical"
    stage = Path(tempfile.mkdtemp(dir=target.parent))
    for p in dist.iterdir():
        shutil.copy2(p, stage / p.name)
    (stage / "release.json").write_text(json.dumps({"tag": tag, "assets": assets},
                                                    indent=2, sort_keys=True) + "\n")
    stage.rename(target)  # appears all at once or not at all
    return f"released {len(assets)} assets"


def mock_catalog(workdir: Path, tag: str, manifest: dict) -> str:
    """Mock catalog row. Moves to `published` only when the mock release exists."""
    if not (workdir / "services/releases" / tag / "release.json").exists():
        raise StepFailed("no release found; catalog must not claim it")
    path = workdir / "services/catalog.json"
    rows = json.loads(path.read_text()) if path.exists() else {}
    row = {"status": "published", "git_commit": manifest["git_commit"],
           "bundle_sha256": manifest["bundle"]["sha256"], "z2": manifest["z2"]}
    if tag in rows:
        if {k: rows[tag][k] for k in row} != row:
            raise StepFailed(f"catalog row for {tag} disagrees with the release")
        return "catalog row already present, identical"
    rows[tag] = dict(row, entity_version=1)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    return "catalog row written"


def mock_draft(workdir: Path, tag: str, manifest: dict) -> str:
    """Mock Gmail draft: written once, never sent."""
    body = (f"Subject: [HumanAIOS Research] Published: {manifest['publication']['title']} — {tag}\n"
            f"X-Sandbox: rehearsal draft, not sent\n\n"
            f"Version: {tag}\nCommit: {manifest['git_commit']}\n"
            f"Bundle sha256: {manifest['bundle']['sha256']}\n").encode()
    path = workdir / "services/drafts" / f"{tag}.eml"
    if path.exists():
        if path.read_bytes() != body:
            raise StepFailed("existing draft differs; refusing to overwrite")
        return "draft already present, identical"
    path.write_bytes(body)
    return "draft written (not sent)"


# --- steps -------------------------------------------------------------------

def step(name, workdir: Path, st: dict) -> str:
    research, ops = workdir / "research", workdir / "operations"
    if name == "approved_exact_sha":
        # The release commit is main's tip when the release starts, pinned in
        # state so later commits on main cannot change what gets released.
        commit = st.get("release_commit") or git(research, "rev-parse", "HEAD")
        errors, _ = auth.verify(ops, Q_ID, TAG, commit, research)
        if errors:
            raise StepFailed("; ".join(errors))
        st["release_commit"] = commit
        return f"Z2 record verifies for {commit[:12]}"
    commit = st["release_commit"]
    if name == "validated":
        rep = vr.run(research, release=TAG, operations=str(ops), commit=commit)
        if rep.errors:
            raise StepFailed("; ".join(rep.errors))
        return f"{len(rep.warnings)} warning(s)"
    if name == "tagged":
        existing = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{TAG}^{{commit}}"],
                                  cwd=research, capture_output=True, text=True).stdout.strip()
        if existing:
            if existing != commit:
                raise StepFailed(f"tag {TAG} exists at {existing[:12]}, approved {commit[:12]}")
            return "tag already at approved commit"
        git(research, "tag", TAG, commit)
        return f"tagged {commit[:12]}"
    if name == "bundled":
        dist = workdir / "dist"
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp)
            brm.build(research, TAG, fresh / "dist", fresh / "notes", ops, f"refs/tags/{TAG}")
            for line in (fresh / "dist/checksums.sha256").read_text().splitlines():
                digest, name_ = line.split("  ")
                if sha256((fresh / "dist" / name_).read_bytes()) != digest:
                    raise StepFailed(f"checksum mismatch for {name_}")
            if dist.exists():
                old = {p.name: p.read_bytes() for p in dist.iterdir()}
                new = {p.name: p.read_bytes() for p in (fresh / "dist").iterdir()}
                if old != new:
                    raise StepFailed("rebuilt bundle differs from the earlier one")
                return "rebuilt bundle is byte-identical"
            shutil.copytree(fresh / "dist", dist)
        return "bundle built, checksums verified"
    if name == "attested":
        dist = workdir / "dist"
        subjects = {p.name: sha256(p.read_bytes()) for p in sorted(dist.iterdir())}
        body = json.dumps({"mock": "provenance statement, not signed",
                           "commit": commit, "subjects": subjects},
                          indent=2, sort_keys=True) + "\n"
        path = workdir / "attestation.json"
        if path.exists() and path.read_text() != body:
            raise StepFailed("attestation no longer matches the bundle")
        path.write_text(body)
        return "mock attestation over bundle"
    manifest = json.loads((workdir / "dist/manifest.json").read_text())
    if name == "released":
        return mock_release(workdir, TAG, workdir / "dist")
    if name == "catalog_recorded":
        return mock_catalog(workdir, TAG, manifest)
    if name == "email_drafted":
        return mock_draft(workdir, TAG, manifest)
    raise ValueError(name)


def record(workdir: Path, st: dict, name: str, status: str, detail: str):
    st["transitions"].append({"state": name, "status": status, "detail": detail,
                              "commit": st.get("release_commit"), "actor": ACTOR, "at": now()})
    if status == "ok":
        st["current"] = name
    (workdir / "state.json").write_text(json.dumps(st, indent=2) + "\n")


def run(workdir: Path, scenario: str = "happy", fail_at=None) -> dict:
    workdir = Path(workdir)
    if not (workdir / "state.json").exists():
        # A fresh rehearsal only writes into an empty directory, so it can
        # never overwrite real files. A resume is found by its state.json.
        if workdir.exists() and any(workdir.iterdir()):
            raise SystemExit(f"{workdir} is not empty and has no state.json; "
                             "use an empty directory for a new rehearsal")
        setup(workdir, scenario)
    st = json.loads((workdir / "state.json").read_text())
    done = STEPS.index(st["current"]) + 1 if st["current"] else 0
    # Re-check finished steps for drift, then continue from the first open one.
    for i, name in enumerate(STEPS):
        try:
            if name == fail_at:
                raise StepFailed(f"injected failure at {name}")
            detail = step(name, workdir, st)
        except (StepFailed, SystemExit, subprocess.CalledProcessError,
                OSError, ValueError, KeyError) as e:
            # Real failures (unauthorized build, git error, bad mock metadata)
            # are recorded like injected ones, so resume sees them.
            record(workdir, st, name, "failed", str(e) or type(e).__name__)
            st["result"] = "failed"
            return st
        if i >= done:
            record(workdir, st, name, "ok", detail)
    st["result"] = "complete"
    return st


def summary(workdir: Path) -> dict:
    workdir = Path(workdir)
    releases = sorted(p.name for p in (workdir / "services/releases").iterdir()
                      if p.is_dir() and (p / "release.json").exists())
    catalog = workdir / "services/catalog.json"
    return {"releases": releases,
            "catalog": json.loads(catalog.read_text()) if catalog.exists() else {},
            "drafts": sorted(p.name for p in (workdir / "services/drafts").iterdir())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--scenario", choices=SCENARIOS, default="happy")
    ap.add_argument("--fail-at", choices=STEPS)
    args = ap.parse_args(argv)
    st = run(Path(args.workdir), args.scenario, args.fail_at)
    last = st["transitions"][-1] if st["transitions"] else {}
    print(f"{st['scenario']}: {st['result']} at {last.get('state')} — {last.get('detail')}")
    print(json.dumps(summary(Path(args.workdir)), indent=2, sort_keys=True))
    return 0 if st["result"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())

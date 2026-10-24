#!/usr/bin/env python3
"""Build a reproducible release bundle for a publication tag.

    python3 scripts/build_release_manifest.py --tag paper-<slug>-vX.Y.Z \
        --operations ../operations --out dist/

Writes a flat directory (GitHub Release assets do not nest):
    dist/<tag>.tar.gz      the Z2-approved files at the tagged commit, sorted,
                           mtime/owner zeroed; each checked against its approved
                           SHA-256 before it is packed
    dist/manifest.json     tag, commit, publication metadata, per-file SHA-256
    dist/checksums.sha256  SHA-256 of the two files above
and notes/<tag>.md, the human release-notes header (kept out of dist/).

Same commit + same approved file list = byte-identical bundle. Files come
from `git show <commit>:<path>`, never the working tree.
"""
import argparse
import gzip
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory  # noqa: E402
import z2_release_auth  # noqa: E402

NOTES = """# What this release is

{summary}

## Publication

- Title: {title}
- Tag: `{tag}`
- Commit: `{commit}`
- Method version: {method_version}
- License: {license}
- DOI: {doi}
- Z2 ratification: `{q_id}` (`{z2}`)

## Reproducibility

- Bundle: `{tag}.tar.gz`
- Manifest: `manifest.json`
- Checksums: `checksums.sha256`
- Provenance: GitHub artifact attestation on this release's assets

## Corrections

{corrections}

## Change log
"""


def deterministic_tar_gz(blobs) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel, data in blobs:
            info = tarfile.TarInfo(rel)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def build(root: Path, tag: str, out: Path, notes_dir: Path, operations: Path,
          commit: str = "HEAD") -> dict:
    pubs = json.loads((root / "registry/publications.json").read_text())["publications"]
    match = [p for p in pubs if p.get("release_tag") == tag]
    if len(match) != 1:
        raise SystemExit(f"tag {tag}: expected one entry in registry/publications.json, "
                         f"found {len(match)}")
    pub = match[0]
    commit = subprocess.run(["git", "rev-parse", f"{commit}^{{commit}}"], cwd=root, check=True,
                            capture_output=True, text=True).stdout.strip()
    errors, files = z2_release_auth.verify(Path(operations), str(pub.get("z2_q_id")),
                                           tag, commit, root)
    errors = errors or z2_release_auth.dataset_rights_errors(root, commit, files)
    if errors:
        raise SystemExit("not authorized:\n  " + "\n  ".join(errors))
    blobs = [(f, z2_release_auth.git_bytes(root, commit, f)) for f in files]
    bundle = deterministic_tar_gz(blobs)
    index = z2_release_auth.load_index(Path(operations))
    z2_hash = next(c["z2_hash"] for c in index["candidates"] if c.get("q_id") == pub["z2_q_id"])

    manifest = {
        "schema_version": 1,
        "release_tag": tag,
        "git_commit": commit,
        "z2": {"q_id": pub["z2_q_id"], "z2_hash": z2_hash},
        "publication": {k: pub.get(k) for k in
                        ("kind", "slug", "version", "title", "authors", "license",
                         "method_version", "doi", "scope", "limitations")},
        "bundle": {"name": f"{tag}.tar.gz", "sha256": inventory.sha256_bytes(bundle),
                   "bytes": len(bundle)},
        "files": [{"path": f, "sha256": inventory.sha256_bytes(d)} for f, d in blobs],
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

    out.mkdir(parents=True, exist_ok=True)
    (out / f"{tag}.tar.gz").write_bytes(bundle)
    (out / "manifest.json").write_text(manifest_text)
    (out / "checksums.sha256").write_text(
        f"{inventory.sha256_bytes(bundle)}  {tag}.tar.gz\n"
        f"{inventory.sha256_bytes(manifest_text.encode())}  manifest.json\n")

    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / f"{tag}.md").write_text(NOTES.format(
        summary=pub.get("summary") or "_Summary pending._",
        title=pub.get("title"), tag=tag, commit=commit,
        method_version=pub.get("method_version") or "n/a",
        license=pub.get("license"), doi=pub.get("doi") or "pending",
        q_id=pub["z2_q_id"], z2=z2_hash,
        corrections=pub.get("corrections") or "None."))
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(inventory.ROOT))
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--notes-dir", default="notes")
    ap.add_argument("--operations", required=True, help="humanaios-ui/operations checkout")
    ap.add_argument("--commit", default="HEAD")
    args = ap.parse_args(argv)
    m = build(Path(args.root).resolve(), args.tag, Path(args.out), Path(args.notes_dir),
              Path(args.operations), args.commit)
    print(f"{args.tag}: {len(m['files'])} files, bundle sha256 {m['bundle']['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

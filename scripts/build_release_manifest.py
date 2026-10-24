#!/usr/bin/env python3
"""Build a reproducible release bundle for a publication tag.

    python3 scripts/build_release_manifest.py --tag paper-<slug>-vX.Y.Z --out dist/

Writes a flat directory (GitHub Release assets do not nest):
    dist/<tag>.tar.gz      declared paths, sorted, mtime/owner zeroed
    dist/manifest.json     tag, commit, publication metadata, per-file SHA-256
    dist/checksums.sha256  SHA-256 of the two files above
and notes/<tag>.md, the human release-notes header (kept out of dist/).

Same commit + same registry entry = byte-identical bundle.
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

NOTES = """# What this release is

{summary}

## Publication

- Title: {title}
- Tag: `{tag}`
- Commit: `{commit}`
- Method version: {method_version}
- License: {license}
- DOI: {doi}
- Z2 ratification hash: `{z2}`

## Reproducibility

- Bundle: `{tag}.tar.gz`
- Manifest: `manifest.json`
- Checksums: `checksums.sha256`
- Provenance: GitHub artifact attestation on this release's assets

## Corrections

{corrections}

## Change log
"""


def expand(root: Path, declared):
    tracked = set(inventory.tracked_files(root))
    files = set()
    for p in declared:
        p = p.rstrip("/")
        hits = {f for f in tracked if f == p or f.startswith(p + "/")}
        if not hits:
            raise SystemExit(f"declared path {p} matches no tracked file")
        files |= hits
    return sorted(files)


def deterministic_tar_gz(root: Path, files) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in files:
            data = (root / rel).read_bytes()
            info = tarfile.TarInfo(rel)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def build(root: Path, tag: str, out: Path, notes_dir: Path) -> dict:
    pubs = json.loads((root / "registry/publications.json").read_text())["publications"]
    match = [p for p in pubs if p.get("release_tag") == tag]
    if not match:
        raise SystemExit(f"tag {tag}: no entry in registry/publications.json")
    pub = match[0]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                            capture_output=True, text=True).stdout.strip()
    files = expand(root, pub.get("paths", []))
    bundle = deterministic_tar_gz(root, files)

    manifest = {
        "schema_version": 1,
        "release_tag": tag,
        "git_commit": commit,
        "publication": {k: pub.get(k) for k in
                        ("kind", "slug", "version", "title", "authors", "license",
                         "method_version", "doi", "z2_ratification_hash")},
        "bundle": {"name": f"{tag}.tar.gz", "sha256": inventory.sha256_bytes(bundle),
                   "bytes": len(bundle)},
        "files": [{"path": f, "sha256": inventory.sha256_bytes((root / f).read_bytes())}
                  for f in files],
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
        z2=pub.get("z2_ratification_hash"),
        corrections=pub.get("corrections") or "None."))
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(inventory.ROOT))
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--notes-dir", default="notes")
    args = ap.parse_args(argv)
    m = build(Path(args.root).resolve(), args.tag, Path(args.out), Path(args.notes_dir))
    print(f"{args.tag}: {len(m['files'])} files, bundle sha256 {m['bundle']['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

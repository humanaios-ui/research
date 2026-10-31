#!/usr/bin/env python3
"""Deterministic inventory of this repository and, optionally, an Azure
Resource Graph (ARG) CSV export.

    python3 scripts/inventory.py                      # write registry/generated/
    python3 scripts/inventory.py --check              # fail if committed output is stale
    python3 scripts/inventory.py --arg-csv export.csv --private-out ~/aios-private/arg/

Output is content-addressed: no timestamps, no commit SHA, sorted records.
The same tree always yields the same bytes, so --check can gate CI.

Public-repo rule: Azure inventory is operational data and never enters this
repository, not even sanitized (names, groups and regions reveal topology, and
a hash of a predictable resource id is not anonymization). --private-out must
be outside the repo; validate_repository.py rejects ARG-shaped files.
"""
import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = "registry/generated"
OUTPUT_FILES = ("inventory.json", "inventory.csv", "inventory.md",
                "validation.json", "checksums.sha256")

# canonical field <- first present source column (case-insensitive)
ARG_ALIASES = {
    "resource_name": ["name", "resourceName", "resource_name"],
    "resource_type": ["type", "resourceType", "resource_type"],
    "resource_group": ["resourceGroup", "resource_group", "rg"],
    "region": ["location", "region"],
    "azure_id": ["id", "resourceId", "resource_id"],
    # already-sanitized snapshots carry these instead of azure_id
    "azure_id_complete": ["azure_id_complete"],
    "azure_id_sha256": ["azure_id_sha256"],
}
# Columns that are expected but deliberately dropped from public output.
ARG_DROPPED = {"subscriptionid", "tenantid", "tags", "properties", "sku",
               "kind", "managedby", "identity", "zones", "plan"}
SANITIZED_COLUMNS = ["resource_name", "resource_type", "resource_group",
                     "region", "azure_id_complete", "azure_id_sha256"]

# (path prefix, bucket, lifecycle). First match wins. Buckets follow the
# publishing methodology: source | publication-data | generated | operational.
CLASS_RULES = [
    ("datasets/", "publication-data", "frozen"),
    ("corrections/", "publication-data", "frozen"),
    ("papers/", "source", "draft"),
    ("supplementary/", "source", "active"),
    ("registry/", "source", "active"),
    ("scripts/", "source", "active"),
    ("tests/", "source", "active"),
    ("infra/", "source", "active"),
    ("docs/", "source", "active"),
    (".github/", "source", "active"),
    (".claude/", "source", "active"),
    (".agents/", "source", "active"),
    (".codex/", "source", "active"),
]
ROOT_FILES = {"README.md", "LICENSE", "CITATION.cff", "CONTRIBUTING.md",
              "SECURITY.md", "CODEOWNERS", ".gitignore"}
# README.md files inside frozen trees are navigation, not published data.
FROZEN_EXEMPT_NAMES = {"README.md"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def is_complete_azure_id(value: str) -> bool:
    if not value or "..." in value or "…" in value:
        return False
    low = value.lower()
    return low.startswith("/subscriptions/") and "/resourcegroups/" in low


def tracked_files(root: Path) -> list:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                         capture_output=True).stdout.decode()
    return sorted(p for p in out.split("\0")
                  if p and not p.startswith(GENERATED_DIR + "/"))


def classify(path: str):
    for prefix, bucket, lifecycle in CLASS_RULES:
        if path.startswith(prefix):
            if lifecycle == "frozen" and Path(path).name in FROZEN_EXEMPT_NAMES:
                return "source", "active"
            return bucket, lifecycle
    if path in ROOT_FILES:
        return "source", "active"
    return "unclassified", "draft"


def load_registry(root: Path) -> dict:
    by_path = {}
    reg = root / "registry" / "datasets.json"
    if reg.exists():
        for ds in json.loads(reg.read_text())["datasets"]:
            by_path[ds["path"]] = ds
    return by_path


def file_records(root: Path):
    registry = load_registry(root)
    records, warnings = [], []
    for path in tracked_files(root):
        full = root / path
        if not full.is_file():  # deleted in worktree but still in index
            continue
        data = full.read_bytes()
        bucket, lifecycle = classify(path)
        ds = registry.get(path)
        rec = {
            "inventory_id": "git:" + path,
            "source_system": "github",
            "kind": "file",
            "name": Path(path).name,
            "path": path,
            "bytes": len(data),
            "sha256": sha256_bytes(data),
            "git_blob_sha": git_blob_sha(data),
            "bucket": bucket,
            "lifecycle": ds["lifecycle"] if ds else lifecycle,
            "data_class": ds["data_class"] if ds else "public",
            "dataset_id": ds["id"] if ds else "",
        }
        records.append(rec)
        if bucket == "unclassified":
            warnings.append({"severity": "warning", "path": path,
                             "issue": "unclassified path",
                             "remediation": "Move under a known top-level directory or add a rule to CLASS_RULES."})
    return records, warnings


def resolve_columns(headers):
    lower = {h.lower(): h for h in headers}
    mapping, used = {}, set()
    for canon, aliases in ARG_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lower:
                mapping[canon] = lower[alias.lower()]
                used.add(alias.lower())
                break
    unmapped = sorted(h for h in headers
                      if h.lower() not in used and h.lower() not in ARG_DROPPED)
    return mapping, unmapped


def sanitize_arg_rows(text: str):
    """Raw or already-sanitized ARG CSV -> (sanitized rows, warnings)."""
    reader = csv.DictReader(io.StringIO(text))
    mapping, unmapped = resolve_columns(reader.fieldnames or [])
    warnings = [{"severity": "warning", "column": c,
                 "issue": "unmapped ARG column dropped",
                 "remediation": "Add an alias in ARG_ALIASES or to ARG_DROPPED."}
                for c in unmapped]
    for required in ("resource_name", "resource_type", "resource_group"):
        if required not in mapping:
            raise SystemExit(f"ARG CSV has no column for {required}; headers={reader.fieldnames}")
    rows = []
    for raw in reader:
        get = lambda c: (raw.get(mapping[c]) or "").strip() if c in mapping else ""
        if "azure_id" in mapping:
            azure_id = get("azure_id")
            complete = is_complete_azure_id(azure_id)
            id_hash = sha256_bytes(azure_id.lower().encode()) if complete else ""
        else:
            complete = get("azure_id_complete").lower() == "true"
            id_hash = get("azure_id_sha256")
        row = {
            "resource_name": get("resource_name"),
            "resource_type": get("resource_type").lower(),
            "resource_group": get("resource_group"),
            "region": get("region").lower(),
            "azure_id_complete": "true" if complete else "false",
            "azure_id_sha256": id_hash,
        }
        rows.append(row)
        if not complete:
            warnings.append({"severity": "warning",
                             "resource": f"{row['resource_group']}/{row['resource_name']}",
                             "issue": "azure_id incomplete or truncated",
                             "remediation": "Re-query Azure Resource Graph using name/resourceGroup and capture the full id."})
    rows.sort(key=lambda r: (r["resource_type"], r["resource_group"], r["resource_name"]))
    return rows, warnings


def azure_records(rows):
    out = []
    for r in rows:
        key = f"{r['resource_type']}|{r['resource_group']}|{r['resource_name']}".lower()
        out.append({
            "inventory_id": "azure:" + sha256_bytes(key.encode())[:16],
            "source_system": "azure-resource-graph",
            "kind": "azure-resource",
            "name": r["resource_name"],
            "resource_type": r["resource_type"],
            "resource_group": r["resource_group"],
            "region": r["region"],
            "azure_id_complete": r["azure_id_complete"] == "true",
            "azure_id_sha256": r["azure_id_sha256"],
            "data_class": "internal",
            "lifecycle": "active",
        })
    return out


def render_private_arg(arg_csv) -> dict:
    """Azure inventory outputs, for a directory outside the public repo."""
    rows, warnings = sanitize_arg_rows(Path(arg_csv).read_text(encoding="utf-8-sig"))
    return {
        "azure-inventory.json": json.dumps({"schema_version": 1, "records": azure_records(rows)},
                                           indent=2, sort_keys=True) + "\n",
        "azure-validation.json": json.dumps({"warnings": warnings}, indent=2, sort_keys=True) + "\n",
    }


def render(root: Path):
    files, warnings = file_records(root)
    records = files

    fields = ["inventory_id", "source_system", "kind", "name", "path", "bytes",
              "sha256", "git_blob_sha", "bucket", "lifecycle", "data_class",
              "dataset_id"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for r in records:
        w.writerow({k: r.get(k, "") for k in fields})

    md = ["# Repository inventory", "",
          "Generated by `scripts/inventory.py`. Do not edit by hand.", "",
          f"- Files: {len(files)}",
          f"- Warnings: {len(warnings)}", "",
          "## Files", "", "| Path | Bucket | Lifecycle | Bytes | SHA-256 |",
          "|:--|:--|:--|--:|:--|"]
    md += [f"| `{r['path']}` | {r['bucket']} | {r['lifecycle']} | {r['bytes']} | `{r['sha256'][:12]}` |"
           for r in files]
    if warnings:
        md += ["", "## Warnings", ""]
        md += ["- " + w["path"] + ": " + w["issue"] for w in warnings]

    checksums = "".join(f"{r['sha256']}  {r['path']}\n" for r in files
                        if r["bucket"] == "publication-data")
    return {
        "inventory.json": json.dumps({"schema_version": 1, "records": records},
                                     indent=2, sort_keys=True) + "\n",
        "inventory.csv": buf.getvalue(),
        "inventory.md": "\n".join(md) + "\n",
        "validation.json": json.dumps({"warnings": warnings}, indent=2, sort_keys=True) + "\n",
        "checksums.sha256": checksums,
    }


def write_outputs(outputs, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        (out_dir / name).write_text(text, encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=None, help=f"Output directory. Default: {GENERATED_DIR}")
    ap.add_argument("--check", action="store_true", help="Fail if committed outputs are stale.")
    ap.add_argument("--arg-csv", help="Azure Resource Graph CSV export (raw).")
    ap.add_argument("--private-out", help="Directory OUTSIDE this repo for Azure outputs.")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    if args.arg_csv:
        if not args.private_out:
            ap.error("--arg-csv needs --private-out (Azure inventory stays out of this repo)")
        private = Path(args.private_out).expanduser().resolve()
        if private == root or root in private.parents:
            ap.error(f"--private-out {private} is inside the public repo; choose a path outside it")
        write_outputs(render_private_arg(args.arg_csv), private)
        print(f"wrote Azure inventory to {private}")
        return 0

    outputs = render(root)
    committed = root / (args.out or GENERATED_DIR)

    if args.check:
        stale = [n for n, text in outputs.items()
                 if not (committed / n).exists()
                 or (committed / n).read_text(encoding="utf-8") != text]
        if stale:
            print("inventory is stale: " + ", ".join(stale), file=sys.stderr)
            print("run: python3 scripts/inventory.py", file=sys.stderr)
            return 1
        print(f"inventory up to date ({len(outputs)} files)")
        return 0

    write_outputs(outputs, committed)
    print(f"wrote {len(outputs)} files to {committed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

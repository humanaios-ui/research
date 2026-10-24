# Contributing and publishing

This repository is the **publication ledger**: frozen papers, datasets, and
supplementary material. `humanaios-ui/operations` is the operational source of
truth and holds governance (Z1 propose / Z2 ratify / Z3 execute).

## Systems of record

| Information | System of record | Copies |
|:--|:--|:--|
| Paper source, dataset manifests, methodology | Git (this repo) | Catalog DB |
| Frozen datasets (small) | Git, registered in `registry/datasets.json` | Release assets |
| Published artifacts (PDF, bundles) | GitHub Release on an immutable tag | Catalog DB |
| Release approval | Z2 ratification hash in `registry/publications.json` | PR state |
| Azure inventory | Azure Resource Graph | Sanitized snapshot in `registry/` |
| Secrets | GitHub Environments / cloud secret stores | Never committed |

Database backups are operational recovery. **Tag + release asset + checksum is
the publication record.**

## Naming

| Object | Convention | Example |
|:--|:--|:--|
| Paper / dataset slug | lowercase kebab-case | `acat-corpus` |
| Dataset snapshot dir | `datasets/<slug>/v<method>-<period>/` | `datasets/acat-corpus/v5-3-2026q1/` |
| Branch | `feat/`, `fix/`, `docs/` + `<issue>-<slug>` | `feat/142-release-manifest` |
| Paper tag | `paper-<slug>-vX.Y.Z` | `paper-sycophancy-under-pressure-v1.0.0` |
| Dataset tag | `dataset-<slug>-vX.Y.Z` | `dataset-acat-corpus-v5.3.0` |
| Errata | `corrections/<slug>/errata-YYYY-MM-DD.md` | `errata-2026-11-14.md` |

`datasets/acat_corpus_v2.csv` predates this convention and stays where it is:
moving a published file rewrites it.

## Rules CI enforces

`scripts/validate_repository.py` (run in `.github/workflows/ci.yml`):

- Only declared top-level directories. No committed `build/`, `dist/`, `artifacts/`.
- Every file under `datasets/` is registered with a matching SHA-256.
- Files under `datasets/` and `corrections/` are append-only versus the PR base.
- No Azure subscription ids, private keys, storage keys, or tokens.
- A release tag must match an `approved` entry in `registry/publications.json`
  that carries a 64-hex Z2 ratification hash.

`scripts/inventory.py --check` fails when `registry/generated/` is stale.
After changing tracked files, run `git add -A && python3 scripts/inventory.py`
and commit the result.

## Publication lifecycle

```
draft → candidate → validated → approved (Z2 hash) → tagged → published
                                                         ↘ corrected (new patch release only)
```

A failed release job never advances the state to `published`.

## Commit size

Authored commits touch at most 13 files (P19). Split larger work into
several commits or PRs.

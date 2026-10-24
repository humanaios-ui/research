# Publishing architecture — decision record

**Status:** Z1 proposal, awaiting Z2 ratification.
**Date:** 2026-10-24
**Source:** "Repository Organization and Publishing Methodology for HumanAIOS
Research" (external report), reviewed and corrected below.

## Decision

| Layer | Choice |
|:--|:--|
| Publication ledger | This repo: Git commits, immutable tags, GitHub Releases |
| Release approval | Z2 ratification hash in `registry/publications.json`, checked by CI |
| Catalog / workflow DB | Supabase Postgres (`infra/supabase/migrations/`) |
| Global event store | Azure Cosmos DB **only** after a measured need |
| CI artifacts | Short-lived diagnostics only (90-day default retention) |
| Announcements | Gmail draft, human sends |

Weighted score from the report, re-checked: Supabase 83/100, Cosmos 75/100.
The gap comes from relational fit (20% weight) and portability. Cosmos wins on
global write scale and Azure fit, which this repo does not need today.

## Corrections to the source report

1. **Z2 gate was missing.** "Approved" now means a 64-hex Z2 ratification hash
   in the registry. `validate_repository.py --release` blocks tags without it.
2. **No falsifiers.** Added below, as operations governance requires.
3. **Commit size.** The proposed tree was ~40 files in one change. P19 caps
   authored commits at 13 files; this work landed as three commits.
4. **CI example did not run.** It lacked `setup-python`, ran scripts before
   installing dependencies, never installed `mkdocs`, used `version: latest`
   for the Supabase CLI, and uploaded `dist/*` which skips nested files.
   Fixed: stdlib-only Python, SHA-pinned actions, flat release bundle.
5. **Moving `datasets/acat_corpus_v2.csv`** into the new layout would rewrite a
   published file. It stays in place, registered as a legacy path.
6. **Raw Azure ids in a public repo.** The inventory never writes them; it keeps
   a completeness flag and a SHA-256 of complete ids only.
7. **Mailbox.** Use the existing authorized business identity
   (aioshuman@gmail.com) rather than a new mailbox.
8. **Citations** carried `utm_source=chatgpt.com` tracking. Strip before
   republishing the report.
9. **Action versions** `checkout@v6` and `attest@v4` could not be confirmed.
   Workflows here pin verified SHAs (`checkout` v4.2.2, `setup-python` v5.6.0,
   `attest-build-provenance` v2.4.0).

## Falsifiers

| Claim | Falsified if | Check |
|:--|:--|:--|
| Supabase fits the catalog better than Cosmos | Catalog needs multi-region writes, or sustained >1,000 writes/s, within 12 months | Supabase usage metrics, quarterly |
| Git stays the record; DB is a projection | Catalog disagrees with Git/Releases more than once per quarter after sync is wired | Reconciliation job diff count |
| Releases are reproducible | A clean checkout of a tag yields a bundle whose SHA-256 differs from the published `checksums.sha256` | Rebuild on each release + quarterly sample |
| Frozen means frozen | Any merged PR modifies or deletes a path under `datasets/` or `corrections/` | CI frozen-path check; `git log --diff-filter=MD` audit |

## Needs Night (cannot be done from code)

- [ ] Protect `main`: require PR, 1 approval (2 for `datasets/`, `infra/`), status check `ci / validate`, block force-push and delete.
- [ ] Tag ruleset: restrict create/update/delete of `paper-*` and `dataset-*`.
- [ ] Create `production` environment with required reviewer and tag rule.
- [ ] Enable immutable releases if offered for this repo.
- [ ] Add a `LICENSE` file for `acat-corpus-v2` (README promises CC0 per dataset). Licensing is your call.
- [ ] Decide CODEOWNERS teams for this repo (none exist yet here).
- [ ] Z2: update ZONE_REGISTRY Z-011 (research) cap to reflect this unlock.

## Not done (design only, per instruction)

- No Supabase project created and no migration applied. The migration was
  tested against a local PostgreSQL 16: stale-write rejection, slug check,
  published-version immutability, and anonymous read of published rows only.
  Note: an update that omits `entity_version` still passes; writers must send it.
- No Gmail draft created. Template: `docs/release-email.md`.
- Azure CSV (`AzureResourceGraphResults-New_query_3.csv`) was not in this
  session. To add it: `python3 scripts/inventory.py --sanitize-arg-csv <file>
  --out-csv registry/azure-resources.snapshot.csv`, then regenerate inventory.

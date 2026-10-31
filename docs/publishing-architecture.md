# Publishing architecture — decision record

**Status:** Z1 proposal, awaiting Z2 ratification.
**Date:** 2026-10-24
**Source:** "Repository Organization and Publishing Methodology for HumanAIOS
Research" (external report), reviewed and corrected below.

## Decision

| Layer | Choice |
|:--|:--|
| Publication ledger | This repo: Git commits, immutable tags, GitHub Releases |
| Release approval | Z2 ratification in operations (`z1-inbox/INDEX.yaml`, signed by `.z1-control/ratify.py`, merged by Z2), re-verified by the release job |
| Catalog | Git registry (`registry/*.json`) for now |
| Catalog DB | Supabase Postgres, **deferred** until a measured need; migration is design only |
| Global event store | Azure Cosmos DB: not adopted |
| Azure inventory | Operational data, kept outside this public repo |
| CI artifacts | Short-lived diagnostics only (90-day default retention) |
| Announcements | Gmail draft, human sends (not wired) |

Why Postgres over Cosmos if a DB is ever added: the catalog is relational
(papers, authors, datasets, versions) and small. Cosmos is built for
multi-region writes and very high throughput, which this repo does not have.
The source report's numeric scores (83 vs 75) rested on judgment-based 1-5
criteria scores with no stated method, so they are not repeated here.

## Corrections to the source report

1. **Z2 gate was missing.** A release now needs a ratified operations record
   that binds the tag, the exact commit, and every file's SHA-256. See
   "Release authorization" below.
2. **No falsifiers.** Added below, as operations governance requires.
3. **Commit size.** The proposed tree was ~40 files in one change. P19 caps
   authored commits at 13 files; this work landed as three commits.
4. **CI example did not run.** It lacked `setup-python`, ran scripts before
   installing dependencies, never installed `mkdocs`, used `version: latest`
   for the Supabase CLI, and uploaded `dist/*` which skips nested files.
   Fixed: stdlib-only Python, SHA-pinned actions, flat release bundle.
5. **Moving `datasets/acat_corpus_v2.csv`** into the new layout would rewrite a
   published file. It stays in place, registered as a legacy path.
6. **Azure inventory in a public repo.** Not even sanitized: names, groups and
   regions reveal topology, and a hash of a predictable id is not anonymization.
   `inventory.py --arg-csv` writes only to `--private-out` outside the repo, and
   the validator rejects ARG-shaped files.
7. **Mailbox.** Use the existing authorized business identity
   (aioshuman@gmail.com) rather than a new mailbox.
8. **Citations** carried `utm_source=chatgpt.com` tracking. Strip before
   republishing the report.
9. **Action versions** `checkout@v6` and `attest@v4` could not be confirmed.
   Workflows here pin verified SHAs (`checkout` v4.2.2, `setup-python` v5.6.0,
   `attest-build-provenance` v2.4.0).

## Release authorization

1. Content merges to `main` with a `registry/publications.json` entry naming a
   `z2_q_id`, plus `scope` and `limitations`.
2. Z1 files a candidate in operations `z1-inbox/` with one block:

   ````
   ```json research-release
   {"repo": "humanaios-ui/research", "release_tag": "...",
    "git_commit": "<40-hex main commit>",
    "files": [{"path": "...", "sha256": "..."}]}
   ```
   ````
3. Z2 runs `ratify.py <q_id> --decision ACCEPT --by Night --apply` and merges.
4. The tag is pushed on exactly that commit.
5. `publish.yml` checks out operations `main` and `z2_release_auth.verify`
   requires: status `ratified`, a listed ratifier, the recomputed signature,
   the ruling file, no superseding entry, the same tag and commit, and every
   approved file present at that commit with the approved SHA-256. Datasets in
   the payload also need a `license_file` in the payload and a `rights_ref`.
6. The bundle is built only from those files, read from the commit.

Limit: like `ratify.py`, this pins content, not identity. Binding comes from
Z2 merging the record in operations; CI cannot prove who signed.

`workflow_dispatch` with `dry_run: true` rehearses every gate on an existing
tag and uploads the bundle as a 7-day artifact without attesting or releasing.

## Sandbox rehearsal (Milestone C)

`scripts/rehearse_release.py --workdir <empty dir>` runs the whole release
path end to end with no network: a throwaway research repo with a synthetic
dataset, a SANDBOX Z2 record, the real validator and bundle builder, and
file-backed mocks of GitHub Releases, the catalog, and the Gmail draft.

```
approved_exact_sha → validated → tagged → bundled → attested
    → released → catalog_recorded → email_drafted
```

- `<workdir>/state.json` records every transition (state, commit, actor,
  time, status). A failed step stops the run; nothing after it happens.
- `--fail-at <step>` injects a failure; running again resumes there.
- A repeat run re-checks finished steps for drift and changes nothing.
- The mock release refuses a second release of the same tag with other
  assets, and the catalog never records a release that does not exist.
- `--scenario forged-hash | mutated-after-approval | unratified |
  missing-license` must each end with zero releases.

`tests/test_release_rehearsal.py` runs all of this in CI. It proves the
pipeline logic, not the real services: the GitHub Release, attestation
signing, Supabase and Gmail steps are mocks. A `publish.yml` dry run on a
real tag is still the step before production.

## Falsifiers

| Claim | Falsified if | Check |
|:--|:--|:--|
| No DB needed yet | A real catalog query or workflow cannot be served from `registry/*.json` | Log each such request; 3 in a quarter reopens the DB decision |
| Unauthorized releases are zero | Any GitHub Release exists without a verifying operations record for its tag | Quarterly audit: rerun `validate --release` per release |
| Releases are reproducible | A clean checkout of a tag yields a bundle whose SHA-256 differs from the published `checksums.sha256` | Rebuild on each release + quarterly sample |
| Frozen means frozen | Any merged PR modifies or deletes a path under `datasets/` or `corrections/` | CI frozen-path check; `git log --diff-filter=MD` audit |

## Needs Night (cannot be done from code)

- [ ] Protect `main`: require PR, 1 approval (2 for `datasets/`, `infra/`), status check `ci / validate`, block force-push and delete.
- [ ] Tag ruleset: restrict create/update/delete of `paper-*` and `dataset-*`.
- [ ] Create `production` environment with required reviewer and tag rule.
- [ ] Enable immutable releases if offered for this repo.
- [ ] Add `OPERATIONS_READ_TOKEN` (fine-grained, read-only, operations only) to the `production` environment, unless operations is public.
- [ ] Confirm rights for `acat-corpus-v2`: add its LICENSE file and a `rights_ref` (consent / redistribution clearance). Until then it cannot be released.
- [ ] Decide CODEOWNERS teams for this repo (none exist yet here).
- [ ] Z2: update ZONE_REGISTRY Z-011 (research) cap to reflect this unlock.

## Later milestones (from review on PR #6)

- **B:** read-only ORCID reconciliation reusing `operations/orcid-publications-manager` (fix its DOI external-id keys, group dedup, null handling, retries first). Report-only; no ORCID writes, no auto-publish.
- **C:** done, see "Sandbox rehearsal" above.

## Not done (design only, per instruction)

- No Supabase project created and no migration applied. The migration was
  tested against a local PostgreSQL 16: compare-and-set (omitted, stale and
  replayed versions rejected; of two concurrent writers one wins), slug check,
  published-version immutability, and anonymous read of published rows only.
- No Gmail draft created. Template: `docs/release-email.md`.
- Azure CSV (`AzureResourceGraphResults-New_query_3.csv`) was not in this
  session. To inventory it privately: `python3 scripts/inventory.py --arg-csv
  <file> --private-out <dir outside this repo>`.

# Rights record — acat-corpus-v2

**Dataset:** `datasets/acat_corpus_v2.csv` (registry id `acat-corpus-v2`, sha256 `884ef1506e918b58757a154dfcd4394e1534ad511133b2e377b05d9df81a4237`)
**License:** CC0-1.0, full text in `datasets/LICENSE`. That file covers the legacy root-level dataset files; datasets in their own `datasets/<slug>/<method-version>-<time-window>/` folder carry their own LICENSE.
**Decision:** Z2 (Night), 2026-10-31, option A ("CC0, plus a short rights note as `rights_ref`").

## What the file holds

- 604 rows and 28 columns of ACAT scores: truth, service, harm, autonomy, value, humility, totals, learning index, and phase and pairing fields.
- 64 rows have provider family `Human`. All 64 have the agent name `Anonymous`. Five more rows are `Anonymous` with no provider family.
- The other 535 rows name an AI model, assistant or agent: OpenAI, Google, Anthropic, DeepSeek, Microsoft, Meta, xAI, Mistral and others. Some of these rows have a blank provider family.
- Three rows use the agent name `FloridawestCity`, with no provider family. It is not a known model name. **Resolved:** Z2 (Night) confirmed on 2026-11-02 that it is an agent label, not a person's handle. No anonymization is needed.
- The `raw_response` column is empty in every row. No model text and no free-text human answers are stored.
- A scan found no email addresses and no URLs. The `metadata` column holds processing flags only.

## Basis for public release

- Z2 selected option A, which was offered on condition that the anonymous human submissions were collected for anonymous public release. Z2's selection is the ratifier's attestation of that condition. No consent record is in this repository, and this note does not supply one.
- The file has been publicly readable in this repository since 2026-07-08 (commit `beb1f02`). A formal release adds a versioned bundle and, later, a DOI. A DOI is hard to withdraw, so a correction would be published as a new version, not by deletion.
- Third-party model terms are not engaged by redistribution here, because no model output text is stored, only scores.

## What this record does not do

- It does not authorize a release. Each release still needs its own Z2 `research-release` record, as `docs/publishing-architecture.md` describes.
- It does not change the frozen data file.

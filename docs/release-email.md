# Release announcement (Gmail, draft first)

**Policy:** papers, datasets, and corrections are announced by **draft**. A
person reviews subject, body, and recipients, then sends. Direct send is
allowed only for machine notices such as "release pipeline failed".

**Sender:** aioshuman@gmail.com (authorized business identity).
**OAuth scope:** `https://www.googleapis.com/auth/gmail.compose` only (create
and send drafts). No domain-wide delegation.

**Sequence:** Release job succeeds → render this template from
`dist/manifest.json` → `drafts.create` → human review → `drafts.send` →
catalog `notifications.state = 'sent'`.

## Subject

```
[HumanAIOS Research] Published: {title} — {release_tag}
```

## Body

```
A new HumanAIOS research release is available.

Title: {title}
Version: {release_tag}
Release: {release_url}
Method version: {method_version}
Commit: {git_commit}
Checksums: {release_url}/checksums.sha256   (download from the release assets)

Summary:
{summary}

Corrections: {corrections}
```

## Labels

```
Research/Releases/Draft
Research/Releases/Published
Research/Releases/Corrections
Research/Review
Research/Failures
```

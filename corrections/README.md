# Corrections

Public corrections to published work. **Append only.**

```
corrections/<paper-or-dataset-slug>/errata-YYYY-MM-DD.md
```

A published file is never edited in place. A correction is a new errata file
plus a new patch release (for example `paper-<slug>-v1.0.1`) that links back to
the original tag. CI rejects any modify or delete under `corrections/` and
`datasets/` (`scripts/validate_repository.py --base`).

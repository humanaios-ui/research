# Papers

One folder per paper, named by lowercase kebab-case slug:

```
papers/<paper-slug>/
├── README.md
├── source/         # tex or markdown source
├── figures/
├── tables/
└── supplementary/  # paper-specific only; shared material lives in /supplementary
```

Build outputs (PDF, archives) are produced in CI and attached to a GitHub
Release tagged `paper-<slug>-vX.Y.Z`. They are not committed here.
Release metadata lives in `registry/publications.json`. See `CONTRIBUTING.md`.

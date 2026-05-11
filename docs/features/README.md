# Feature Documentation

Feature docs are **versioned by release**. Each version folder contains a spec for every feature shipped in that release.

## Version Index

| Version | Status | Release date | Description |
|---|---|---|---|
| [v1.0](./v1.0/README.md) | In development | — | Core coaching MVP |
| [v1.1](./v1.1/README.md) | Planned | — | Personalization & history analysis |

## Conventions

- Each feature doc lives at `docs/features/vX.Y/{feature-slug}.md`
- Docs are written **before** implementation (spec-first)
- Once shipped, docs in a version folder are **frozen** — corrections go in the next version or as an erratum note at the top of the file
- Link from `CHANGELOG.md` to the feature doc when a version ships

## Versioning Policy

We follow [Semantic Versioning](https://semver.org/):
- **Major (v2.0)** — breaking API changes
- **Minor (v1.1)** — new features, backwards-compatible
- **Patch (v1.0.1)** — bug fixes only, no new features

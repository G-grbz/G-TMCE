# Security Policy

## Supported versions

Security fixes are applied to the latest released version of G-TMCE and to the `main` branch.

## Reporting a vulnerability

Please do not open a public GitHub issue for a vulnerability that could put users at risk.

Use GitHub's private vulnerability reporting feature for this repository when available. Include:

- affected version or commit;
- a clear description of the issue;
- reproduction steps or a proof of concept;
- the expected security impact;
- any suggested mitigation, if known.

Please avoid accessing data that does not belong to you, disrupting third-party services, or publishing exploit details before a fix is available.

## Security design notes

G-TMCE processes local media files, downloads metadata and optional third-party tooling, and invokes FFmpeg/MKVToolNix. Security-sensitive boundaries therefore include:

- remote URL and redirect validation;
- archive extraction;
- subprocess argument handling;
- local path handling;
- API credentials stored in the per-user configuration directory;
- release and build supply-chain integrity.

CI includes CodeQL analysis and dependency auditing. Release artifacts are generated from version tags only after verification jobs pass, and published with SHA-256 checksums, an SBOM, and GitHub artifact attestations.

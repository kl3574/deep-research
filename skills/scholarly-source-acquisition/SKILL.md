---
name: scholarly-source-acquisition
description: Acquire one already-selected scholarly PDF from an explicit public URL into a validated, auditable artifact. Use when discovery is complete and paper reading needs a verified local source. Not for search or ranking, paywall or CAPTCHA bypass, interpretation, Zotero writes, or graph mutation.
---

# Scholarly Source Acquisition

Fetch one caller-selected public PDF as untrusted bytes and produce an auditable
acquisition result. Read [references/contracts.md](references/contracts.md) for
schemas, limits, transport policy, and failure semantics.

## Required workflow

1. Accept exactly one `AcquisitionCandidate/v1` with the selected URL, source
   type, access basis, destination, and discovery digest when applicable.
2. Run `plan`; it must pass without DNS or network access.
3. Run `fetch` for only the approved URL and transport profile. Do not substitute
   mirrors or infer a different source.
4. Run `validate` against the live PDF. For an acquired result, verify regular
   file, size, `%PDF-` magic, and SHA-256.
5. Hand only a validated acquired artifact to the `PaperSourceBundle/v1` builder,
   which must independently recompute the same source digest.

Use `scripts/source_acquisition.py --help` for commands and fields.

## Safety gates

- Allow only explicit public `http` or `https` repository, institutional,
  author, preprint, or publisher-open URLs.
- Never send credentials, cookies, referrers, authorization headers, or browser
  sessions; never solve CAPTCHAs or bypass paywalls.
- `direct` ignores proxy environment variables. `loopback-proxy` requires an
  explicit unauthenticated loopback HTTP proxy and changes transport only.
- Enforce public-DNS/SSRF checks, redirects, one wall-clock deadline, byte limits,
  HTTP 200, PDF media/signature checks, exclusive output, and partial cleanup.
- Preserve structured failures. Acquisition proves byte integrity, not license,
  bibliographic identity, scientific quality, or evidentiary support.

Route discovery to `$scholar-discovery`, reading to `$learn-from-papers`, Zotero
mutation to `$curate-research-to-zotero`, and graph mutation to
`$research-knowledge-network`.

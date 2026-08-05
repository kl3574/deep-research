---
name: zotero-declarative-bridge
description: Execute reviewed, hash-bound mutations on existing Zotero Desktop parents through a constrained local plugin. Use when curation must add exact collection membership, update only a reviewed parent shortTitle, create or update one child note, or attach a verified local PDF without SQLite edits, cloud credentials, arbitrary JavaScript, or blind UI automation.
---

# Zotero Declarative Bridge

Keep semantic curation in `$curate-research-to-zotero`. This skill is only the
local transaction executor for an already reviewed manifest.

## Fixed workflow

1. Read [protocol.md](references/protocol.md) and compile one of the four
   supported operations with [zotero_declarative_bridge.py](scripts/zotero_declarative_bridge.py).
2. Validate the sealed manifest. Never add an operation type or dynamic method
   name to bypass the protocol.
3. Build and inspect the XPI with [build_xpi.py](scripts/build_xpi.py). The build
   must bind the external update manifest and final XPI hash. Follow
   [install-uninstall.md](references/install-uninstall.md); prefer Zotero's
   visible Plugins action for the packed XPI. The stable skill does not install
   source proxies or change profile discovery preferences.
4. Before installation, require Zotero's own `loadManifestFromFile` preflight to
   return the expected ID/version with no `additionalErrors`; offline JSON-schema
   checks are not a substitute for this runtime loader gate.
5. Require registry-active ID/version, a private capability file, and an
   authenticated `probe` before `preview`. XPI presence alone proves nothing.
6. Pass the explicit private capability file to `probe`, then run `preview`.
   Review its receipt before `apply --yes`.
7. Run `readback` against the same sealed manifest. Treat partial, unknown,
   drift, or hash mismatch as failure, not success.

The bridge is loopback-only and accepts `application/octet-stream` envelopes
authenticated with a nonce and HMAC. The random capability token never crosses
HTTP. It supports only:

- `ensure_collection_membership`
- `ensure_parent_short_title`
- `ensure_child_note`
- `ensure_pdf_attachment`

A sealed manifest is either a multi-operation `db_atomic` transaction containing
only collection, short-title, and note operations, or an attachment-only plan.
Preview refuses to issue a token when more than one PDF still needs import.
`ensure_pdf_attachment` uses Zotero's own single-file transaction and is never
nested inside the bridge database transaction. Mixed metadata/PDF manifests are
invalid and attachment batches must be compiled one parent at a time.

It never removes data, edits any parent bibliography field other than the
explicitly bound `shortTitle`, evaluates code, reads SQLite, or obtains Zotero
sync credentials. A preview expires and is single-use. A
successful local readback does not prove cloud synchronization.

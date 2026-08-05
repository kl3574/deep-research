---
name: zotero-declarative-bridge
description: Execute reviewed, hash-bound mutations on existing Zotero Desktop parents through a constrained local plugin. Use when curation must add exact collection membership, create or update one child note, or attach a verified local PDF without SQLite edits, cloud credentials, arbitrary JavaScript, or blind UI automation.
---

# Zotero Declarative Bridge

Keep semantic curation in `$curate-research-to-zotero`. This skill is only the
local transaction executor for an already reviewed manifest.

## Fixed workflow

1. Read [protocol.md](references/protocol.md) and compile one of the three
   supported operations with [zotero_declarative_bridge.py](scripts/zotero_declarative_bridge.py).
2. Validate the sealed manifest. Never add an operation type or dynamic method
   name to bypass the protocol.
3. Build and inspect the XPI with [build_xpi.py](scripts/build_xpi.py). Follow
   [install-uninstall.md](references/install-uninstall.md); prefer Zotero's
   visible Plugins action and use [install_packed_xpi.py](scripts/install_packed_xpi.py)
   only after explicit authorization when UI installation is inaccessible.
4. Require registry-active ID/version, a private capability file, and an
   authenticated `probe` before `preview`. XPI presence alone proves nothing.
5. Pass the explicit private capability file to `probe`, then run `preview`.
   Review its receipt before `apply --yes`.
6. Run `readback` against the same sealed manifest. Treat partial, unknown,
   drift, or hash mismatch as failure, not success.

The bridge is loopback-only and accepts `application/octet-stream` envelopes
authenticated with a nonce and HMAC. The random capability token never crosses
HTTP. It supports only:

- `ensure_collection_membership`
- `ensure_child_note`
- `ensure_pdf_attachment`

It never removes data, edits parent bibliography, evaluates code, reads SQLite,
or obtains Zotero sync credentials. A preview expires and is single-use. A
successful local readback does not prove cloud synchronization.
